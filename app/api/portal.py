"""Portal content API."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_admin
from app.models.portal_content import PortalContent
from app.models.user import User

router = APIRouter(prefix="/portal")


class ContentIn(BaseModel):
    content: dict
    sort_order: int = 0
    is_active: bool = True


def ok(data=None, message="操作成功"):
    return {"code": 200, "message": message, "data": data or {}}


def _list(db: Session, section: str):
    return [x.to_dict() for x in db.query(PortalContent).filter(PortalContent.section == section, PortalContent.is_active.is_(True)).order_by(PortalContent.sort_order).all()]


def _get_single(db: Session, section: str):
    item = db.query(PortalContent).filter(PortalContent.section == section, PortalContent.is_active.is_(True)).order_by(PortalContent.sort_order).first()
    return item.to_dict() if item else {"section": section, "content": {}}


def _upsert_single(db: Session, section: str, body: ContentIn):
    item = db.query(PortalContent).filter(PortalContent.section == section).order_by(PortalContent.id).first()
    if not item:
        item = PortalContent(section=section)
        db.add(item)
    item.content = body.content
    item.sort_order = body.sort_order
    item.is_active = body.is_active
    db.commit(); db.refresh(item)
    return item.to_dict()


@router.get("/hero")
async def hero(db: Session = Depends(get_db)):
    return ok(_get_single(db, "hero"))


@router.put("/hero")
async def update_hero(body: ContentIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return ok(_upsert_single(db, "hero", body))


@router.get("/solutions")
async def solutions(db: Session = Depends(get_db)):
    return ok({"items": _list(db, "solutions")})


@router.post("/solutions")
async def create_solution(body: ContentIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    item = PortalContent(section="solutions", content=body.content, sort_order=body.sort_order, is_active=body.is_active)
    db.add(item); db.commit(); db.refresh(item)
    return ok(item.to_dict(), "创建成功")


@router.put("/solutions/{item_id}")
async def update_solution(item_id: int, body: ContentIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    item = db.query(PortalContent).filter(PortalContent.id == item_id, PortalContent.section == "solutions").first()
    if not item: raise HTTPException(404, "内容不存在")
    item.content = body.content; item.sort_order = body.sort_order; item.is_active = body.is_active
    db.commit(); db.refresh(item)
    return ok(item.to_dict())


@router.delete("/solutions/{item_id}")
async def delete_solution(item_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    item = db.query(PortalContent).filter(PortalContent.id == item_id, PortalContent.section == "solutions").first()
    if not item: raise HTTPException(404, "内容不存在")
    db.delete(item); db.commit()
    return ok(message="删除成功")


@router.get("/carousel")
async def carousel(db: Session = Depends(get_db)):
    return ok({"items": _list(db, "carousel")})


@router.post("/carousel")
async def create_carousel(body: ContentIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    item = PortalContent(section="carousel", content=body.content, sort_order=body.sort_order, is_active=body.is_active)
    db.add(item); db.commit(); db.refresh(item)
    return ok(item.to_dict(), "创建成功")


@router.put("/carousel/{item_id}")
async def update_carousel(item_id: int, body: ContentIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    item = db.query(PortalContent).filter(PortalContent.id == item_id, PortalContent.section == "carousel").first()
    if not item: raise HTTPException(404, "内容不存在")
    item.content = body.content; item.sort_order = body.sort_order; item.is_active = body.is_active
    db.commit(); db.refresh(item)
    return ok(item.to_dict())


@router.delete("/carousel/{item_id}")
async def delete_carousel(item_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    item = db.query(PortalContent).filter(PortalContent.id == item_id, PortalContent.section == "carousel").first()
    if not item: raise HTTPException(404, "内容不存在")
    db.delete(item); db.commit()
    return ok(message="删除成功")


@router.get("/benefits")
async def benefits(db: Session = Depends(get_db)):
    return ok({"items": _list(db, "benefits")})


@router.put("/benefits")
async def update_benefits(body: ContentIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return ok(_upsert_single(db, "benefits", body))


@router.get("/footer")
async def footer(db: Session = Depends(get_db)):
    return ok(_get_single(db, "footer"))


@router.put("/footer")
async def update_footer(body: ContentIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return ok(_upsert_single(db, "footer", body))
