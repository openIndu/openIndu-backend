"""Import legacy OSS documents (doc/ prefix) into the PostgreSQL documents table.

Usage:
    python scripts/import_legacy_docs.py            # dry-run (preview only)
    python scripts/import_legacy_docs.py --write    # write to DB
"""

import re
import sys
import hashlib
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.document import Document
from app.models.resource_tag import ResourceTag
from app.services.oss_service import oss_service
from app.core.config import settings

# ── Brand mapping: OSS Chinese folder → DB slug ──────────────────────────────
BRAND_MAP: dict[str, str] = {
    "西门子": "siemens",
    "三菱": "mitsubishi",
    "三菱手冊": "mitsubishi",
    "欧姆龙": "omron",
    "基恩士": "keyence",
    "汇川": "inovance",
    "ABB": "abb",
    # auto-created for unknowns (slug derived below)
    "CKD": "ckd",
    "不二越": "nachi",
    "东方马达": "oriental-motor",
    "信捷": "xinje",
    "倍福": "beckhoff",
    "北阳": "hokuyo",
    "台达": "delta",
    "富士": "fuji",
    "康耐视": "cognex",
    "松下": "panasonic",
    "COGNEX": "cognex",
}

# ── Category mapping: OSS Chinese folder → DB slug ───────────────────────────
CATEGORY_MAP: dict[str, str] = {
    "PLC": "plc-manual",
    "驱动器": "driver-manual",
    "变频器": "driver-manual",
    "触摸屏": "hmi-manual",
    "IO模块": "hardware-manual",
    "运动控制模块": "hardware-manual",
    "通讯模块": "hardware-manual",
    "接触器": "other",
    "断路器": "other",
    "线缆": "other",
    "机器人": "other",
    "传感器": "other",
    "机器视觉": "other",
    "网关": "hardware-manual",
}

# ── Series detection: (brand_slug, category_slug, filename_pattern) → series slug
# Checked in order; first match wins
SERIES_RULES: list[tuple[str | None, str | None, str, str]] = [
    # brand,       category,       regex_pattern (case-insensitive),  series_slug
    ("siemens",    "plc-manual",   r"S7[-_]?1200",                    "s7-1200"),
    ("siemens",    "plc-manual",   r"S7[-_]?[34]\d\d",                "s7-300"),
    ("siemens",    "driver-manual",r"S120|SINAMICS.{0,5}S120",        "sinamics-s120"),
    ("siemens",    "driver-manual",r"G120|SINAMICS.{0,5}G120",        "sinamics-g120"),
    ("siemens",    "hmi-manual",   r"KTP",                            "simatic-ktp"),
    ("siemens",    "hmi-manual",   r"\bTP\b|SIMATIC.{0,5}TP",         "simatic-tp"),
    ("siemens",    "hardware-manual", r"ET.?200",                     "et200"),
    ("mitsubishi", "plc-manual",   r"FX5U?",                          "fx5u"),
    ("mitsubishi", "plc-manual",   r"FX[1-9]|FX系列|FX\d",            "fx"),
    ("mitsubishi", "plc-manual",   r"iQ[-_]?R",                       "iQ-R"),
    ("mitsubishi", "plc-manual",   r"Q系列|QnU|Q0[12]|Q06|QCPU",      "q"),
    ("mitsubishi", "driver-manual",r"MR[-_]?J5",                      "melservo-j5"),
    ("mitsubishi", "driver-manual",r"MR[-_]?J4",                      "melservo-j4"),
    ("mitsubishi", "driver-manual",r"MR[-_]?J3",                      "melservo-j4"),
    ("mitsubishi", "driver-manual",r"MR[-_]?JE",                      "melservo-j4"),
    ("mitsubishi", "hmi-manual",   r"GOT2000|GT27|GT25|GT23",         "got2000"),
    ("mitsubishi", "hmi-manual",   r"GOT1000|GT15|GT11|GT10",         "got1000"),
    ("mitsubishi", "hardware-manual", r"iQ[-_]?R",                    "iQ-R-hw"),
    ("mitsubishi", "hardware-manual", r"FX5U?",                       "fx5u"),
    ("omron",      "plc-manual",   r"CP1H",                           "cp1h"),
    ("omron",      "plc-manual",   r"CP1E",                           "cp1e"),
    ("omron",      "driver-manual",r"G5|SmartStep",                   "g5-series"),
    ("omron",      "hmi-manual",   r"NS[-_]?\d",                      "ns-series"),
]


