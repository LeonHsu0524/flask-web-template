"""Shared pytest fixtures. Builds the app via the factory in testing mode."""
import pytest

from app import create_app
from models import db, SystemUser


@pytest.fixture()
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_user(app):
    """Create an admin account and return its credentials."""
    with app.app_context():
        user = SystemUser(username="admin", name="Admin", role="admin")
        user.set_password("pw12345")
        db.session.add(user)
        db.session.commit()
    return {"username": "admin", "password": "pw12345"}
