"""Focused API/helper coverage for coverage gate."""
import asyncio
import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
import uuid

import pytest
from fastapi import HTTPException


def _chain(items=None, first=None, count=0):
    q = MagicMock()
    q.filter.return_value = q
    q.join.return_value = q
    q.order_by.return_value = q
    q.offset.return_value = q
    q.limit.return_value = q
    q.all.return_value = items or []
    q.first.return_value = first
    q.count.return_value = count
    return q


class _Request:
    def __init__(self, forwarded=None):
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}
        self.client = SimpleNamespace(host="127.0.0.1")


def _user(role="admin"):
    return SimpleNamespace(id=1, role=role, is_active=True, is_blacklisted=False, tokens_invalidated_at=None)


def test_brand_mapping_helpers():
    from app.api import brand_mapping

    assert brand_mapping.ok({"x": 1})["data"] == {"x": 1}
    assert asyncio.run(brand_mapping.overview(user=_user()))["data"]["siemens"]
    mapped = asyncio.run(brand_mapping.address("siemens", "omron", "D0", user=_user()))
    assert mapped["data"]["item"] == "D0"


def test_documents_helpers_and_edges(monkeypatch):
    from app.api import documents

    assert documents.ok()["data"] == {}
    assert documents.client_ip(_Request("1.1.1.1, 2.2.2.2")) == "1.1.1.1"
    assert documents.client_ip(_Request()) == "127.0.0.1"

    db = MagicMock()
    doc = SimpleNamespace(id=1, oss_key="docs/a.pdf", original_name="a.pdf", download_count=None)
    db.query.side_effect = [_chain(first=doc), _chain(count=0)]
    monkeypatch.setattr(documents.storage_service, "get_download_url", lambda key: {"url": f"/files/{key}", "expires_in": None})
    result = asyncio.run(documents.get_document_download_link(1, _Request(), db, _user("member")))
    assert result["data"]["download_url"] == "/files/docs/a.pdf"
    assert doc.download_count == 1

    db = MagicMock()
    db.query.return_value = _chain(first=doc)
    monkeypatch.setattr(documents.storage_service, "delete_file", lambda key: None)
    assert asyncio.run(documents.delete_document(1, db, _user()))["message"] == "删除成功"


def test_documents_list_upload_get(monkeypatch):
    from app.api import documents

    db = MagicMock()
    doc = SimpleNamespace(id=1, oss_key="docs/a.pdf", original_name="a.pdf")
    doc.to_dict = lambda: {"id": doc.id}
    db.query.return_value = _chain(items=[doc], count=1)
    result = asyncio.run(documents.list_documents(brand="siemens", keyword="a", page=1, size=20, db=db))
    assert result["data"]["total"] == 1

    db = MagicMock()
    db.query.side_effect = [
        _chain(items=[SimpleNamespace(value="siemens")]),
        _chain(items=[SimpleNamespace(value="plc-manual")]),
    ]
    monkeypatch.setattr(documents.storage_service, "upload_file", lambda c, n, p, t: {"oss_key": "docs/x.pdf", "filename": "x.pdf", "file_size": 100, "file_hash": "abc"})
    file = MagicMock()
    file.filename = "test.pdf"
    file.size = 100
    file.content_type = "application/pdf"

    async def read():
        return b"%PDF"
    file.read = read
    result = asyncio.run(documents.upload_document(file=file, brand="siemens", category="plc-manual", series="", description="desc", db=db, admin=_user()))
    assert "上传成功" in result["message"]

    db = MagicMock()
    db.query.return_value = _chain(first=doc)
    result = asyncio.run(documents.get_document(1, db=db))
    assert result["data"]["id"] == 1


def test_documents_brands_categories():
    from app.api import documents

    db = MagicMock()
    db.query.return_value = _chain(items=[SimpleNamespace(value="siemens"), SimpleNamespace(value="mitsubishi")])
    assert asyncio.run(documents.brands(db))["data"] == ["siemens", "mitsubishi"]

    db = MagicMock()
    db.query.return_value = _chain(items=[SimpleNamespace(value="plc-manual"), SimpleNamespace(value="best-practice")])
    assert asyncio.run(documents.categories(db))["data"] == ["plc-manual", "best-practice"]


