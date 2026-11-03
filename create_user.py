"""CLI helper to create/reset a login for the audit-doc-stamper app.

Usage:
    python create_user.py <username> <password>
"""
import sys

from app.db import init_db, get_conn
from app.auth import hash_password, get_user_by_username


def main():
    if len(sys.argv) < 3:
        print("Usage: python create_user.py <username> <password> [role: cto|hr|accountant] [full_name]")
        sys.exit(1)

    username, password = sys.argv[1], sys.argv[2]
    role = sys.argv[3] if len(sys.argv) > 3 else "hr"
    full_name = sys.argv[4] if len(sys.argv) > 4 else None

    init_db()

    existing = get_user_by_username(username)
    with get_conn() as conn:
        if existing:
            conn.execute(
                "UPDATE users SET password_hash = ?, role = ?, full_name = ? WHERE username = ?",
                (hash_password(password), role, full_name, username),
            )
            print(f"Updated user '{username}' (role: {role}).")
        else:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
                (username, hash_password(password), role, full_name),
            )
            print(f"Created user '{username}' (role: {role}).")


if __name__ == "__main__":
    main()
