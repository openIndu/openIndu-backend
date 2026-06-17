"""Brand mapping API placeholders."""
from fastapi import APIRouter, Depends

from app.core.dependencies import require_auth
from app.models.user import User

router = APIRouter(prefix="/brand-mapping")

BRAND_OVERVIEW = {
    "siemens": "西门子 S7-1200 / S7-1500",
    "mitsubishi": "三菱 FX5U / R 系列",
    "omron": "欧姆龙 NJ / NX 系列",
    "keyence": "基恩士 KV-8000",
    "inovance": "汇川 AM600 / Easy 系列",
}


def ok(data=None, message="操作成功"):
    return {"code": 200, "message": message, "data": data or {}}


@router.get("/overview")
async def overview(user: User = Depends(require_auth)):
    return ok(BRAND_OVERVIEW)


@router.get("/address")
async def address(source_brand: str | None = None, target_brand: str | None = None, item: str | None = None, user: User = Depends(require_auth)):
    return ok({"source_brand": source_brand, "target_brand": target_brand, "item": item, "mapping": None})
