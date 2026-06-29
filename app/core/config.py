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

    # IP geo resolution (ip2region offline xdb). Relative paths resolve against
    # the backend root; empty falls back to data/ip2region_v4.xdb.
    IP2REGION_XDB_PATH: str = "data/ip2region_v4.xdb"

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
    SMS_ACCESS_KEY_SECRET: str = ""
    SMS_SIGN_NAME: str = ""
    SMS_TEMPLATE_ID: str = ""
    SMS_MOCK_ENABLED: bool = True
    SMS_MOCK_CODE: str = "888888"
    SMS_MOCK_EXTRA_CODE: str = ""   # 附加测试验证码，留空则不生效

    MCP_API_KEY: str = "change-me-mcp-key"
    WEB_PORT: int = 8004
    MCP_PORT: int = 8005

    # OSS path prefixes — override in .env to match your bucket layout
    OSS_DOC_PREFIX: str = "documents"
    OSS_SOFTWARE_PREFIX: str = "soft"
    OSS_LEGACY_DOC_PREFIX: str = "doc"

    DOWNLOAD_DAILY_LIMIT: int = 5
    # Preview has its own daily quota, separate from downloads: in-page reading
    # shouldn't burn the download budget, but it's still capped so the preview
    # endpoint can't be used to bypass the download limit (inline files can be saved).
    PREVIEW_DAILY_LIMIT: int = 20
    PRESIGNED_URL_EXPIRE_MINUTES: int = 5
    DOCUMENT_MAX_SIZE_MB: int = 50
    SOFTWARE_MAX_SIZE_GB: int = 5
    RAG_SYNC_INTERVAL_MINUTES: int = 60
    # Whether the in-process APScheduler registers the OSS → Milvus sync job
    # at startup. Production sets this to ``false`` so resource-constrained
    # nodes don't run the expensive BGE-M3 embedding cycle every hour;
    # syncs are triggered manually instead (POST /sync/trigger, the admin UI
    # button, or scripts/sync_local.py from the aggregate repo). The two
    # lightweight cleanup jobs (sessions, expired tokens) always run — they
    # cost almost nothing and dashboard "current online" depends on them.
    RAG_SYNC_ENABLED: bool = True

    # --- 智能咨询 / RAG 对话（§4.3.12）---
    # 生成模型走 OpenAI 兼容协议（默认 DeepSeek，可切通义等），换厂商只改这些 env。
    # 检索沿用 BGE-M3 + Milvus（CPU），不依赖 GPU。
    LLM_PROVIDER: str = "deepseek"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL: str = "deepseek-chat"
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 1024
    LLM_TIMEOUT_SECONDS: int = 60
    RAG_TOP_K: int = 5
    # 每用户每日咨询上限（admin 豁免），基于 chat_logs 当日计数
    CHAT_DAILY_LIMIT: int = 30

    # --- Direct-to-OSS multipart upload (large software packages) ---
    # Part size for multipart uploads. Must be ≥ 5 MiB (S3/OSS minimum).
    # 64 MiB strikes a good balance: a 5 GiB package is ~80 parts (few enough
    # to keep HTTP overhead low), each part finishes in ~5–30 s on typical
    # home upstreams (≥2 MB/s), keeping the progress bar responsive.
    UPLOAD_PART_SIZE_MB: int = 64
    # How long presigned PUT URLs stay valid. Large uploads take time, so
    # default to 2 hours.
    UPLOAD_PRESIGN_EXPIRE_MINUTES: int = 120

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=True)


settings = Settings()
