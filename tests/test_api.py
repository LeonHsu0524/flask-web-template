"""Phase 3 — api: register/login/token and API-key protection on /save."""
import pytest

pytestmark = pytest.mark.api


def test_register_and_login_returns_token(client):
    r = client.post("/api/register", json={"username": "alice", "password": "secret1"})
    assert r.status_code == 201

    r = client.post("/login", json={"username": "alice", "password": "secret1"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "success"
    assert body["token"]


def test_login_bad_credentials(client):
    r = client.post("/login", json={"username": "ghost", "password": "nope"})
    assert r.status_code == 401


def test_save_rejected_without_key(client):
    r = client.post("/save", json={"userInfo": {"userID": "U1", "name": "Bob"}})
    assert r.status_code == 401


def test_save_accepted_with_api_key(client):
    payload = {"userInfo": {"userID": "U1", "name": "Bob"}, "data": {"x": 1}}
    r = client.post("/save", json=payload, headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "success"


def test_save_accepted_with_bearer_token(client):
    client.post("/api/register", json={"username": "carol", "password": "secret1"})
    token = client.post("/login", json={"username": "carol", "password": "secret1"}).get_json()["token"]
    payload = {"userInfo": {"userID": "U2", "name": "Carol"}, "data": [1, 2, 3]}
    r = client.post("/save", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_log_requires_key(client):
    assert client.get("/log").status_code == 401
    assert client.get("/log", headers={"X-API-Key": "test-key"}).status_code == 200


# ---- role model: user < admin < superadmin --------------------------------
def _make(app, username, role):
    from models import db, SystemUser
    with app.app_context():
        u = SystemUser(username=username, role=role)
        u.set_password("pw12345")
        db.session.add(u)
        db.session.commit()
        return u.id


def _web_login(client, username):
    return client.post("/web_login", data={"username": username, "password": "pw12345"})


def test_admin_cannot_delete_another_admin(client, app):
    _make(app, "adminA", "admin")
    victim = _make(app, "adminB", "admin")
    _web_login(client, "adminA")
    r = client.post("/admin/delete_account", data={"account_id": victim})
    assert r.status_code == 403
    from models import db, SystemUser
    with app.app_context():
        assert db.session.get(SystemUser, victim) is not None  # still there


def test_admin_cannot_promote_user_to_admin(client, app):
    _make(app, "adminC", "admin")
    target = _make(app, "plain", "user")
    _web_login(client, "adminC")
    client.post("/admin/edit_account", data={"account_id": target, "role": "admin"})
    from models import db, SystemUser
    with app.app_context():
        assert db.session.get(SystemUser, target).role == "user"  # unchanged


def test_superadmin_can_delete_admin(client, app):
    _make(app, "boss", "superadmin")
    victim = _make(app, "adminD", "admin")
    _web_login(client, "boss")
    r = client.post("/admin/delete_account", data={"account_id": victim},
                    follow_redirects=False)
    assert r.status_code in (200, 302)
    from models import db, SystemUser
    with app.app_context():
        assert db.session.get(SystemUser, victim) is None  # gone


def test_plain_user_blocked_from_admin_area(client, app):
    _make(app, "joe", "user")
    _web_login(client, "joe")
    assert client.get("/admin/accounts").status_code == 403
