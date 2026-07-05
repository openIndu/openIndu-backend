"""
一次性脚本：修正今日上传文档的模糊文件名和错误分类。
同步修改 OSS + PostgreSQL + Milvus。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.document import Document
from app.services.milvus_service import milvus_service
from app.core.config import settings

import boto3
from botocore.config import Config

oss_client = boto3.client(
    "s3",
    endpoint_url=settings.OSS_ENDPOINT,
    aws_access_key_id=settings.OSS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.OSS_ACCESS_KEY_SECRET,
    region_name=settings.OSS_REGION,
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
)
BUCKET = settings.OSS_BUCKET

# ============================================================================
# 改名清单 (doc_id, old_name, new_name, brand, category, old_oss_key)
# ============================================================================
RENAMES = [
    (350, "A5.pdf", "三菱-A5系列参考手册.pdf", "三菱", "plc-manual", "doc/三菱/A5.pdf"),
    (383, "SETUP.pdf", "CKD-选型系统安装指南.pdf", "CKD", "software-manual", "doc/CKD/SETUP.pdf"),
    (384, "Setup_Procedure_J.pdf", "CKD-选型系统安装步骤.pdf", "CKD", "software-manual", "doc/CKD/Setup_Procedure_J.pdf"),
    (356, "fx3u-64ccl.pdf", "三菱-FX3U-64CCL模块手册.pdf", "三菱", "plc-manual", "doc/三菱/fx3u-64ccl.pdf"),
    (360, "jy997d38401c.pdf", "三菱-FX-ENET-L用户手册.pdf", "三菱", "plc-manual", "doc/三菱/jy997d38401c.pdf"),
    (361, "manual_20138141353058807.pdf", "三菱-Q系列参考手册.pdf", "三菱", "plc-manual", "doc/三菱/manual_20138141353058807.pdf"),
    (385, "sh081084enga.pdf", "三菱-MX-Component操作手册.pdf", "三菱", "software-manual", "doc/三菱/sh081084enga.pdf"),
    (386, "sh081085enga.pdf", "三菱-MX-Component编程手册.pdf", "三菱", "software-manual", "doc/三菱/sh081085enga.pdf"),
    (351, "A5L_MANUAL_110308.pdf", "Akribis-A5L线马手册.pdf", "Akribis", "driver-manual", "doc/Akribis/A5L_MANUAL_110308.pdf"),
    (448, "SR-DSV10679_110308.pdf", "Akribis-驱动器手册.pdf", "Akribis", "driver-manual", "doc/Akribis/SR-DSV10679_110308.pdf"),
    (449, "一維讀碼器.pdf", "康耐视-一維讀碼器.pdf", "康耐视", "hardware-manual", "doc/康耐视/一維讀碼器.pdf"),
    (450, "二維讀碼器.pdf", "康耐视-二維讀碼器.pdf", "康耐视", "hardware-manual", "doc/康耐视/二維讀碼器.pdf"),
    (451, "光源.pdf", "康耐视-视觉光源.pdf", "康耐视", "hardware-manual", "doc/康耐视/光源.pdf"),
    (452, "鏡頭.pdf", "康耐视-视觉镜头.pdf", "康耐视", "hardware-manual", "doc/康耐视/鏡頭.pdf"),
    (453, "顯示器.pdf", "康耐视-视觉显示器.pdf", "康耐视", "hardware-manual", "doc/康耐视/顯示器.pdf"),
]

# ============================================================================
# 分类修正 (doc_id, new_category)
# ============================================================================
CATEGORY_FIXES = [
    (381, "plc-manual"),   # QD77MS同步控制: driver-manual → plc-manual
    (380, "plc-manual"),   # PLC通讯组件使用说明V23: software-manual → plc-manual
]


def oss_key_for_new_name(new_name: str, brand: str) -> str:
    """Build OSS key for the new name."""
    return f"doc/{brand}/{new_name}"


def main():
    db = SessionLocal()
    milvus_deleted = 0
    oss_copied = 0
    oss_failed = 0
    db_updated = 0
    category_fixed = 0
    errors = []

    # ---- Phase 1: Rename documents ----
    print("=" * 60)
    print("Phase 1: 重命名文档 (15个)")
    print("=" * 60)

    for doc_id, old_name, new_name, brand, category, old_oss_key in RENAMES:
        new_oss_key = oss_key_for_new_name(new_name, brand)
        print(f"\n[ID={doc_id}] {old_name} → {new_name}")
        print(f"  OSS: {old_oss_key} → {new_oss_key}")

        # Step 1: Delete old Milvus vectors
        try:
            count = milvus_service.delete_by_document(old_name)
            print(f"  [OK] Milvus: 删除 {count} 条旧向量 (document_name='{old_name}')")
            milvus_deleted += 1
        except Exception as e:
            err = f"Milvus delete failed for {old_name}: {e}"
            print(f"  [WARN] {err}")
            errors.append(err)

        # Step 2: OSS copy + delete old
        try:
            oss_client.copy_object(
                Bucket=BUCKET,
                Key=new_oss_key,
                CopySource={"Bucket": BUCKET, "Key": old_oss_key},
            )
            oss_client.delete_object(Bucket=BUCKET, Key=old_oss_key)
            print(f"  [OK] OSS: 复制+删除旧key完成")
            oss_copied += 1
        except Exception as e:
            err = f"OSS copy/delete failed for {old_oss_key}: {e}"
            print(f"  [FAIL] {err}")
            errors.append(err)
            oss_failed += 1
            continue  # Don't update DB if OSS failed

        # Step 3: Update DB
        try:
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if not doc:
                print(f"  [FAIL] DB: 找不到 id={doc_id}")
                errors.append(f"DB: doc id={doc_id} not found")
                continue
            doc.original_name = new_name
            doc.filename = new_name
            doc.oss_key = new_oss_key
            doc.sync_status = "pending"
            doc.brand = brand
            doc.category = category
            db.flush()
            print(f"  [OK] DB: original_name, filename, oss_key 已更新, sync_status='pending'")
            db_updated += 1
        except Exception as e:
            err = f"DB update failed for id={doc_id}: {e}"
            print(f"  [FAIL] {err}")
            errors.append(err)

    # ---- Phase 2: Fix categories ----
    print(f"\n{'=' * 60}")
    print("Phase 2: 修正分类 (2个)")
    print("=" * 60)

    for doc_id, new_cat in CATEGORY_FIXES:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            print(f"  [FAIL] 找不到 id={doc_id}")
            continue
        old_cat = doc.category
        doc.category = new_cat
        db.flush()
        print(f"  [OK] ID={doc_id} {doc.original_name}: {old_cat} → {new_cat}")
        category_fixed += 1

    # ---- Commit ----
    try:
        db.commit()
        print(f"\n[OK] 所有 DB 更改已提交")
    except Exception as e:
        db.rollback()
        print(f"\n[FAIL] DB commit 失败: {e}")
        errors.append(f"Commit failed: {e}")

    # ---- Summary ----
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)
    print(f"  Milvus 旧向量删除: {milvus_deleted}/15")
    print(f"  OSS 拷贝+删除:    {oss_copied}/15 (失败: {oss_failed})")
    print(f"  DB 重命名更新:    {db_updated}/15")
    print(f"  DB 分类修正:      {category_fixed}/2")
    if errors:
        print(f"  错误: {len(errors)}")
        for e in errors:
            print(f"    - {e}")

    db.close()


if __name__ == "__main__":
    main()
