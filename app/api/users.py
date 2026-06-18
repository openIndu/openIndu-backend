"""User administration API."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_admin
from app.models.admin_audit_log import AdminAuditLog
from app.models.login_session import LoginSession
from app.models.token_blacklist import TokenBlacklist
from app.models.user import User

router = APIRouter(prefix="/users")


class RoleChange(BaseModel):
    role: str


def ok(data=None, message="操作成功"):
    return {"code": 200, "message": message, "data": data or {}}


def audit(db: Session, admin_id: int, target_user_id: int, action: str, detail: dict | None = None):
    db.add(AdminAuditLog(admin_id=admin_id, target_user_id=target_user_id, action=action, detail=detail or {}))


def _enrich_user_dict(db: Session, user_dict: dict, user_id: int) -> dict:
    """Add online status and last login IP to user dict."""
    active_session = db.query(LoginSession).filter(
        LoginSession.user_id == user_id,
        LoginSession.is_active.is_(True),
    ).first()
    user_dict["online"] = active_session is not None

    last_session = db.query(LoginSession).filter(
        LoginSession.user_id == user_id,
    ).order_by(LoginSession.last_active_at.desc()).first()
    user_dict["login_ip"] = last_session.ip_address if last_session else None

    return user_dict


@router.get("")
async def list_users(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    q = db.query(User).order_by(User.created_at.desc())
    if keyword:
        q = q.filter(User.phone.ilike(f"%{keyword}%"))
    total = q.count()
    items = [_enrich_user_dict(db, u.to_dict(), u.id) for u in q.offset((page - 1) * size).limit(size).all()]
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.put("/{user_id}/role")
async def change_role(user_id: int, body: RoleChange, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if body.role not in ("user", "member", "admin"):
        raise HTTPException(400, "无效角色")
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "用户不存在")
    old_role = user.role
    user.role = body.role
    audit(db, admin.id, user.id, "role_change", {"old_role": old_role, "new_role": body.role})
    db.commit(); db.refresh(user)
    return ok(user.to_dict())


@router.post("/{user_id}/blacklist")
async def blacklist(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "用户不存在")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    user.is_active = False; user.is_blacklisted = True; user.blacklisted_at = now; user.blacklisted_by = admin.id; user.tokens_invalidated_at = now
    # Deactivate all login sessions for this user
    db.query(LoginSession).filter(LoginSession.user_id == user_id, LoginSession.is_active.is_(True)).update(
        {"is_active": False}, synchronize_session=False
    )
    audit(db, admin.id, user.id, "blacklist")
    db.commit(); db.refresh(user)
    return ok(user.to_dict(), "已拉黑")


@router.post("/{user_id}/unblacklist")
async def unblacklist(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "用户不存在")
    user.is_active = True; user.is_blacklisted = False; user.blacklisted_at = None; user.blacklisted_by = None; user.tokens_invalidated_at = None
    audit(db, admin.id, user.id, "unblacklist")
    db.commit(); db.refresh(user)
    return ok(user.to_dict(), "已解除拉黑")


@router.post("/{user_id}/force-logout")
async def force_logout(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "用户不存在")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    user.tokens_invalidated_at = now
    # Deactivate all login sessions for this user
    db.query(LoginSession).filter(LoginSession.user_id == user_id, LoginSession.is_active.is_(True)).update(
        {"is_active": False}, synchronize_session=False
    )
    audit(db, admin.id, user.id, "force_logout")
    db.commit(); db.refresh(user)
    return ok(user.to_dict(), "已强制登出")
