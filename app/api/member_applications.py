"""Member application API — user applies, admin approves."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_admin, require_auth
from app.core.utils import mask_phone, ok
from app.models.admin_audit_log import AdminAuditLog
from app.models.member_application import MemberApplication
from app.models.user import User

router = APIRouter()


class ApplyBody(BaseModel):
    note: str | None = None


def _audit(db: Session, admin_id: int, target_user_id: int, action: str, detail: dict | None = None):
    db.add(AdminAuditLog(admin_id=admin_id, target_user_id=target_user_id, action=action, detail=detail or {}))


# ── 用户侧 ────────────────────────────────────────────────────────────────────

@router.post("/member-applications")
async def apply(body: ApplyBody, db: Session = Depends(get_db), user: User = Depends(require_auth)):
    if user.role in ("member", "admin"):
        raise HTTPException(400, "当前账号已是会员或管理员，无需申请")
    existing = db.query(MemberApplication).filter(
        MemberApplication.user_id == user.id,
        MemberApplication.status == "pending",
    ).first()
    if existing:
        raise HTTPException(400, "已有待审核的申请，请耐心等待")
    app_obj = MemberApplication(user_id=user.id, note=body.note)
    db.add(app_obj)
    db.commit()
    db.refresh(app_obj)
    return ok(app_obj.to_dict(), "申请已提交，等待审核")


@router.get("/member-applications/mine")
async def my_application(db: Session = Depends(get_db), user: User = Depends(require_auth)):
    """返回当前用户最新一条申请状态（pending 优先，否则最近一条）。"""
    pending = db.query(MemberApplication).filter(
        MemberApplication.user_id == user.id,
        MemberApplication.status == "pending",
    ).first()
    if pending:
        return ok(pending.to_dict())
    latest = db.query(MemberApplication).filter(
        MemberApplication.user_id == user.id,
    ).order_by(MemberApplication.created_at.desc()).first()
    return ok(latest.to_dict() if latest else None)


# ── 管理员侧 ──────────────────────────────────────────────────────────────────

@router.get("/admin/member-applications")
async def list_applications(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    q = db.query(MemberApplication).order_by(MemberApplication.created_at.desc())
    if status:
        q = q.filter(MemberApplication.status == status)
    total = q.count()
    items = q.offset((page - 1) * size).limit(size).all()

    user_ids = {a.user_id for a in items}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}

    result = []
    for a in items:
        d = a.to_dict()
        u = users.get(a.user_id)
        d["phone"] = mask_phone(u.phone) if u else None
        d["nickname"] = u.nickname if u else None
        d["current_role"] = u.role if u else None
        result.append(d)

    return ok({"items": result, "total": total, "page": page, "size": size})


@router.put("/admin/member-applications/{app_id}/approve")
async def approve(app_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    app_obj = db.query(MemberApplication).filter(MemberApplication.id == app_id).first()
    if not app_obj:
        raise HTTPException(404, "申请记录不存在")
    if app_obj.status != "pending":
        raise HTTPException(400, "该申请已处理")
    target = db.query(User).filter(User.id == app_obj.user_id).first()
    if not target:
        raise HTTPException(404, "用户不存在")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    app_obj.status = "approved"
    app_obj.reviewed_by = admin.id
    app_obj.updated_at = now
    target.role = "member"
    _audit(db, admin.id, target.id, "member_approve", {"application_id": app_id})
    db.commit()
    db.refresh(app_obj)
    return ok(app_obj.to_dict(), "已通过，用户已升级为会员")
