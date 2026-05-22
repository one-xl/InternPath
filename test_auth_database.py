import pytest
from pathlib import Path
from uuid import uuid4

from auth import hash_password, verify_password_hash
from config import Config
from database import Database
from models import FitExamAttempt, FitExamPaper, FitExamQuestion, JobAnalysis, JobPosting


TEST_DB_DIR = Path(__file__).parent / ".test_dbs"


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


def make_analysis() -> JobAnalysis:
    return JobAnalysis(
        skills=["Python"],
        difficulty="medium",
        job_summary="backend intern",
    )


def make_attempt(user_id: int, jd_record_id: int) -> FitExamAttempt:
    return FitExamAttempt(
        user_id=user_id,
        jd_record_id=jd_record_id,
        major_profile="computer science",
        paper=FitExamPaper(
            questions=[
                FitExamQuestion(
                    stem="What is Python?",
                    options=["Language", "Database"],
                    correct_index=0,
                )
            ]
        ),
        answers=[0],
        score=1.0,
    )


def test_password_hash_roundtrip():
    stored = hash_password("abc12345")

    assert verify_password_hash("abc12345", stored)
    assert not verify_password_hash("wrong-password", stored)


def test_create_user_rejects_duplicate_username(db_path):
    db = Database(db_path)

    user_id = db.create_user("Alice", "abc12345")

    assert user_id > 0
    with pytest.raises(ValueError, match="username_taken"):
        db.create_user("alice", "abc12345")


def test_create_user_rejects_duplicate_device_signature(db_path):
    db = Database(db_path)

    db.create_user("alice", "abc12345", "device-1")

    with pytest.raises(ValueError, match="device_already_registered"):
        db.create_user("bob", "abc12345", "device-1")


def test_admin_account_management_actions(db_path):
    db = Database(db_path)
    user_id = db.create_user("alice", "abc12345", "device-1")

    users = db.list_users_with_devices()
    assert users[0]["username"] == "alice"
    assert users[0]["device_count"] == 1

    db.update_user_password(user_id, "newpass123")
    assert db.authenticate_user("alice", "abc12345") is None
    assert db.authenticate_user("alice", "newpass123") is not None

    db.clear_registered_devices(user_id)
    users = db.list_users_with_devices()
    assert users[0]["device_count"] == 0

    db.delete_user(user_id)
    assert db.authenticate_user("alice", "newpass123") is None
    assert db.list_users_with_devices() == []


def test_authenticate_user(db_path):
    db = Database(db_path)
    user_id = db.create_user("alice", "abc12345")

    user = db.authenticate_user("ALICE", "abc12345")

    assert user is not None
    assert user.id == user_id
    assert user.username == "alice"
    assert db.authenticate_user("alice", "wrong-password") is None


def test_jd_records_are_scoped_by_user(db_path):
    db = Database(db_path)
    alice = db.create_user("alice", "abc12345")
    bob = db.create_user("bob", "abc12345")

    alice_jd = db.save_jd_record(alice, "alice jd", make_analysis())
    bob_jd = db.save_jd_record(bob, "bob jd", make_analysis())

    alice_records = db.get_jd_records(alice)
    bob_records = db.get_jd_records(bob)

    assert [record.id for record in alice_records] == [alice_jd]
    assert [record.id for record in bob_records] == [bob_jd]
    assert db.get_jd_record_by_id(alice, bob_jd) is None


def test_job_postings_are_scoped_by_user(db_path):
    db = Database(db_path)
    alice = db.create_user("alice", "abc12345")
    bob = db.create_user("bob", "abc12345")

    db.insert_job_posting(
        JobPosting(user_id=alice, title="Alice role", salary_monthly_k=12.0)
    )
    db.insert_job_posting(
        JobPosting(user_id=bob, title="Bob role", salary_monthly_k=15.0)
    )

    assert [job.title for job in db.list_job_postings(alice)] == ["Alice role"]
    assert [job.title for job in db.list_job_postings(bob)] == ["Bob role"]


def test_fit_scores_are_scoped_by_user(db_path):
    db = Database(db_path)
    alice = db.create_user("alice", "abc12345")
    bob = db.create_user("bob", "abc12345")
    alice_jd = db.save_jd_record(alice, "alice jd", make_analysis())
    bob_jd = db.save_jd_record(bob, "bob jd", make_analysis())

    db.save_fit_exam_attempt(make_attempt(alice, alice_jd))
    db.save_fit_exam_attempt(make_attempt(bob, bob_jd))

    assert set(db.get_latest_fit_score_by_jd(alice)) == {alice_jd}
    assert set(db.get_latest_fit_score_by_jd(bob)) == {bob_jd}


def test_user_data_isolation_single_database(db_path, monkeypatch):
    monkeypatch.setattr(Config, "DB_PATH", db_path)

    alice_db = Database.for_user(1)
    bob_db = Database.for_user(2)
    alice_jd = alice_db.save_jd_record(1, "alice jd", make_analysis())
    bob_jd = bob_db.save_jd_record(2, "bob jd", make_analysis())

    assert alice_db.db_path == bob_db.db_path
    assert Path(alice_db.db_path).is_file()
    assert [record.id for record in alice_db.get_jd_records(1)] == [alice_jd]
    assert [record.id for record in bob_db.get_jd_records(2)] == [bob_jd]
    assert alice_db.get_jd_record_by_id(2, alice_jd) is None
    assert bob_db.get_jd_record_by_id(1, bob_jd) is None
