"""Redis 缓存装饰器。

用法：
    @cache(prefix="quote:stock", ttl=lambda: 15 if is_trading() else 300)
    async def get_stock(code: str) -> dict:
        return await tencent.fetch_stock(code)

    @cache(prefix="news:trend:latest", ttl=60)
    async def list_latest(platform: str, limit: int = 30) -> list[dict]:
        ...

设计要点：
- key = f"{prefix}:{md5(args+kwargs)}" — 稳定、与位置参数顺序无关
- TTL 可以是 int 或返回 int 的可调用（用于动态 TTL）
- 序列化用 json + default=str（处理 datetime/Decimal）
- 缓存失败不影响业务（Redis 挂了应该走原函数，不该让请求失败）
"""
import hashlib
import json
from functools import wraps
from typing import Awaitable, Callable, ParamSpec, TypeVar

from loguru import logger

from app.core.redis import get_redis

P = ParamSpec("P")
R = TypeVar("R")


def _make_key(args: tuple, kwargs: dict) -> str:
    """生成稳定的 key 后缀（与参数顺序无关）。"""
    payload = json.dumps(
        [args, sorted(kwargs.items())],
        default=str,
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def cache(
    prefix: str,
    ttl: int | Callable[[], int],
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Redis 缓存装饰器。

    Args:
        prefix: Redis key 前缀，建议 'group:subgroup' 格式
        ttl:    缓存秒数；可传 int 或返回 int 的无参可调用（用于动态 TTL）
    """

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            key = f"{prefix}:{_make_key(args, kwargs)}"

            # 读缓存
            try:
                redis = await get_redis()
                cached = await redis.get(key)
                if cached is not None:
                    return json.loads(cached)
            except Exception as e:
                # Redis 不可用：降级到原函数，不影响业务
                logger.warning("cache read failed for {}: {}", key, e)

            # 走原函数
            result = await fn(*args, **kwargs)

            # 写缓存
            try:
                real_ttl = ttl() if callable(ttl) else ttl
                redis = await get_redis()
                await redis.setex(
                    key,
                    real_ttl,
                    json.dumps(result, default=str, ensure_ascii=False),
                )
            except Exception as e:
                logger.warning("cache write failed for {}: {}", key, e)

            return result

        return wrapper

    return decorator


async def invalidate(prefix: str, *, pattern: str | None = None) -> int:
    """主动失效缓存（如用户修改了某只股票后清掉相关缓存）。

    Args:
        prefix: key 前缀
        pattern: 可选的 glob 模式追加到 prefix 之后

    Returns:
        被删除的 key 数量
    """
    redis = await get_redis()
    match = f"{prefix}:{pattern}" if pattern else f"{prefix}:*"
    deleted = 0
    async for key in redis.scan_iter(match=match, count=100):
        await redis.delete(key)
        deleted += 1
    return deleted
