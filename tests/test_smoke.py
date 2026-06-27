"""Phase 1 — smoke: the app boots and core public pages respond."""
import pytest

pytestmark = pytest.mark.smoke


def test_app_factory_builds(app):
    assert app is not None
    assert app.config["TESTING"] is True


def test_login_page_loads(client):
    resp = client.get("/login")
    assert resp.status_code == 200


def test_register_page_loads(client):
    resp = client.get("/web_register")
    assert resp.status_code == 200


def test_index_redirects_when_logged_out(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (301, 302)
