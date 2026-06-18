"""Integration tests for document API endpoints.

These tests use FastAPI TestClient with dependency_overrides to verify
API routing, request validation, response formatting, and error handling.
"""
import io
from unittest.mock import MagicMock, patch

import pytest


def _make_user(id=1, phone="13800138000", role="user"):
    user = MagicMock()
    user.id = id
    user.phone = phone
    user.role = role
    user.is_active = True
    user.is_blacklisted = False
    return user


def _make_client(app, auth_user=None):
    """Create a TestClient with dependency overrides set up.

    Clears any existing overrides on the app first to ensure test isolation.
    """
    from fastapi.testclient import TestClient

    from app.core.dependencies import get_db, require_auth, require_admin, require_member

    # Clear previous overrides for test isolation
    app.dependency_overrides.clear()

    mock_db = MagicMock()
    mock_db.query.return_value = MagicMock()
    mock_db.add = MagicMock()
    mock_db.commit = MagicMock()
    mock_db.refresh = MagicMock()

    def _get_db():
        yield mock_db
    app.dependency_overrides[get_db] = _get_db

    if auth_user is not None:
        async def _require_auth():
            return auth_user
        app.dependency_overrides[require_auth] = _require_auth
        app.dependency_overrides[require_admin] = _require_auth
        app.dependency_overrides[require_member] = _require_auth

    client = TestClient(app)
    client._mock_db = mock_db
    return client


class TestDocumentList:
    """Test GET /api/v1/documents."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from app.web_app import app
        self.app = app

    def test_list_empty(self):
        """Listing documents with no data should return empty list."""
        user = _make_user()
        client = _make_client(self.app, auth_user=user)

        response = client.get("/api/v1/documents")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data["data"]
        assert "total" in data["data"]

    def test_list_unauthenticated(self):
        """Listing without auth should stay public."""
        client = _make_client(self.app)
        response = client.get("/api/v1/documents")
        assert response.status_code == 200
        assert "items" in response.json()["data"]

    def test_list_with_pagination(self):
        """Pagination parameters should be accepted."""
        user = _make_user()
        client = _make_client(self.app, auth_user=user)

        response = client.get("/api/v1/documents?page=1&size=10")
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["page"] == 1
        assert data["data"]["size"] == 10


class TestDocumentUpload:
    """Test POST /api/v1/documents/upload."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from app.web_app import app
        self.app = app

    def test_upload_success(self):
        """Uploading a valid PDF should succeed."""
        from app.services.storage_service import storage_service

        admin = _make_user(role="admin")
        client = _make_client(self.app, auth_user=admin)

        mock_meta = {
            "oss_key": "documents/siemens/abc123.pdf",
            "filename": "abc123.pdf",
            "file_hash": "abc123hash",
            "file_size": 100,
        }

        with patch.object(storage_service, "upload_file", return_value=mock_meta):
            pdf_content = b"%PDF-1.4 fake pdf content"
            response = client.post(
                "/api/v1/documents/upload",
                data={
                    "brand": "siemens",
                    "category": "plc-manual",
                    "description": "Test document",
                },
                files={"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 200
            assert data["data"]["original_name"] == "test.pdf"
            assert data["data"]["brand"] == "siemens"
            assert data["data"]["category"] == "plc-manual"

    def test_upload_not_pdf(self):
        """Uploading a non-PDF file should fail."""
        admin = _make_user(role="admin")
        client = _make_client(self.app, auth_user=admin)

        response = client.post(
            "/api/v1/documents/upload",
            data={"brand": "siemens", "category": "plc-manual"},
            files={"file": ("test.txt", io.BytesIO(b"not a pdf"), "text/plain")},
        )
        assert response.status_code == 415

    def test_upload_invalid_brand(self):
        """Uploading with an invalid brand should fail."""
        admin = _make_user(role="admin")
        client = _make_client(self.app, auth_user=admin)

        response = client.post(
            "/api/v1/documents/upload",
            data={"brand": "invalid_brand", "category": "plc-manual"},
            files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        )
        assert response.status_code == 400

    def test_upload_invalid_category(self):
        """Uploading with an invalid category should fail."""
        admin = _make_user(role="admin")
        client = _make_client(self.app, auth_user=admin)

        response = client.post(
            "/api/v1/documents/upload",
            data={"brand": "siemens", "category": "invalid_category"},
            files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        )
        assert response.status_code == 400


class TestBrandsAndCategories:
    """Test GET /api/v1/documents/brands/list and categories/list."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from app.web_app import app
        self.app = app

    def test_brands_list(self):
        """Brands list should return the predefined brands."""
        user = _make_user()
        client = _make_client(self.app, auth_user=user)

        response = client.get("/api/v1/documents/brands/list")
        assert response.status_code == 200
        brands = response.json()["data"]
        assert "siemens" in brands
        assert "mitsubishi" in brands

    def test_categories_list(self):
        """Categories list should return the predefined categories."""
        user = _make_user()
        client = _make_client(self.app, auth_user=user)

        response = client.get("/api/v1/documents/categories/list")
        assert response.status_code == 200
        categories = response.json()["data"]
        assert "plc-manual" in categories
        assert "best-practice" in categories


class TestDocumentDetail:
    """Test GET /api/v1/documents/{id}."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from app.web_app import app
        self.app = app

    def test_get_nonexistent_document(self):
        """Getting a nonexistent document should return 404."""
        user = _make_user()
        client = _make_client(self.app, auth_user=user)

        # The mock DB query chain must return None for the document
        client._mock_db.query.return_value.filter.return_value.first.return_value = None

        response = client.get("/api/v1/documents/99999")
        assert response.status_code == 404