def detect_series(brand: str, category: str, filename: str) -> str | None:
    for rule_brand, rule_cat, pattern, series_slug in SERIES_RULES:
        if rule_brand and rule_brand != brand:
            continue
        if rule_cat and rule_cat != category:
            continue
        if re.search(pattern, filename, re.IGNORECASE):
            return series_slug
    return None


def ensure_brand_tag(db, brand_slug: str, label_zh: str) -> None:
    exists = db.query(ResourceTag).filter(
        ResourceTag.type == "doc_brand",
        ResourceTag.value == brand_slug,
    ).first()
    if not exists:
        db.add(ResourceTag(
            type="doc_brand",
            value=brand_slug,
            label_zh=label_zh,
            is_active=True,
            sort_order=99,
        ))
        db.flush()
        print(f"  [NEW TAG] doc_brand: {brand_slug!r} ({label_zh})")


def main(write: bool = False) -> None:
    mode_label = "WRITE" if write else "DRY-RUN"
    print(f"=== import_legacy_docs [{mode_label}] ===")
    print(f"Bucket: {settings.OSS_BUCKET}  Prefix: doc/")
    print()

    db = SessionLocal()

    # Load existing oss_key → Document map
    existing: dict[str, Document] = {
        d.oss_key: d for d in db.query(Document).filter(Document.oss_key.like("doc/%")).all()
    }
    print(f"Existing DB records with doc/ prefix: {len(existing)}")

    # List all objects
    all_objs = oss_service.list_objects("doc")
    pdfs = [o for o in all_objs if o["key"].lower().endswith(".pdf") and "/_index/" not in o["key"]]
    print(f"PDF files in OSS doc/: {len(pdfs)}")
    print()

    stats = {"new": 0, "updated": 0, "skipped": 0, "unmapped_brand": set(), "unmapped_category": set()}

    for obj in pdfs:
        key = obj["key"]
        parts = key.split("/")
        # Expected: doc/{brand_folder}/{category_folder}/{filename}
        if len(parts) < 4:
            print(f"  SKIP (unexpected path depth): {key}")
            stats["skipped"] += 1
            continue

        brand_folder = parts[1]
        category_folder = parts[2]
        filename = parts[-1]

        brand_slug = BRAND_MAP.get(brand_folder)
        category_slug = CATEGORY_MAP.get(category_folder)

        if not brand_slug:
            stats["unmapped_brand"].add(brand_folder)
            print(f"  SKIP (unmapped brand {brand_folder!r}): {key}")
            stats["skipped"] += 1
            continue

        if not category_slug:
            stats["unmapped_category"].add(category_folder)
            print(f"  SKIP (unmapped category {category_folder!r}): {key}")
            stats["skipped"] += 1
            continue

        series_slug = detect_series(brand_slug, category_slug, filename)

        if write:
            ensure_brand_tag(db, brand_slug, brand_folder)

        existing_doc = existing.get(key)
        if existing_doc:
            changed = (
                existing_doc.brand != brand_slug
                or existing_doc.category != category_slug
                or existing_doc.series != series_slug
            )
            action = "UPDATE" if changed else "NOCHANGE"
            print(f"  [{action}] {key}")
            print(f"    brand={brand_slug}  category={category_slug}  series={series_slug}")
            if write and changed:
                existing_doc.brand = brand_slug
                existing_doc.category = category_slug
                existing_doc.series = series_slug
                stats["updated"] += 1
            elif changed:
                stats["updated"] += 1
        else:
            print(f"  [NEW] {key}")
            print(f"    brand={brand_slug}  category={category_slug}  series={series_slug}")
            if write:
                new_doc = Document(
                    filename=filename,
                    original_name=filename,
                    brand=brand_slug,
                    category=category_slug,
                    series=series_slug,
                    file_size=obj["size"],
                    file_hash=None,
                    oss_key=key,
                    description="",
                    is_published=False,
                    sync_status="pending",
                )
                db.add(new_doc)
            stats["new"] += 1

    if write:
        db.commit()
        print()
        print("=== Committed ===")
    else:
        print()
        print("=== DRY-RUN complete (no changes written) ===")

    db.close()

    print()
    print(f"New records    : {stats['new']}")
    print(f"Updated records: {stats['updated']}")
    print(f"Skipped        : {stats['skipped']}")
    if stats["unmapped_brand"]:
        print(f"Unmapped brands   : {sorted(stats['unmapped_brand'])}")
    if stats["unmapped_category"]:
        print(f"Unmapped categories: {sorted(stats['unmapped_category'])}")


if __name__ == "__main__":
    write_mode = "--write" in sys.argv
    main(write=write_mode)
