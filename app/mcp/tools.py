"""MCP tool definitions aligned with document categories."""
from app.core.database import SessionLocal
from app.services.milvus_service import milvus_service


def _search(keyword: str, top_k: int, brand: str | None = None, category: str | None = None):
    where = {}
    if brand: where["brand"] = brand
    if category: where["category"] = category
    return milvus_service.search(keyword, top_k=top_k, where_filter=where or None)


def search_plc_manual(brand: str, keyword: str, top_k: int = 5):
    return _search(keyword, top_k, brand, "plc-manual")


def search_hardware_manual(brand: str, keyword: str, top_k: int = 5):
    return _search(keyword, top_k, brand, "hardware-manual")


def search_driver_manual(brand: str, keyword: str, top_k: int = 5):
    return _search(keyword, top_k, brand, "driver-manual")


def search_hmi_manual(brand: str, keyword: str, top_k: int = 5):
    return _search(keyword, top_k, brand, "hmi-manual")


def search_robot_manual(brand: str, keyword: str, top_k: int = 5):
    return _search(keyword, top_k, brand, "robot-manual")


def search_software_manual(brand: str, keyword: str, top_k: int = 5):
    return _search(keyword, top_k, brand, "software-manual")


def search_best_practice(topic: str, top_k: int = 5):
    return _search(topic, top_k, category="best-practice")


def search_electrical_standard(standard_name: str | None = None, keyword: str | None = None, top_k: int = 5):
    query = " ".join(x for x in [standard_name, keyword] if x)
    return _search(query, top_k, category="electrical-standard")


def get_brand_mapping(source_brand: str, target_brand: str, item: str):
    """Query cross-brand PLC address/instruction mappings from the database."""
    from sqlalchemy import or_

    from app.models.brand_mapping import BrandMapping

    db = SessionLocal()
    try:
        q = db.query(BrandMapping).filter(
            BrandMapping.source_brand == source_brand.lower(),
            BrandMapping.target_brand == target_brand.lower(),
        )
        if item:
            kw = f"%{item}%"
            q = q.filter(
                or_(
                    BrandMapping.item_type.ilike(kw),
                    BrandMapping.source_value.ilike(kw),
                    BrandMapping.target_value.ilike(kw),
                    BrandMapping.description.ilike(kw),
                )
            )
        rows = q.order_by(BrandMapping.item_type, BrandMapping.id).all()
        mappings = [
            {
                "item_type": r.item_type,
                "source_value": r.source_value,
                "target_value": r.target_value,
                "description": r.description,
            }
            for r in rows
        ]
        return {
            "source_brand": source_brand,
            "target_brand": target_brand,
            "item": item,
            "mappings": mappings,
        }
    finally:
        db.close()


def list_available_documents(brand: str | None = None, category: str | None = None):
    """List available documents from the database, filtered by brand/category."""
    from app.models.document import Document

    db = SessionLocal()
    try:
        q = db.query(Document)
        if brand:
            q = q.filter(Document.brand == brand)
        if category:
            q = q.filter(Document.category == category)
        docs = q.order_by(Document.upload_time.desc()).all()
        items = [
            {
                "id": d.id,
                "name": d.original_name,
                "brand": d.brand,
                "category": d.category,
                "sync_status": d.sync_status,
            }
            for d in docs
        ]
        return {"brand": brand, "category": category, "items": items}
    finally:
        db.close()


def list_available_software(brand: str | None = None, category: str | None = None):
    """List available software from the database, filtered by brand/category."""
    from app.models.software import Software

    db = SessionLocal()
    try:
        q = db.query(Software).filter(Software.is_active == True)  # noqa: E712
        if brand:
            q = q.filter(Software.brand == brand)
        if category:
            q = q.filter(Software.category == category)
        sw_list = q.order_by(Software.created_at.desc()).all()
        items = [
            {
                "id": s.id,
                "name": s.original_name,
                "brand": s.brand,
                "category": s.category,
                "latest_version": s.latest_version,
            }
            for s in sw_list
        ]
        return {"brand": brand, "category": category, "items": items}
    finally:
        db.close()
