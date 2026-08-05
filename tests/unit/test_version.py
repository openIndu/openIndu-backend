"""Tests for the version endpoint."""
from fastapi.testclient import TestClient

from app.web_app import app

client = TestClient(app)


def test_version_returns_200():
    """Version endpoint returns 200."""
    response = client.get("/api/v1/version")
    assert response.status_code == 200


def test_version_has_required_fields():
    """Version endpoint returns version, git_commit, build_time in data."""
    response = client.get("/api/v1/version")
    data = response.json()
    assert data["code"] == 200
    assert data["message"] == "ok"
    assert "version" in data["data"]
    assert "git_commit" in data["data"]
    assert "build_time" in data["data"]


def test_version_no_auth_required():
    """Version endpoint does not require authentication."""
    response = client.get("/api/v1/version")
    assert response.status_code == 200


def test_version_fallback_values():
    """Without env vars, version falls back to app.version, others to 'unknown'."""
    response = client.get("/api/v1/version")
    data = response.json()["data"]
    assert data["version"] == "0.1.0"  # app.version fallback
    assert data["git_commit"] == "unknown"  # env not set
    assert data["build_time"] == "unknown"  # env not set
