"""
OBS/OSS → PostgreSQL 元数据导入脚本

遍历远程 OBS bucket 中 doc/ 前缀下的文件，自动从路径中识别品牌和类型，
将元数据写入数据库。已存在的记录（按 oss_key 去重）自动跳过，可安全重复执行。

OBS 路径结构: doc/{中文品牌}/{中文分类}/{文件名}.{ext}

Usage:
    # 预览（不写库）
    docker compose exec web-api python scripts/obs_import.py --dry-run

    # 执行导入
    docker compose exec web-api python scripts/obs_import.py
"""
import argparse
import os
import sys

# Allow running from repo root or scripts/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Document
from app.services.oss_service import oss_service

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DOC_EXTS = {".pdf"}

# 系统支持的 5 个品牌（中文/英文别名 → 系统 brand ID）
BRAND_MAP: dict[str, str] = {
    # 西门子
    "西门子": "siemens",
    "siemens": "siemens",
    "SIEMENS": "siemens",
    # 三菱
    "三菱": "mitsubishi",
    "mitsubishi": "mitsubishi",
    "MITSUBISHI": "mitsubishi",
    # 欧姆龙
    "欧姆龙": "omron",
    "omron": "omron",
    "OMRON": "omron",
    # 基恩士
    "基恩士": "keyence",
    "keyence": "keyence",
    "KEYENCE": "keyence",
    # 汇川
    "汇川": "inovance",
    "inovance": "inovance",
    "INOVANCE": "inovance",
}

# 文件夹名 → 系统 category ID（文档）
CATEGORY_MAP: dict[str, str] = {
    "PLC":        "plc-manual",
    "plc":        "plc-manual",
    "驱动器":     "driver-manual",
    "变频器":     "driver-manual",
    "伺服":       "driver-manual",
    "IO模块":     "hardware-manual",
    "通讯模块":   "hardware-manual",
    "网关":       "hardware-manual",
    "运动控制模块": "hardware-manual",
    "传感器":     "hardware-manual",
    "机器人":     "hardware-manual",
    "机器视觉":   "hardware-manual",
    "触摸屏":     "hmi-manual",
    "人机界面":   "hmi-manual",
    "HMI":        "hmi-manual",
    "驱动程序":   "software-manual",
    "软件":       "software-manual",
    "编程软件":   "software-manual",
    "应用":       "best-practice",
    "最佳实践":   "best-practice",
    "规范":       "electrical-standard",
    "标准":       "electrical-standard",
    # 通用硬件配件 → hardware-manual
    "按钮":       "hardware-manual",
    "接触器":     "hardware-manual",
    "断路器":     "hardware-manual",
    "热继电器":   "hardware-manual",
    "熔断器":     "hardware-manual",
    "线缆":       "hardware-manual",
}

# 跳过整个目录
def _skip_prefixes() -> set[str]:
    base = settings.OSS_LEGACY_DOC_PREFIX.rstrip("/")
    return {f"{base}/_index/"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def classify(oss_key: str) -> tuple[str | None, str]:
    """Return (brand_id, category_id) from the OBS path.

    Path format: doc/{brand_folder}/{category_folder}/{filename}
    Returns (None, category) when brand is unsupported — caller should skip.
    """
    parts = oss_key.split("/")
    # parts[0] = "doc", parts[1] = brand_folder, parts[2] = category_folder
    brand_folder    = parts[1] if len(parts) > 1 else ""
    category_folder = parts[2] if len(parts) > 2 else ""

    brand    = BRAND_MAP.get(brand_folder)
    category = CATEGORY_MAP.get(category_folder, "other")
    return brand, category


def should_skip(oss_key: str) -> bool:
    return any(oss_key.startswith(p) for p in _skip_prefixes())


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def import_documents(db, dry_run: bool) -> dict:
    stats = {
        "found": 0,
        "imported": 0,
        "skipped_exists": 0,
        "skipped_unsupported_brand": 0,
        "skipped_wrong_ext": 0,
    }
    unsupported_brands: set[str] = set()

    prefix = settings.OSS_LEGACY_DOC_PREFIX.rstrip("/") + "/"
    print(f"\n=== Scanning {prefix} prefix ===")
    objects = oss_service.list_objects(prefix)

    for obj in objects:
        oss_key  = obj["key"]
        filename = oss_key.split("/")[-1]

        # Skip index files and non-PDF
        if should_skip(oss_key):
            continue
        ext = os.path.splitext(filename)[1].lower()
        if ext not in DOC_EXTS:
            stats["skipped_wrong_ext"] += 1
            continue

        stats["found"] += 1

        # Dedup
        if db.query(Document).filter(Document.oss_key == oss_key).first():
            print(f"  [EXISTS ]  {oss_key}")
            stats["skipped_exists"] += 1
            continue

        brand, category = classify(oss_key)
        if brand is None:
            parts = oss_key.split("/")
            brand_folder = parts[1] if len(parts) > 1 else "?"
            unsupported_brands.add(brand_folder)
            stats["skipped_unsupported_brand"] += 1
            continue

        action = "DRY-RUN" if dry_run else "IMPORT "
        print(f"  [{action}]  {oss_key}")
        print(f"            brand={brand}  category={category}  size={obj['size']:,}")

        if not dry_run:
            doc = Document(
                filename=filename,
                original_name=filename,
                brand=brand,
                category=category,
                file_size=obj["size"],
                file_hash=obj["etag"],
                oss_key=oss_key,
                sync_status="pending",
                is_published=False,
            )
            db.add(doc)
            stats["imported"] += 1

    if not dry_run:
        db.commit()

    if unsupported_brands:
        print(f"\n  [INFO] Skipped unsupported brands: {', '.join(sorted(unsupported_brands))}")
        print("         Add them to BRAND_MAP in the script if you want to import them.")

    return stats


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Import OBS file metadata into PostgreSQL")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only, do not write to DB")
    args = parser.parse_args()

    if args.dry_run:
        print("[DRY-RUN MODE] No changes will be written to the database.\n")

    db = SessionLocal()
    try:
        stats = import_documents(db, args.dry_run)
    except Exception as exc:
        db.rollback()
        print(f"\n[ERROR] {exc}", file=sys.stderr)
        raise
    finally:
        db.close()

    print("\n" + "=" * 52)
    print("SUMMARY")
    print("=" * 52)
    print(f"  PDF files found          : {stats['found']}")
    print(f"  Imported                 : {stats['imported']}")
    print(f"  Skipped (already exists) : {stats['skipped_exists']}")
    print(f"  Skipped (brand not in system) : {stats['skipped_unsupported_brand']}")
    print(f"  Skipped (non-PDF)        : {stats['skipped_wrong_ext']}")

    if args.dry_run:
        print("\n[DRY-RUN] Re-run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
