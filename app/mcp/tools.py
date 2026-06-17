"""MCP tool definitions aligned with document categories."""
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


def search_software_manual(brand: str, keyword: str, top_k: int = 5):
    return _search(keyword, top_k, brand, "software-manual")


def search_best_practice(topic: str, top_k: int = 5):
    return _search(topic, top_k, category="best-practice")


def search_electrical_standard(standard_name: str | None = None, keyword: str | None = None, top_k: int = 5):
    query = " ".join(x for x in [standard_name, keyword] if x)
    return _search(query, top_k, category="electrical-standard")


def get_brand_mapping(source_brand: str, target_brand: str, item: str):
    return {"source_brand": source_brand, "target_brand": target_brand, "item": item, "mapping": None}


def list_available_documents(brand: str | None = None, category: str | None = None):
    return {"brand": brand, "category": category, "items": []}


def list_available_software(brand: str | None = None, category: str | None = None):
    return {"brand": brand, "category": category, "items": []}
