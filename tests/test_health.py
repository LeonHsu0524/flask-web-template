"""
Phase 2 — health: live HTTP check against a RUNNING server.

Replaces the old Jenkins `curl -f http://localhost:5000`. Point it at the
deployed/staging server with the TARGET_URL env var:

    TARGET_URL=http://localhost:5000 pytest -m health
"""
import os

import pytest
import requests

pytestmark = pytest.mark.health

TARGET_URL = os.getenv("TARGET_URL", "http://localhost:5000")


def test_server_is_alive():
    """The login page must be reachable and return 2xx/3xx."""
    resp = requests.get(f"{TARGET_URL}/login", timeout=10)
    assert resp.status_code < 400, f"Unexpected status {resp.status_code} from {TARGET_URL}"


def test_protected_api_requires_key():
    """/save must reject unauthenticated POSTs (401)."""
    resp = requests.post(f"{TARGET_URL}/save", json={}, timeout=10)
    assert resp.status_code == 401
