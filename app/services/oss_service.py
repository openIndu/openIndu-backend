"""S3-compatible OSS service used for documents and software packages."""
import hashlib
import uuid

import boto3
from botocore.config import Config

from app.core.config import settings


class OSSService:
    """Thin wrapper around boto3 S3 client."""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.OSS_ENDPOINT,
                aws_access_key_id=settings.OSS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.OSS_ACCESS_KEY_SECRET,
                region_name=settings.OSS_REGION,
                config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
            )
        return self._client

    @property
    def bucket(self) -> str:
        return settings.OSS_BUCKET

    def upload_file(self, file_content: bytes, original_name: str, prefix: str, content_type: str | None = None) -> dict:
        ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else "bin"
        filename = f"{uuid.uuid4().hex}.{ext}"
        oss_key = f"{prefix.strip('/')}/{filename}"
        file_hash = hashlib.sha256(file_content).hexdigest()
        params = {"Bucket": self.bucket, "Key": oss_key, "Body": file_content}
        if content_type:
            params["ContentType"] = content_type
        self.client.put_object(**params)
        return {"oss_key": oss_key, "filename": filename, "file_hash": file_hash, "file_size": len(file_content)}

    def delete_file(self, oss_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=oss_key)

    def generate_presigned_url(self, oss_key: str, expiration_minutes: int = 5) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": oss_key,
                "ResponseContentDisposition": "attachment",
            },
            ExpiresIn=expiration_minutes * 60,
        )

    def list_objects(self, prefix: str) -> list[dict]:
        objects: list[dict] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                objects.append({
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"],
                    "etag": obj["ETag"].strip('"'),
                })
        return objects


oss_service = OSSService()
