"""Business system configuration API."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_admin, require_auth
from app.core.utils import ok
from app.models.system_config import SystemConfig
from app.models.user import User

router = APIRouter(prefix="/config")


class ConfigItem(BaseModel):
    key: str
    value: str
    description: str | None = None


class ConfigUpdate(BaseModel):
    items: list[ConfigItem]


@router.get("")
async def get_config(db: Session = Depends(get_db), user: User = Depends(require_auth)):
    items = [x.to_dict() for x in db.query(SystemConfig).order_by(SystemConfig.config_key).all()]
    return ok({"items": items})


@router.put("")
async def update_config(body: ConfigUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    updated = []
    for incoming in body.items:
        item = db.query(SystemConfig).filter(SystemConfig.config_key == incoming.key).first()
        if not item:
            item = SystemConfig(config_key=incoming.key)
            db.add(item)
        item.config_value = incoming.value
        item.description = incoming.description
        updated.append(item)
    db.commit()
    return ok({"items": [x.to_dict() for x in updated]})
