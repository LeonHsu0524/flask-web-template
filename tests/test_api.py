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


# ---- optional registration fields: address + birthday ---------------------
def test_register_stores_address_and_birthday(client, app):
    r = client.post("/api/register", json={
        "username": "dave", "password": "secret1",
        "birthday": "1990-05-20",
        "address": {"country": "Taiwan", "state": "臺北市", "district": "中正區",
                    "zipcode": "100", "street": "重慶南路一段122號"},
    })
    assert r.status_code == 201
    from models import SystemUser
    from datetime import date
    with app.app_context():
        u = SystemUser.query.filter_by(username="dave").first()
        assert u.address["zipcode"] == "100"
        assert u.address["country"] == "Taiwan"
        assert u.birthday == date(1990, 5, 20)


def test_address_required_rejects_when_missing(client, app):
    app.config["REGISTER_ADDRESS_REQUIRED"] = True
    r = client.post("/api/register", json={"username": "eve", "password": "secret1"})
    assert r.status_code == 400


def test_birthday_required_rejects_when_missing(client, app):
    app.config["REGISTER_BIRTHDAY_REQUIRED"] = True
    r = client.post("/api/register", json={"username": "fred", "password": "secret1"})
    assert r.status_code == 400


def test_birthday_rejects_future_or_malformed(client, app):
    assert client.post("/api/register", json={
        "username": "gail", "password": "secret1", "birthday": "2999-01-01"}).status_code == 400
    assert client.post("/api/register", json={
        "username": "gail2", "password": "secret1", "birthday": "not-a-date"}).status_code == 400


def test_email_required_rejects_when_missing(client, app):
    app.config["REGISTER_EMAIL_REQUIRED"] = True
    assert client.post("/api/register", json={
        "username": "noemail", "password": "secret1"}).status_code == 400
    assert client.post("/api/register", json={
        "username": "hasemail", "password": "secret1", "email": "a@b.com"}).status_code == 201


def test_phone_required_rejects_when_missing(client, app):
    app.config["REGISTER_PHONE_REQUIRED"] = True
    assert client.post("/api/register", json={
        "username": "nophone", "password": "secret1"}).status_code == 400


def test_collect_off_ignores_email_phone(client, app):
    app.config["REGISTER_COLLECT_EMAIL"] = False
    app.config["REGISTER_EMAIL_REQUIRED"] = True   # ignored because collect is off
    app.config["REGISTER_COLLECT_PHONE"] = False
    r = client.post("/api/register", json={
        "username": "ivy", "password": "secret1", "email": "x@y.com", "phone": "0900"})
    assert r.status_code == 201
    from models import SystemUser
    with app.app_context():
        u = SystemUser.query.filter_by(username="ivy").first()
        assert u.email is None and u.phone is None


def test_collect_off_ignores_address(client, app):
    app.config["REGISTER_COLLECT_ADDRESS"] = False
    app.config["REGISTER_ADDRESS_REQUIRED"] = True  # ignored because collect is off
    r = client.post("/api/register", json={
        "username": "hank", "password": "secret1",
        "address": {"country": "Taiwan", "street": "x"}})
    assert r.status_code == 201
    from models import SystemUser
    with app.app_context():
        assert SystemUser.query.filter_by(username="hank").first().address is None


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


# ---- self-service account API (/api/v1) -----------------------------------
def _signup(client, username, password="secret1", **extra):
    r = client.post("/api/v1/auth/register",
                    json={"username": username, "password": password, **extra})
    assert r.status_code == 201, r.get_data(as_text=True)
    tok = client.post("/api/v1/auth/login",
                      json={"username": username, "password": password}).get_json()["token"]
    return tok


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_v1_full_flow_register_login_post_get(client):
    tok = _signup(client, "nina")
    # profile
    me = client.get("/api/v1/me", headers=_auth(tok)).get_json()
    assert me["profile"]["username"] == "nina"
    # write own data
    r = client.post("/api/v1/me/data", json={"data": {"steps": 42}, "kind": "message"},
                    headers=_auth(tok))
    assert r.status_code == 201
    # read it back with payload
    body = client.get("/api/v1/me/data", headers=_auth(tok)).get_json()
    assert body["total"] == 1
    assert body["records"][0]["data"] == {"steps": 42}


def test_v1_isolation_between_accounts(client):
    tok_a = _signup(client, "alpha")
    tok_b = _signup(client, "bravo")
    client.post("/api/v1/me/data", json={"data": {"secret": "A"}}, headers=_auth(tok_a))
    # B sees nothing of A's
    assert client.get("/api/v1/me/data", headers=_auth(tok_b)).get_json()["total"] == 0
    # B cannot forge access by registering with A's name/linked_userid
    tok_forge = _signup(client, "evil", name="alpha", linked_userid="alpha")
    assert client.get("/api/v1/me/data", headers=_auth(tok_forge)).get_json()["total"] == 0


def test_v1_requires_bearer(client):
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me/data").status_code == 401
    # a shared API key is NOT accepted on the account endpoints
    assert client.get("/api/v1/me", headers={"X-API-Key": "test-key"}).status_code == 401


def test_v1_token_revoked_on_password_change(client, app):
    tok = _signup(client, "owen")
    assert client.get("/api/v1/me", headers=_auth(tok)).status_code == 200
    # change the password -> password-stamp changes -> old token rejected
    from models import db, SystemUser
    u = SystemUser.query.filter_by(username="owen").first()
    u.set_password("brand-new-pass")
    db.session.commit()
    assert client.get("/api/v1/me", headers=_auth(tok)).status_code == 401


def test_v1_per_page_capped(client, app):
    app.config["API_MAX_PAGE_SIZE"] = 200
    tok = _signup(client, "pam")
    r = client.get("/api/v1/me/data?per_page=100000", headers=_auth(tok)).get_json()
    assert r["per_page"] == 200


def test_v1_readable_kinds_policy(client, app):
    tok = _signup(client, "quinn")
    client.post("/api/v1/me/data", json={"data": 1, "kind": "message"}, headers=_auth(tok))
    client.post("/api/v1/me/data", json={"data": 2, "kind": "secret"}, headers=_auth(tok))
    # no restriction -> both kinds visible
    assert client.get("/api/v1/me/data", headers=_auth(tok)).get_json()["total"] == 2
    # restrict to "message" -> only that kind is returned
    app.config["API_READABLE_KINDS"] = ["message"]
    body = client.get("/api/v1/me/data", headers=_auth(tok)).get_json()
    assert body["total"] == 1 and body["records"][0]["kind"] == "message"
    # ?kind=secret cannot bypass the whitelist
    assert client.get("/api/v1/me/data?kind=secret", headers=_auth(tok)).get_json()["total"] == 0


def test_v1_min_password_length_enforced(client, app):
    app.config["MIN_PASSWORD_LENGTH"] = 8
    r = client.post("/api/v1/auth/register", json={"username": "shorty", "password": "abc"})
    assert r.status_code == 400


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


def test_change_own_password(client, app):
    _make(app, "kim", "user")
    _web_login(client, "kim")
    # wrong current password is rejected
    r = client.post("/change_password", data={
        "current_password": "wrong", "new_password": "newpass1",
        "confirm_password": "newpass1"})
    assert "不正確" in r.get_data(as_text=True)
    # correct current password updates it
    client.post("/change_password", data={
        "current_password": "pw12345", "new_password": "newpass1",
        "confirm_password": "newpass1"})
    from models import db, SystemUser
    with app.app_context():
        assert SystemUser.query.filter_by(username="kim").first().check_password("newpass1")