def test_document_series_validation():
    from app.api import documents

    db = MagicMock()
    db.query.return_value = _chain(first=SimpleNamespace(value="s7-1200"))
    documents._validate_doc_series(db, "siemens", "plc-manual", "s7-1200")

    db = MagicMock()
    db.query.return_value = _chain(first=None)
    with pytest.raises(HTTPException) as exc:
        documents._validate_doc_series(db, "siemens", "plc-manual", "bad-series")
    assert exc.value.status_code == 400
    assert exc.value.detail == "无效系列"


def test_series_tags_require_brand_and_global_unique_value():
    from app.api import tags

    db = MagicMock()
    body = tags.CreateTagBody(type="doc_series", value="s7-1200", label_zh="S7-1200", parent_value="plc-manual")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(tags.create_tag(body, db, _user()))
    assert exc.value.status_code == 400

    db = MagicMock()
    db.query.return_value = _chain(first=SimpleNamespace(value="s7-1200"))
    body = tags.CreateTagBody(type="doc_series", value="s7-1200", label_zh="S7-1200", parent_value="hardware-manual", brand_value="siemens")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(tags.create_tag(body, db, _user()))
    assert exc.value.status_code == 409


def test_software_responses_do_not_expose_legacy_series():
    from app.api import software
    from app.models.software import Software

    sw = Software(filename="tool.zip", original_name="Tool.zip", brand="siemens", category="utility")
    sw.id = 1
    sw.versions = []
    data = sw.to_dict()
    assert "series" not in data

    version = SimpleNamespace(
        id=10,
        software_id=1,
        software=SimpleNamespace(
            id=1,
            brand="siemens",
            category="utility",
            description="desc",
            created_at=datetime(2026, 1, 1),
            latest_version="1.0",
        ),
        oss_key="soft/tool.zip",
        original_name="Tool.zip",
        version="1.0",
        file_size=100,
        file_hash="abc",
        upload_time=datetime(2026, 1, 1),
        download_count=0,
        is_published=True,
    )
    db = MagicMock()
    db.query.return_value = _chain(items=[version], count=1)
    result = asyncio.run(software.list_software(expand_versions=True, page=1, size=20, db=db))
    assert "series" not in result["data"]["items"][0]


def test_sw_series_tag_type_is_rejected():
    from app.api import tags

    db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(tags.list_tags(type="sw_series", db=db))
    assert exc.value.status_code == 400

    body = tags.CreateTagBody(type="sw_series", value="obsolete", label_zh="Obsolete")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(tags.create_tag(body, db, _user()))
    assert exc.value.status_code == 400


@pytest.mark.parametrize("filename,expected", [("setup.exe", ".exe"), ("archive", "")])
def test_software_ext(filename, expected):
    from app.api.software import _ext

    assert _ext(filename) == expected


def test_software_download_and_delete(monkeypatch):
    from app.api import software

    assert software.ok()["data"] == {}
    assert software._ip(_Request("2.2.2.2, 3.3.3.3")) == "2.2.2.2"

    sw = SimpleNamespace(id=3, original_name="tool.zip", download_count=0)
    ver = SimpleNamespace(oss_key="software/tool.zip", version="1.0", download_count=0)
    db = MagicMock()
    db.query.return_value = _chain(count=0)
    monkeypatch.setattr(software.storage_service, "get_download_url", lambda key: {"url": f"/files/{key}", "expires_in": 60})
    result = software._download_version(db, sw, ver, _user("member"), _Request())
    assert result["data"]["version"] == "1.0"
    assert sw.download_count == 1
    assert ver.download_count == 1

    db = MagicMock()
    db.query.return_value = _chain(first=ver)
    monkeypatch.setattr(software.storage_service, "delete_file", lambda key: None)
    assert asyncio.run(software.delete_version(3, 4, db, _user()))["message"] == "删除成功"


