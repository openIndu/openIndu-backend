"""Application settings loaded from environment variables."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Layer-1 infrastructure and secret configuration."""

    DATABASE_URL: str = "postgresql://openindu:openindu123@localhost:5432/openindu_backend"

    # --- Storage backend ---
    # "local": filesystem storage under DATA_DIR (dev / low-traffic)
    # "s3":    S3-compatible storage via OSS_* env vars (MinIO dev, OSS prod)
    STORAGE_BACKEND: str = "local"
    DATA_DIR: str = "/data/files"

    # --- S3 / OSS credentials (only used when STORAGE_BACKEND=s3) ---
    OSS_ACCESS_KEY_ID: str = "minioadmin"
    OSS_ACCESS_KEY_SECRET: str = "minioadmin"
    OSS_ENDPOINT: str = "http://localhost:9000"
    OSS_BUCKET: str = "openindu"
    OSS_REGION: str = "us-east-1"

    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_COLLECTION: str = "plc_knowledge"

    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    SMS_ACCESS_KEY: str = ""
    SMS_TEMPLATE_ID: str = ""
    SMS_MOCK_ENABLED: bool = True
    SMS_MOCK_CODE: str = "888888"

    MCP_API_KEY: str = "change-me-mcp-key"
    WEB_PORT: int = 8004
    MCP_PORT: int = 8005

    DOWNLOAD_DAILY_LIMIT: int = 5
    PRESIGNED_URL_EXPIRE_MINUTES: int = 5
    DOCUMENT_MAX_SIZE_MB: int = 50
    SOFTWARE_MAX_SIZE_GB: int = 5
    RAG_SYNC_INTERVAL_MINUTES: int = 60

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=True)


settings = Settings()
