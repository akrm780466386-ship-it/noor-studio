import getpass
import re
import secrets

from . import create_app
from .database import get_db
from .security import hash_password

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]{3,80}$")


def main():
    app = create_app()
    with app.app_context():
        database = get_db()
        existing = database.execute(
            "SELECT username FROM admin_users WHERE active = 1 LIMIT 1"
        ).fetchone()
        if existing:
            raise SystemExit(
                f"An active administrator ({existing['username']}) already exists."
            )

        username = input("Admin username (3-80 letters, numbers, . _ -): ").strip()
        if not USERNAME_PATTERN.fullmatch(username):
            raise SystemExit("Invalid username.")
        password = getpass.getpass("Password (at least 14 characters): ")
        confirmation = getpass.getpass("Confirm password: ")
        if len(password) < 14:
            raise SystemExit("Password must contain at least 14 characters.")
        if len(password) > 1024:
            raise SystemExit("Password must not exceed 1024 characters.")
        if password != confirmation:
            raise SystemExit("Passwords do not match.")

        salt = secrets.token_bytes(16)
        database.execute(
            """INSERT INTO admin_users (username, password_hash, password_salt)
               VALUES (?, ?, ?)""",
            (username.lower(), hash_password(password, salt), salt),
        )
        database.commit()
        print("Administrator created. Keep the password in a password manager.")


if __name__ == "__main__":
    main()