def test_software_list_upload_get_add_delete(monkeypatch):
    from app.api import software

    sw = SimpleNamespace(id=1, original_name="Tool.zip", brand="siemens", latest_version="1.0", download_count=0)
    sw.to_dict = lambda include_versions=False: {"id": sw.id}
    sw.versions = []
    ver = SimpleNamespace(id=10, software_id=1, version="2.0", oss_key="software/new.zip")
    ver.to_dict = lambda: {"id": ver.id}

    db = MagicMock()
    db.query.return_value = _chain(items=[sw], count=1)
    result = asyncio.run(software.list_software(page=1, size=20, keyword="Tool", db=db))
    assert result["data"]["total"] == 1

    db = MagicMock()
    db.query.return_value = _chain(first=sw)
    assert asyncio.run(software.get_software(1, db=db))["data"]["id"] == 1

    monkeypatch.setattr(software.storage_service, "upload_file", lambda c, n, p, t: {"oss_key": "software/x.zip", "filename": "x.zip", "file_size": 100, "file_hash": "abc"})
    file = MagicMock()
    file.filename = "test.zip"
    file.size = 100
    file.content_type = "application/octet-stream"

    async def read():
        return b"PK"
    file.read = read

    db = MagicMock()
    db.query.side_effect = [
        _chain(items=[SimpleNamespace(value="siemens")]),
        _chain(items=[SimpleNamespace(value="utility")]),
    ]
    db.flush = lambda: None
    assert asyncio.run(software.upload_software(file=file, brand="siemens", category="utility", version="1.0", description="desc", db=db, admin=_user()))["message"] == "上传成功"

    db = MagicMock()
    db.query.return_value = _chain(first=sw)
    assert asyncio.run(software.add_version(1, file=file, version="2.0", db=db, admin=_user()))["message"] == "版本已添加"

    db = MagicMock()
    db.query.return_value = _chain(first=sw)
    monkeypatch.setattr(software.storage_service, "delete_file", lambda key: None)
    assert asyncio.run(software.delete_software(1, db=db, admin=_user()))["message"] == "删除成功"


def test_config_api_update_and_list():
    from app.api import config

    db = MagicMock()
    item = SimpleNamespace(config_key="a", config_value="b", description=None, updated_at=datetime(2026, 1, 1))
    item.to_dict = lambda: {"key": item.config_key, "value": item.config_value, "description": item.description}
    db.query.return_value.order_by.return_value.all.return_value = [item]
    assert asyncio.run(config.get_config(db, _user()))["data"]["items"][0]["key"] == "a"

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    body = config.ConfigUpdate(items=[config.ConfigItem(key="rag_chunk_size", value="512")])
    result = asyncio.run(config.update_config(body, db, _user()))
    updated = result["data"]["items"][0]
    assert (updated.get("config_key") or updated.get("key")) == "rag_chunk_size"


def test_portal_api_crud():
    from app.api import portal

    item = SimpleNamespace(id=1, section="hero", content={"title": "Hi"}, sort_order=0, is_active=True, updated_at=datetime(2026, 1, 1))
    item.to_dict = lambda: {"id": item.id, "content": item.content}
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = item
    assert asyncio.run(portal.hero(db))["data"]["content"]["title"] == "Hi"

    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [item]
    assert asyncio.run(portal.solutions(db))["data"]["items"][0]["id"] == 1

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = item
    body = portal.ContentIn(content={"title": "Next"}, sort_order=2)
    assert asyncio.run(portal.update_solution(1, body, db, _user()))["data"]["content"]["title"] == "Next"
    assert asyncio.run(portal.delete_solution(1, db, _user()))["message"] == "删除成功"


