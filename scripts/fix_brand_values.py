"""
修正批量上传文档的 brand 值，使其与 tags 表 value 一致。
同步修改 OSS key + PG + Milvus。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.document import Document
from app.models.resource_tag import ResourceTag
from app.services.milvus_service import milvus_service
from app.core.config import settings

import boto3
from botocore.config import Config

oss = boto3.client(
    "s3",
    endpoint_url=settings.OSS_ENDPOINT,
    aws_access_key_id=settings.OSS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.OSS_ACCESS_KEY_SECRET,
    region_name=settings.OSS_REGION,
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
)
BUCKET = settings.OSS_BUCKET

# brand 映射: old_value → new_value
BRAND_FIX = {
    "三菱": "mitsubishi",
    "CKD": "ckd",
    "康耐视": "cognex",
}


def ensure_tag(db, value: str, label_zh: str):
    """确保 tags 表中有对应记录"""
    tag = db.query(ResourceTag).filter(
        ResourceTag.type == "doc_brand",
        ResourceTag.value == value,
    ).first()
    if tag:
        return tag
    tag = ResourceTag(
        type="doc_brand",
        value=value,
        label_zh=label_zh,
        is_active=True,
    )
    db.add(tag)
    db.flush()
    print(f"  [NEW TAG] type=doc_brand value={value} label_zh={label_zh}")
    return tag


def main():
    db = SessionLocal()

    # Ensure Akribis tag exists
    print("=== 确保 Akribis tag 存在 ===")
    ensure_tag(db, "akribis", "Akribis")
    BRAND_FIX["Akribis"] = "akribis"  # add to fix map

    # Find affected documents
    old_values = list(BRAND_FIX.keys())
    docs = db.query(Document).filter(Document.brand.in_(old_values)).all()
    print(f"\n=== 受影响文档: {len(docs)} 个 ===")

    milvus_ok = 0
    oss_ok = 0
    db_ok = 0
    errors = []

    for doc in docs:
        old_brand = doc.brand
        new_brand = BRAND_FIX[old_brand]
        old_oss_key = doc.oss_key
        # Replace brand segment in OSS key
        new_oss_key = old_oss_key.replace(f"/{old_brand}/", f"/{new_brand}/", 1)

        print(f"\nID={doc.id} | brand: {old_brand}→{new_brand} | {doc.original_name}")
        print(f"  OSS: {old_oss_key} → {new_oss_key}")

        # Step 1: Delete old Milvus vectors
        try:
            count = milvus_service.delete_by_document(doc.original_name)
            print(f"  [OK] Milvus: 删 {count} 条旧向量")
            milvus_ok += 1
        except Exception as e:
            errors.append(f"Milvus id={doc.id}: {e}")
            print(f"  [WARN] {e}")

        # Step 2: OSS copy + delete
        try:
            oss.copy_object(
                Bucket=BUCKET, Key=new_oss_key,
                CopySource={"Bucket": BUCKET, "Key": old_oss_key},
            )
            oss.delete_object(Bucket=BUCKET, Key=old_oss_key)
            print(f"  [OK] OSS 迁移完成")
            oss_ok += 1
        except Exception as e:
            errors.append(f"OSS id={doc.id}: {e}")
            print(f"  [FAIL] {e}")
            continue

        # Step 3: Update DB
        try:
            doc.brand = new_brand
            doc.oss_key = new_oss_key
            doc.sync_status = "pending"
            db.flush()
            print(f"  [OK] DB 已更新, sync_status='pending'")
            db_ok += 1
        except Exception as e:
            errors.append(f"DB id={doc.id}: {e}")
            print(f"  [FAIL] {e}")

    db.commit()
    print(f"\n=== SUMMARY ===")
    print(f"  Milvus 删旧向量: {milvus_ok}/{len(docs)}")
    print(f"  OSS 迁移:        {oss_ok}/{len(docs)}")
    print(f"  DB 更新:         {db_ok}/{len(docs)}")
    if errors:
        print(f"  错误: {len(errors)}")
        for e in errors[:10]:
            print(f"    {e}")

    db.close()


if __name__ == "__main__":
    main()
