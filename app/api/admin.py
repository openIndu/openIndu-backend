"""Admin management API (audit logs, etc.)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_admin
from app.models.admin_audit_log import AdminAuditLog
from app.models.user import User

router = APIRouter(prefix="/admin")


def ok(data=None, message="操作成功"):
    return {"code": 200, "message": message, "data": data or {}}


@router.get("/audit-logs")
async def audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(15, ge=1, le=100),
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    q = db.query(AdminAuditLog).order_by(AdminAuditLog.created_at.desc())
    total = q.count()
    logs = q.offset((page - 1) * page_size).limit(page_size).all()

    user_ids = {log.admin_id for log in logs} | {log.target_user_id for log in logs if log.target_user_id}
    phone_map = {u.id: u.phone for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    items = [{
        "id": log.id,
        "admin_username": phone_map.get(log.admin_id) or f"ID:{log.admin_id}",
        "target_user": phone_map.get(log.target_user_id) or (f"ID:{log.target_user_id}" if log.target_user_id else "-"),
        "action": log.action,
        "detail": str(log.detail) if log.detail else "-",
        "created_at": log.created_at.isoformat() if log.created_at else None,
    } for log in logs]

    return ok({"items": items, "total": total, "page": page, "size": page_size})