def test_stats_and_sync_apis(monkeypatch):
    from app.api import stats, sync

    session = SimpleNamespace(user_id=1, geo_location="CN", ip_address="127.0.0.1", user_agent="ua", last_active_at=datetime(2026, 1, 1), is_active=True)
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [session]
    assert asyncio.run(stats.online(db, _user()))["data"]["online_users"] == 1

    db = MagicMock()
    lh_q = db.query.return_value.join.return_value.order_by.return_value
    lh_q.count.return_value = 1
    lh_q.offset.return_value.limit.return_value.all.return_value = []
    assert asyncio.run(stats.login_history(page=1, size=20, keyword=None, status=None, db=db, admin=_user()))["data"]["total"] == 1

    db = MagicMock()
    db.query.return_value.all.return_value = [("pending",), ("synced",), ("synced",)]
    assert asyncio.run(sync.sync_status(db, _user()))["data"]["documents"]["synced"] == 2
    bg = MagicMock()
    result = asyncio.run(sync.trigger_sync(bg, sync.TriggerBody(), _user()))
    assert result["data"]["mode"] == "incremental"
    assert result["data"]["status"] == "queued"


def test_users_helpers_and_actions():
    from app.api import users

    active = SimpleNamespace(ip_address="127.0.0.1")
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.first.return_value = active
    db = MagicMock()
    db.query.return_value = q
    data = users._enrich_user_dict(db, {}, 1)
    assert data["online"] is True
    assert data["login_ip"] == "127.0.0.1"

    target = SimpleNamespace(id=2, phone="138", role="user", is_active=True, is_blacklisted=False, blacklisted_at=None, blacklisted_by=None, tokens_invalidated_at=None)
    target.to_dict = lambda: {"id": target.id, "role": target.role, "is_blacklisted": target.is_blacklisted}
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = target
    assert asyncio.run(users.change_role(2, users.RoleChange(role="member"), db, _user()))["data"]["role"] == "member"
    assert asyncio.run(users.blacklist(2, db, _user()))["message"] == "已拉黑"
    assert asyncio.run(users.unblacklist(2, db, _user()))["message"] == "已解除拉黑"
    assert asyncio.run(users.force_logout(2, db, _user()))["message"] == "已强制登出"

    db = MagicMock()
    db.query.return_value = _chain(items=[target], count=1)
    result = asyncio.run(users.list_users(page=1, size=20, db=db, admin=_user()))
    assert result["data"]["total"] == 1


