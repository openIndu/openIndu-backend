"""Resource tag CRUD API — manages dynamic brands and categories."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_admin
from app.models.document import Document
from app.models.resource_tag import ResourceTag
from app.models.software import Software
from app.models.user import User

router = APIRouter(prefix="/tags")

VALID_TYPES = {"brand", "doc_category", "sw_category"}


def ok(data=None, message="操作成功"):
    return {"code": 200, "message": message, "data": data or {}}


class CreateTagBody(BaseModel):
    type: str
    value: str
    label_zh: str
    sort_order: int = 0


class UpdateTagBody(BaseModel):
    label_zh: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None


@router.get("")
async def list_tags(type: str | None = None, db: Session = Depends(get_db)):
    q = db.query(ResourceTag)
    if type:
        if type not in VALID_TYPES:
            raise HTTPException(400, f"无效 type，可选：{', '.join(VALID_TYPES)}")
        q = q.filter(ResourceTag.type == type)
    tags = q.order_by(ResourceTag.type, ResourceTag.sort_order, ResourceTag.id).all()
    return ok([t.to_dict() for t in tags])


@router.post("")
async def create_tag(body: CreateTagBody, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if body.type not in VALID_TYPES:
        raise HTTPException(400, f"无效 type，可选：{', '.join(VALID_TYPES)}")
    if not body.value.strip() or not body.label_zh.strip():
        raise HTTPException(400, "value 和 label_zh 不能为空")
    existing = db.query(ResourceTag).filter(ResourceTag.type == body.type, ResourceTag.value == body.value.strip()).first()
    if existing:
        raise HTTPException(409, f"标签已存在：type={body.type}, value={body.value}")
    tag = ResourceTag(type=body.type, value=body.value.strip(), label_zh=body.label_zh.strip(), sort_order=body.sort_order)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return ok(tag.to_dict(), "创建成功")


@router.patch("/{tag_id}")
async def update_tag(tag_id: int, body: UpdateTagBody, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    tag = db.query(ResourceTag).filter(ResourceTag.id == tag_id).first()
    if not tag:
        raise HTTPException(404, "标签不存在")
    if body.label_zh is not None:
        if not body.label_zh.strip():
            raise HTTPException(400, "label_zh 不能为空")
        tag.label_zh = body.label_zh.strip()
    if body.is_active is not None:
        tag.is_active = body.is_active
    if body.sort_order is not None:
        tag.sort_order = body.sort_order
    db.commit()
    db.refresh(tag)
    return ok(tag.to_dict(), "更新成功")


@router.delete("/{tag_id}")
async def delete_tag(tag_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    tag = db.query(ResourceTag).filter(ResourceTag.id == tag_id).first()
    if not tag:
        raise HTTPException(404, "标签不存在")
    if tag.type == "brand":
        in_use = (
            db.query(Document).filter(Document.brand == tag.value).first()
            or db.query(Software).filter(Software.brand == tag.value).first()
        )
    elif tag.type == "doc_category":
        in_use = db.query(Document).filter(Document.category == tag.value).first()
    else:
        in_use = db.query(Software).filter(Software.category == tag.value).first()
    if in_use:
        raise HTTPException(400, "该标签仍有文档或软件在使用，无法删除")
    db.delete(tag)
    db.commit()
    return ok(message="删除成功")
