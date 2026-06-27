"""Phase 4 — integration: DB read/write through the API + generic JSON storage."""
import pytest

from models import db, SystemUser, UserData, UserInfo

pytestmark = pytest.mark.integration


def test_save_persists_generic_json(client, app):
    payload = {
        "userInfo": {"userID": "D1", "name": "Dave", "phone": "0900"},
        "data": {"any": "shape", "nums": [1, 2, 3]},
    }
    r = client.post("/save", json=payload, headers={"X-API-Key": "test-key"})
    assert r.status_code == 200

    with app.app_context():
        person = UserInfo.query.filter_by(userID="D1", name="Dave").first()
        assert person is not None and person.phone == "0900"
        record = UserData.query.filter_by(userID="D1", name="Dave").first()
        assert record is not None
        assert record.data == {"any": "shape", "nums": [1, 2, 3]}


def test_save_upserts_person_and_appends_records(client, app):
    base = {"userInfo": {"userID": "E1", "name": "Eve"}}
    client.post("/save", json={**base, "data": {"v": 1}}, headers={"X-API-Key": "test-key"})
    client.post("/save", json={**base, "data": {"v": 2}}, headers={"X-API-Key": "test-key"})

    with app.app_context():
        assert UserInfo.query.filter_by(userID="E1").count() == 1
        assert UserData.query.filter_by(userID="E1").count() == 2


def test_seed_default_admin_creates_once(app):
    from app import seed_default_admin
    app.config.update(DEFAULT_ADMIN_ENABLED=True, DEFAULT_ADMIN_USERNAME="seedadmin",
                      DEFAULT_ADMIN_PASSWORD="pw12345", DEFAULT_ADMIN_ROLE="superadmin")
    seed_default_admin(app)
    seed_default_admin(app)  # idempotent: must not duplicate or error
    with app.app_context():
        admins = SystemUser.query.filter_by(username="seedadmin").all()
        assert len(admins) == 1
        assert admins[0].role == "superadmin"
        assert admins[0].check_password("pw12345")


def test_ecpay_mac_value_is_stable(app):
    """The ECPay SDK produces a deterministic CheckMacValue."""
    from app import get_ecpay_sdk
    with app.app_context():
        sdk = get_ecpay_sdk()
        params = {"MerchantID": app.config["ECPAY_MERCHANT_ID"], "TotalAmount": "199"}
        mac1 = sdk.generate_check_value(dict(params))
        mac2 = sdk.generate_check_value(dict(params))
        assert mac1 == mac2 and len(mac1) == 64