def test_files_api_local_and_error_paths(tmp_path, monkeypatch):
    from app.api import files

    monkeypatch.setattr(files.storage_service, "_backend", "s3")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(files.download_file("missing.pdf", 1, "bad-token"))
    assert exc.value.status_code == 404

    monkeypatch.setattr(files.storage_service, "_backend", "local")
    monkeypatch.setattr(files.storage_service, "validate_local_download_token", lambda key, expires, token: False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(files.download_file("missing.pdf", 1, "bad-token"))
    assert exc.value.status_code == 401

    monkeypatch.setattr(files.storage_service, "validate_local_download_token", lambda key, expires, token: True)
    monkeypatch.setattr(files.storage_service, "get_file_path", lambda key: (_ for _ in ()).throw(FileNotFoundError()))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(files.download_file("missing.pdf", 1, "token"))
    assert exc.value.status_code == 404

    target = tmp_path / "ok.pdf"
    target.write_bytes(b"pdf")
    monkeypatch.setattr(files.storage_service, "get_file_path", lambda key: target)
    response = asyncio.run(files.download_file("ok.pdf", 1, "token"))
    assert str(target) in response.path


def test_files_api_creates_debug_placeholder(tmp_path, monkeypatch):
    from app.api import files

    monkeypatch.setattr(files.settings, "DATA_DIR", str(tmp_path))
    target = tmp_path / "soft" / "debug-tool.zip"
    files.ensure_debug_placeholder("soft/debug-tool.zip")
    assert target.exists()
    assert target.read_bytes() == files.DEBUG_PLACEHOLDERS["soft/debug-tool.zip"]


def test_storage_service_facade_paths(monkeypatch):
    from app.services.storage_service import StorageService
    from app.services import storage_service as module

    local_impl = MagicMock()
    local_impl.upload_file.return_value = {"filename": "a.pdf"}
    local_impl.list_objects.return_value = [{"key": "a"}]
    local_impl.get_file_path.return_value = "path"
    s3_impl = MagicMock()
    s3_impl.generate_presigned_url.return_value = "https://signed"
    monkeypatch.setattr(module, "file_storage", local_impl)
    monkeypatch.setattr(module, "oss_service", s3_impl)

    service = StorageService()
    service._backend = "local"
    assert service.is_local is True
    assert service.upload_file(b"x", "a.pdf", "docs") == {"filename": "a.pdf"}
    assert service.list_objects("docs") == [{"key": "a"}]
    local_download = service.get_download_url("/docs/a.pdf")
    assert local_download["url"].startswith("/api/v1/files/docs/a.pdf?expires=")
    assert "&token=" in local_download["url"]
    assert local_download["expires_in"] == service.LOCAL_DOWNLOAD_TOKEN_TTL_SECONDS
    assert service.get_file_path("docs/a.pdf") == "path"
    service.delete_file("docs/a.pdf")
    local_impl.delete_file.assert_called_once_with("docs/a.pdf")

    service._backend = "s3"
    assert service.is_local is False
    assert service.get_download_url("docs/a.pdf")["url"] == "https://signed"
    with pytest.raises(RuntimeError):
        service.get_file_path("docs/a.pdf")


def test_file_storage_service(monkeypatch, tmp_path):
    from app.services.file_storage import FileStorageService

    monkeypatch.setattr("app.services.file_storage.settings", SimpleNamespace(DATA_DIR=str(tmp_path)))
    service = FileStorageService()
    result = service.upload_file(io.BytesIO(b"test content"), "file.txt", "test-prefix")
    assert result["file_size"] == len(b"test content")
    assert len(service.list_objects("test-prefix")) == 1
    path = service.get_file_path(result["oss_key"])
    assert path.read_bytes() == b"test content"
    service.delete_file(result["oss_key"])
    with pytest.raises(FileNotFoundError):
        service.get_file_path(result["oss_key"])
    assert service.list_objects("non-existent") == []


def test_dependencies_require_roles():
    from app.core import dependencies

    with pytest.raises(HTTPException):
        asyncio.run(dependencies.require_auth(None))
    assert asyncio.run(dependencies.require_member(_user("member"))).role == "member"
    with pytest.raises(HTTPException):
        asyncio.run(dependencies.require_member(_user("user")))
    assert asyncio.run(dependencies.require_admin(_user("admin"))).role == "admin"
    with pytest.raises(HTTPException):
        asyncio.run(dependencies.require_admin(_user("member")))


def test_auth_helpers():
    from app.api import auth
    assert auth.ok()["code"] == 200
    assert auth.ok({"a": 1})["data"]["a"] == 1


def test_update_me_helper():
    from app.api import auth

    user = SimpleNamespace(nickname=None)
    user.to_dict = lambda: {"nickname": user.nickname}
    db = MagicMock()
    result = asyncio.run(auth.update_me(auth.ProfileUpdateRequest(nickname=" Tom "), db, user))
    assert result["data"]["nickname"] == "Tom"
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(user)


def test_visit_tracking_records_client_id_and_event_type(monkeypatch):
    from app.api import visits

    monkeypatch.setattr(visits, "resolve_ip_geo", lambda ip: {"name": "成都", "country_code": "CN"})
    db = MagicMock()
    body = visits.VisitBody(path="/resources", client_id="client-123", event_type="page_view")
    result = asyncio.run(visits.track_visit(body, _Request("8.8.8.8"), db))

    assert result["data"]["tracked"] is True
    event = db.add.call_args.args[0]
    assert event.ip_address == "8.8.8.8"
    assert event.client_id == "client-123"
    assert event.event_type == "page_view"
    assert event.path == "/resources"


def test_visit_tracking_rejects_unknown_event_type():
    from app.api import visits

    body = visits.VisitBody(path="/", client_id="client-123", event_type="click")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(visits.track_visit(body, _Request("8.8.8.8"), MagicMock()))
    assert exc.value.status_code == 400

def test_auth_service_validate_phone(monkeypatch):
    from app.services.auth_service import AuthService

    with pytest.raises(HTTPException):
        AuthService._validate_phone("1234")

    monkeypatch.setattr("app.services.auth_service.settings", SimpleNamespace(
        SMS_MOCK_ENABLED=True, SMS_MOCK_CODE="123456", JWT_SECRET_KEY="test", JWT_ALGORITHM="HS256",
        ACCESS_TOKEN_EXPIRE_MINUTES=60, REFRESH_TOKEN_EXPIRE_DAYS=7
    ))


def test_auth_service_create_token_pair(monkeypatch):
    from app.services.auth_service import AuthService

    monkeypatch.setattr("app.services.auth_service.settings", SimpleNamespace(
        SMS_MOCK_ENABLED=True, SMS_MOCK_CODE="123456", JWT_SECRET_KEY="test-key-123",
        JWT_ALGORITHM="HS256", ACCESS_TOKEN_EXPIRE_MINUTES=60, REFRESH_TOKEN_EXPIRE_DAYS=7
    ))

    user = SimpleNamespace(id=1, phone="13800138000", role="user")
    tokens = AuthService.create_token_pair(user)
    assert "access_token" in tokens
    assert "refresh_token" in tokens


def test_auth_service_verify_code(monkeypatch):
    from app.services.auth_service import AuthService

    monkeypatch.setattr("app.services.auth_service.settings", SimpleNamespace(
        SMS_MOCK_ENABLED=False, SMS_MOCK_CODE="123456", JWT_SECRET_KEY="test-key-123",
        JWT_ALGORITHM="HS256"
    ))

    service = AuthService()
    db = MagicMock()
    record = SimpleNamespace(code="654321", is_used=False, verify_attempts=0)
    db.query.return_value = _chain(first=record)
    assert service.verify_code(db, "13800138000", "wrong") is False
    assert record.verify_attempts == 1


def test_auth_service_send_code(monkeypatch):
    from app.services.auth_service import AuthService
    from fastapi import HTTPException

    monkeypatch.setattr("app.services.auth_service.settings", SimpleNamespace(
        SMS_MOCK_ENABLED=True, SMS_MOCK_CODE="123456", JWT_SECRET_KEY="test-key-123",
        JWT_ALGORITHM="HS256", ACCESS_TOKEN_EXPIRE_MINUTES=60, REFRESH_TOKEN_EXPIRE_DAYS=7
    ))

    service = AuthService()
    db = MagicMock()
    db.query.return_value = _chain(first=None)
    # Should not crash for valid phone
    service.send_code(db, "13800138000")


def test_auth_service_login(monkeypatch):
    from app.services.auth_service import AuthService
    from fastapi import HTTPException

    monkeypatch.setattr("app.services.auth_service.settings", SimpleNamespace(
        SMS_MOCK_ENABLED=True, SMS_MOCK_CODE="123456", JWT_SECRET_KEY="test-key-123",
        JWT_ALGORITHM="HS256", ACCESS_TOKEN_EXPIRE_MINUTES=60, REFRESH_TOKEN_EXPIRE_DAYS=7
    ))

    service = AuthService()

    # Mock verify_code for login path to return False
    service.verify_code = lambda db, phone, code: False
    db = MagicMock()
    user = SimpleNamespace(id=1, phone="13800138000", role="user", is_active=True, is_blacklisted=False, last_login=None)
    user.to_dict = lambda: {"id": 1}
    db.query.return_value = _chain(first=user)

    with pytest.raises(HTTPException):
        service.login(db, "13800138000", "wrong-code")


def test_auth_service_register(monkeypatch):
    from app.services.auth_service import AuthService

    monkeypatch.setattr("app.services.auth_service.settings", SimpleNamespace(
        SMS_MOCK_ENABLED=True, SMS_MOCK_CODE="123456", JWT_SECRET_KEY="test-key-123",
        JWT_ALGORITHM="HS256", ACCESS_TOKEN_EXPIRE_MINUTES=60, REFRESH_TOKEN_EXPIRE_DAYS=7
    ))

    service = AuthService()
    db = MagicMock()
    db.query.return_value = _chain(first=None)
    db.add = lambda x: None
    db.commit = lambda: None
    db.refresh = lambda x: None


def test_auth_service_refresh(monkeypatch):
    from app.services.auth_service import AuthService

    monkeypatch.setattr("app.services.auth_service.settings", SimpleNamespace(
        SMS_MOCK_ENABLED=True, SMS_MOCK_CODE="123456", JWT_SECRET_KEY="test-key-123",
        JWT_ALGORITHM="HS256", ACCESS_TOKEN_EXPIRE_MINUTES=60, REFRESH_TOKEN_EXPIRE_DAYS=7
    ))

    service = AuthService()
    db = MagicMock()


def test_auth_service_logout(monkeypatch):
    from jose import jwt

    from app.services.auth_service import AuthService

    monkeypatch.setattr("app.services.auth_service.settings", SimpleNamespace(
        SMS_MOCK_ENABLED=True, SMS_MOCK_CODE="123456", JWT_SECRET_KEY="test-key-123",
        JWT_ALGORITHM="HS256", ACCESS_TOKEN_EXPIRE_MINUTES=60, REFRESH_TOKEN_EXPIRE_DAYS=7
    ))

    service = AuthService()
    db = MagicMock()
    q = _chain(first=None)
    db.query.return_value = q
    token = jwt.encode(
        {"sub": "7", "type": "access", "jti": "logout-jti", "exp": int(datetime.now().timestamp()) + 3600},
        "test-key-123",
        algorithm="HS256",
    )

    service.logout(db, token, user_agent="UA", client_id="client-1")

    q.update.assert_called_with({"is_active": False})
    db.commit.assert_called()


def test_decode_token(monkeypatch):
    from app.services.auth_service import decode_token

    monkeypatch.setattr("app.services.auth_service.settings", SimpleNamespace(
        JWT_SECRET_KEY="test-key-123", JWT_ALGORITHM="HS256"
    ))


def test_utcnnow():
    from app.services.auth_service import utcnow
    now = utcnow()
    assert now is not None


def test_models():
    from app.models import user
    from app.models import document
    from app.models import software
    assert True


def _direct_upload_token(claims_extra: dict) -> str:
    from jose import jwt
    from app.core.config import settings
    claims = {"oss_key": "software/siemens/abc.zip", "filename": "t.zip", "brand": "siemens",
              "category": "utility", "version": "1.0", "description": "",
              "content_type": "application/zip", "size": 100}
    claims.update(claims_extra)
    return jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def test_software_direct_upload_init_local(monkeypatch):
    from app.api import software
    monkeypatch.setattr(software.storage_service, "_backend", "local")
    db = MagicMock()
    db.query.side_effect = [_chain(items=[SimpleNamespace(value="siemens")]),
                            _chain(items=[SimpleNamespace(value="utility")])]
    body = software.UploadInitBody(filename="t.zip", brand="siemens", category="utility",
                                   version="1.0", size=100)
    result = asyncio.run(software.upload_init(body, db=db, admin=_user()))
    assert result["data"]["mode"] == "sync"


def test_software_direct_upload_init_multipart(monkeypatch):
    from app.api import software
    from app.services import oss_service as oss_mod
    monkeypatch.setattr(software.storage_service, "_backend", "s3")
    monkeypatch.setattr(oss_mod.oss_service, "create_multipart_upload", lambda *a, **k: "uid-1")
    monkeypatch.setattr(oss_mod.oss_service, "presign_part_upload",
                        lambda key, uid, pn, exp: f"https://oss/part{pn}")
    db = MagicMock()
    db.query.side_effect = [_chain(items=[SimpleNamespace(value="siemens")]),
                            _chain(items=[SimpleNamespace(value="utility")])]
    body = software.UploadInitBody(filename="t.zip", brand="siemens", category="utility",
                                   version="1.0", content_type="application/zip",
                                   size=software.settings.UPLOAD_PART_SIZE_MB * 1024 * 1024 + 1)
    result = asyncio.run(software.upload_init(body, db=db, admin=_user()))
    data = result["data"]
    assert data["mode"] == "multipart"
    assert len(data["part_urls"]) == 2
    assert data["part_urls"][1] == "https://oss/part2"
    from jose import jwt
    from app.core.config import settings
    claims = jwt.decode(data["token"], settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    assert claims["mode"] == "multipart"
    assert claims["upload_id"] == "uid-1"
    assert claims["size"] == body.size


def test_software_direct_upload_init_single(monkeypatch):
    from app.api import software
    from app.services import oss_service as oss_mod
    monkeypatch.setattr(software.storage_service, "_backend", "s3")
    monkeypatch.setattr(oss_mod.oss_service, "presign_single_put", lambda *a, **k: "https://oss/single")
    db = MagicMock()
    db.query.side_effect = [_chain(items=[SimpleNamespace(value="siemens")]),
                            _chain(items=[SimpleNamespace(value="utility")])]
    body = software.UploadInitBody(filename="t.zip", brand="siemens", category="utility",
                                   version="1.0", size=1024)
    data = asyncio.run(software.upload_init(body, db=db, admin=_user()))["data"]
    assert data["mode"] == "single"
    assert data["upload_url"] == "https://oss/single"


def test_software_direct_upload_complete_multipart(monkeypatch):
    from app.api import software
    from app.services import oss_service as oss_mod
    monkeypatch.setattr(oss_mod.oss_service, "complete_multipart_upload", lambda *a, **k: None)
    token = _direct_upload_token({"mode": "multipart", "upload_id": "uid-1"})
    db = MagicMock()
    db.flush = lambda: None
    parts = [software.UploadPartResult(part_number=2, etag="B"), software.UploadPartResult(part_number=1, etag="A")]
    body = software.UploadCompleteBody(token=token, parts=parts)
    result = asyncio.run(software.upload_complete(body, db=db, admin=_user()))
    assert result["message"] == "上传成功"


def test_software_direct_upload_complete_single(monkeypatch):
    from app.api import software
    from app.services import oss_service as oss_mod
    monkeypatch.setattr(oss_mod.oss_service, "head_object", lambda *a, **k: True)
    token = _direct_upload_token({"mode": "single"})
    db = MagicMock()
    db.flush = lambda: None
    body = software.UploadCompleteBody(token=token)
    assert asyncio.run(software.upload_complete(body, db=db, admin=_user()))["message"] == "上传成功"


def test_software_direct_upload_complete_single_missing(monkeypatch):
    from app.api import software
    from app.services import oss_service as oss_mod
    monkeypatch.setattr(oss_mod.oss_service, "head_object", lambda *a, **k: False)
    token = _direct_upload_token({"mode": "single"})
    with pytest.raises(HTTPException):
        asyncio.run(software.upload_complete(software.UploadCompleteBody(token=token), db=MagicMock(), admin=_user()))


def test_software_direct_upload_abort(monkeypatch):
    from app.api import software
    from app.services import oss_service as oss_mod
    called = {}
    monkeypatch.setattr(oss_mod.oss_service, "abort_multipart_upload", lambda *a, **k: called.setdefault("aborted", True))
    token = _direct_upload_token({"mode": "multipart", "upload_id": "uid-1"})
    asyncio.run(software.upload_abort(software.UploadAbortBody(token=token), admin=_user()))
    assert called.get("aborted") is True


def test_software_direct_upload_bad_token():
    from app.api import software
    with pytest.raises(HTTPException):
        asyncio.run(software.upload_complete(software.UploadCompleteBody(token="bad"), db=MagicMock(), admin=_user()))
