"""
Create (or promote) a super-admin account from the command line.

Usage:
    python create_superadmin.py <username> <password>

If the username already exists, its role is set to 'superadmin' and (optionally)
its password updated. Otherwise a new superadmin account is created.
"""
import sys

from app import create_app
from models import db, SystemUser


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python create_superadmin.py <username> <password>")
        return 1

    username, password = sys.argv[1], sys.argv[2]
    app = create_app()
    with app.app_context():
        db.create_all()  # make sure tables exist
        user = SystemUser.query.filter_by(username=username).first()
        if user:
            user.role = "superadmin"
            user.set_password(password)
            action = "promoted existing account to"
        else:
            user = SystemUser(username=username, name=username, role="superadmin")
            user.set_password(password)
            db.session.add(user)
            action = "created new"
        db.session.commit()
        print(f"OK: {action} superadmin '{username}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
