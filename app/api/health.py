"""健康检查接口。

GET /api/health         - 进程存活（docker healthcheck 走这个）
GET /api/health/db      - SQLite 业务库 + trend.db 可读
GET /api/health/redis   - Redis 连通性
GET /api/health/sources - 外部数据源可达性（5min Redis 缓存）
"""
from fastapi import APIRouter
from loguru import logger
from sqlalchemy import text

from app.core.envelope import ok
from app.deps import DbDep, RedisDep, TrendDbDep
from app.services.cache import cache
from app.services.sources import probe_sources

router = APIRouter()


@router.get("")
async def health() -> dict:
    """无依赖存活检查。docker healthcheck 走这个。"""
    return ok({"alive": True})


@router.get("/db")
async def health_db(db: DbDep, trend_db: TrendDbDep) -> dict:
    """业务库 + TrendRadar 库可达性。

    trend.db 在首次抓取前可能不存在；那种情况返回 trend=false 不算 fail。
    """
    business_ok = False
    trend_ok = False
    try:
        await db.execute(text("SELECT 1"))
        business_ok = True
    except Exception as e:
        logger.warning("business db unhealthy: {}", e)
    try:
        await trend_db.execute(text("SELECT 1"))
        # 进一步：必须确认 TrendRadar 关键表存在
        # （SQLite 在连接时会创建空文件，所以仅 SELECT 1 不能区分 "已初始化" / "空文件"）
        result = await trend_db.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='platforms'")
        )
        trend_ok = result.first() is not None
    except Exception as e:
        logger.debug("trend db not ready: {}", e)
    return ok({"business": business_ok, "trend": trend_ok})


@router.get("/redis")
async def health_redis(redis: RedisDep) -> dict:
    """Redis 连通性。"""
    try:
        pong = await redis.ping()
        return ok({"redis": bool(pong)})
    except Exception as e:
        logger.warning("redis unhealthy: {}", e)
        return ok({"redis": False})


# 数据源探测做 5min Redis 缓存（避免每次健康检查都打外网）
@cache(prefix="health:sources", ttl=300)
async def _cached_probe() -> dict:
    return await probe_sources()


@router.get("/sources")
async def health_sources() -> dict:
    """外部数据源可达性（缓存 5min）。

    返回各源的 status_code / latency_ms / ok。
    """
    return ok(await _cached_probe())
