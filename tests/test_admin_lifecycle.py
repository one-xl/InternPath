import pytest
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timedelta

from auth import hash_password
from database import Database
from models import User

TEST_DB_DIR = Path(__file__).parent.parent / ".test_dbs"


@pytest.fixture
def db_path():
    TEST_DB_DIR.mkdir(exist_ok=True)
    path = TEST_DB_DIR / f"{uuid4().hex}.db"
    yield str(path)
    for candidate in TEST_DB_DIR.glob(f"{path.stem}*"):
        try:
            candidate.unlink()
        except OSError:
            continue


def test_admin_create_temp_user(db_path):
    db = Database(db_path)
    expires_at = (datetime.now() + timedelta(days=1)).isoformat()
    
    # 1. Test creation of temp user
    user_id = db.admin_create_temp_user(
        username="temp_test@internpath.temp",
        password_hash=hash_password("TempPassword123!"),
        expires_at=expires_at
    )
    assert user_id > 0

    # 2. Test fetching user by id and check fields
    user = db.get_user_by_id(user_id)
    assert user is not None
    assert user.username == "temp_test@internpath.temp"
    assert user.is_active is True
    assert user.expires_at is not None
    assert user.expires_at.isoformat() == expires_at

    # 3. Check admin_list_users returns is_active and expires_at
    users = db.admin_list_users()
    matched = [u for u in users if u["id"] == user_id]
    assert len(matched) == 1
    assert matched[0]["is_active"] is True
    assert matched[0]["expires_at"] == expires_at


def test_admin_update_user_status_and_expiry(db_path):
    db = Database(db_path)
    user_id = db.create_user("bob", "abc12345")
    
    # Check default active status
    user = db.get_user_by_id(user_id)
    assert user.is_active is True
    assert user.expires_at is None

    # Update status to inactive
    db.admin_update_user_status(user_id, False)
    user = db.get_user_by_id(user_id)
    assert user.is_active is False

    # Update status to active
    db.admin_update_user_status(user_id, True)
    user = db.get_user_by_id(user_id)
    assert user.is_active is True

    # Set expiry date
    new_expiry = (datetime.now() + timedelta(hours=12)).isoformat()
    db.admin_update_user_expiry(user_id, new_expiry)
    user = db.get_user_by_id(user_id)
    assert user.expires_at is not None
    assert user.expires_at.isoformat() == new_expiry

    # Clear expiry
    db.admin_update_user_expiry(user_id, None)
    user = db.get_user_by_id(user_id)
    assert user.expires_at is None


def test_admin_update_user_generation_limit(db_path):
    db = Database(db_path)
    user_id = db.create_user("charlie", "abc12345")
    
    # Check default limit
    user = db.get_user_by_id(user_id)
    assert user.generation_limit == 5

    # Update limit to 10
    db.admin_update_user_generation_limit(user_id, 10)
    user = db.get_user_by_id(user_id)
    assert user.generation_limit == 10

    # Decrement limit
    db.decrement_user_generation_limit(user_id)
    user = db.get_user_by_id(user_id)
    assert user.generation_limit == 9

    # Admin role creation
    admin_id = db.create_user("admin_user", "abc12345")
    # Set role to admin
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET role = 'admin' WHERE id = ?", (admin_id,))
    conn.commit()
    conn.close()
    
    admin = db.get_user_by_id(admin_id)
    assert admin.role == "admin"
    assert admin.generation_limit == 5
    
    # Decrement limit as admin user (should NOT decrement)
    db.decrement_user_generation_limit(admin_id)
    admin = db.get_user_by_id(admin_id)
    assert admin.generation_limit == 5
