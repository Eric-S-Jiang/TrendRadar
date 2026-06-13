"""Redis 滑动窗口限流。

用法：
    await check_rate_limit(f"auth:login:{ip}", limit=5, window_sec=60)

超限抛 HTTPException(429, ...) + Retry-After header。
全局异常处理器自动包装成 envelope。

实现：
    用 Sorted Set 存时间戳；每次请求：
      1. 删窗口外的 member
      2. count = ZCARD
      3. 如 >= limit 则拒
      4. 否则 ZADD 当前 ts + EXPIRE 续期
    全部用 pipeline 减少 round-trip。
"""
import time

from fastapi import HTTPException

from app.core.redis import get_redis


async def check_rate_limit(
    key: str,
    limit: int,
    window_sec: int,
    message: str | None = None,
) -> None:
    """超限抛 429。

    key: Redis sorted set key，建议格式 'group:action:ip' 或 'group:action:user_id'
    limit: 窗口内最大次数
    window_sec: 滑动窗口秒数
    message: 自定义 429 detail 文本；默认为英文格式 'Rate limit: N/Ns'
    """
    redis = await get_redis()
    now = time.time()

    pipe = redis.pipeline()
    # 1. 删过期 member
    pipe.zremrangebyscore(key, 0, now - window_sec)
    # 2. count
    pipe.zcard(key)
    # 3. 加当前请求（用 ns 精度避免同一秒多请求 score 冲突）
    pipe.zadd(key, {f"{now}:{time.monotonic_ns()}": now})
    # 4. 续期 key
    pipe.expire(key, window_sec)
    _, count, _, _ = await pipe.execute()

    if count >= limit:
        raise HTTPException(
            status_code=429,
            detail=message or f"Rate limit: {limit}/{window_sec}s",
            headers={"Retry-After": str(window_sec)},
        )
