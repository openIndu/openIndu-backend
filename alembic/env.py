"""Alembic environment."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.models import Base
from app.models.admin_audit_log import AdminAuditLog  # noqa: F401
from app.models.document import Document  # noqa: F401
from app.models.download_log import DownloadLog  # noqa: F401
from app.models.login_session import LoginSession  # noqa: F401
from app.models.portal_content import PortalContent  # noqa: F401
from app.models.sms_code import SmsCode  # noqa: F401
from app.models.software import Software, SoftwareVersion  # noqa: F401
from app.models.sync_log import SyncLog  # noqa: F401
from app.models.system_config import SystemConfig  # noqa: F401
from app.models.token_blacklist import TokenBlacklist  # noqa: F401
from app.models.user import User  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings.DATABASE_URL, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
