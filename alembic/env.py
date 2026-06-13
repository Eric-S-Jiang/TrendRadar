"""Alembic 环境配置 — 业务库（gpxx.db）迁移。

设计原则：
1. 不管 trend.db（由 TrendRadar 的 LocalStorageBackend 自维护）。
2. URL 从 app.config 的 DATABASE_URL 读取，但**剥掉 +aiosqlite 后缀**，
   因为 Alembic 用同步 driver。
3. SQLite 启用 batch 模式（render_as_batch=True），以便后续 ALTER TABLE 类操作。
"""
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# 把项目根目录加入 sys.path，方便 import app.*
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.core.db import Base  # noqa: E402
import app.models  # noqa: F401, E402  — 触发所有 ORM 注册

config = context.config

# 用 .env / 环境变量里的 DATABASE_URL 覆盖 alembic.ini 的占位
_settings = get_settings()
# Alembic 用同步 driver；去掉异步驱动后缀
_sync_url = _settings.DATABASE_URL.replace("+aiosqlite", "")
config.set_main_option("sqlalchemy.url", _sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate 的元数据来源
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite 友好
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：直连库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
