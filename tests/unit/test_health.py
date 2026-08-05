"""Tests for the health check endpoint."""
from fastapi.testclient import TestClient

from app.web_app import app

client = TestClient(app)


def test_health_returns_200():
    """Health endpoint returns 200."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_health_has_timestamp():
    """Health endpoint includes an ISO8601 timestamp."""
    response = client.get("/api/v1/health")
    data = response.json()
    assert data["code"] == 200
    assert data["message"] == "ok"
    assert "timestamp" in data["data"]
    from datetime import datetime

    datetime.fromisoformat(data["data"]["timestamp"])


def test_health_no_auth_required():
    """Health endpoint does not require authentication."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
