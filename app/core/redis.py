"""Redis 异步客户端 — 全局单例 + 连接池。

设计：
- 第一次 get_redis() 时建立连接池
- 应用关闭时 close_redis() 优雅释放
- 测试可通过 set_redis(fakeredis_instance) 注入 mock
- USE_FAKEREDIS=true 时用 fakeredis 替代（本地开发无 Redis 环境）
"""
from typing import TYPE_CHECKING

import redis.asyncio as aioredis

from app.config import get_settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

settings = get_settings()

_redis: "Redis | None" = None

# fakeredis 共享 server，保证同进程内所有 get_redis() 拿到同一个实例
_fake_server = None


def set_redis(client: "Redis | None") -> None:
    """测试用：注入 fakeredis 实例。生产代码不要调。"""
    global _redis
    _redis = client


async def get_redis() -> "Redis":
    """惰性建池。连接失败在调用方报错（避免启动阶段挂死）。"""
    global _redis, _fake_server
    if _redis is None:
        if settings.USE_FAKEREDIS:
            import fakeredis.aioredis as _fakeredis
            if _fake_server is None:
                _fake_server = _fakeredis.FakeServer()
            _redis = _fakeredis.FakeRedis(server=_fake_server, decode_responses=True)
        else:
            _redis = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                max_connections=20,
                socket_keepalive=True,
            )
    return _redis


async def close_redis() -> None:
    """优雅关停（在 FastAPI shutdown 钩子调用）。"""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
