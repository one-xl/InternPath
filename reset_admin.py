import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from auth import hash_password
from database import Database


def _required_setting(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Set {name} before running this script.")
    return value


def main() -> None:
    username = _required_setting("INTERNPATH_ADMIN_USERNAME")
    password = _required_setting("INTERNPATH_ADMIN_PASSWORD")
    db = Database()
    conn = db.get_connection()
    cursor = conn.cursor()
    hashed = hash_password(password)

    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()

    if row:
        cursor.execute(
            "UPDATE users SET password_hash = ?, role = 'admin' WHERE username = ?",
            (hashed, username),
        )
        print("Updated existing admin password and role.")
    else:
        cursor.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (username, hashed, "admin"),
        )
        print("Created new admin account.")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
