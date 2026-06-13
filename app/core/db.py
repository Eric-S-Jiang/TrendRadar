"""SQLite 异步引擎 + 会话工厂。

两个独立 engine：
  - business_engine: gpxx.db（业务库，Alembic 管理）
  - trend_engine:    trend.db（TrendRadar 库，只读访问，schema 由 TrendRadar 维护）

所有连接启用 WAL 模式 + busy_timeout + foreign_keys，详见 PRAGMA 设置。
"""
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    """所有业务库 ORM 模型的基类。

    TrendRadar 库（trend.db）不走 ORM，由 service 层直接用 text(SQL) 查询。
    """


def _make_engine(url: str):
    """创建带 PRAGMA hook 的 async engine。

    SQLAlchemy 在每次新连接建立时触发 'connect' event，
    我们用它统一执行 SQLite PRAGMA 设置。
    """
    eng = create_async_engine(
        url,
        echo=False,
        connect_args={
            "check_same_thread": False,
            "timeout": 5.0,
        },
        # SQLite 用连接池意义有限，但 SQLAlchemy async engine 默认仍会用，
        # 这里限制并发连接，避免 SQLite "database is locked" 风险。
        pool_size=5,
        max_overflow=10,
    )

    # 注册 PRAGMA 设置（在底层 sync engine 上挂 hook）
    @event.listens_for(eng.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _connection_record):
        cur = dbapi_conn.cursor()
        # WAL：读不阻塞写；适合多读少写场景
        cur.execute("PRAGMA journal_mode=WAL")
        # 写竞争时等待 5s 再报 'database is locked'
        cur.execute("PRAGMA busy_timeout=5000")
        # WAL 模式下 NORMAL 安全且更快（断电不会损坏，但可能丢最后几次提交）
        cur.execute("PRAGMA synchronous=NORMAL")
        # 启用外键约束（SQLite 默认关闭）
        cur.execute("PRAGMA foreign_keys=ON")
        # 临时表用内存
        cur.execute("PRAGMA temp_store=MEMORY")
        # mmap 64MB：减少 read 系统调用
        cur.execute("PRAGMA mmap_size=67108864")
        cur.close()

    return eng


# 两个独立引擎
business_engine = _make_engine(settings.DATABASE_URL)
trend_engine = _make_engine(settings.TREND_DATABASE_URL)

# 会话工厂
BusinessSession = async_sessionmaker(
    business_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)
TrendSession = async_sessionmaker(
    trend_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_business_db() -> AsyncIterator[AsyncSession]:
    """业务库会话依赖。在路由中用 DbDep 替代直接调用。"""
    async with BusinessSession() as session:
        yield session


async def get_trend_db() -> AsyncIterator[AsyncSession]:
    """TrendRadar 库会话依赖（只读）。"""
    async with TrendSession() as session:
        yield session


async def dispose_engines() -> None:
    """优雅关停（在 FastAPI shutdown 中调用）。"""
    await business_engine.dispose()
    await trend_engine.dispose()
