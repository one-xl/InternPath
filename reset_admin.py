import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import Database
from auth import hash_password

def main():
    db = Database()
    conn = db.get_connection()
    cursor = conn.cursor()

    hashed = hash_password("ChangeMe123!")

    # Check if admin user exists
    cursor.execute("SELECT id FROM users WHERE username = ?", ("admin@example.com",))
    row = cursor.fetchone()

    if row:
        cursor.execute(
            "UPDATE users SET password_hash = ?, role = 'admin' WHERE username = ?",
            (hashed, "admin@example.com")
        )
        print("Updated existing admin@example.com password to ChangeMe123! and role to admin.")
    else:
        cursor.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            ("admin@example.com", hashed, "admin", "2026-05-23T00:00:00")
        )
        print("Created new admin@example.com with password ChangeMe123! and role admin.")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
