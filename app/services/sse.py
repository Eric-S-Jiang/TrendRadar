"""SSE 连接管理与 Redis pub/sub 订阅。

每个 SSE 客户端独立订阅 Redis 频道 "gpxx:events"，
通过 asyncio.Queue 拼合 Redis 消息和 ping 心跳。
"""
import asyncio
import json
import time
from collections.abc import AsyncIterator

from loguru import logger

# 全局连接计数（CPython GIL 保证单进程内 int 操作原子性）
_connection_count: int = 0

CHANNEL = "gpxx:events"
PING_INTERVAL = 15  # 秒


def get_connection_count() -> int:
    return _connection_count


async def event_generator(
    redis,
    topics: set[str] | None = None,
) -> AsyncIterator[str]:
    """
    产出 SSE 格式字符串流。

    topics=None 表示订阅全部事件类型。
    每 PING_INTERVAL 秒发送一次 ping 保持连接。
    """
    global _connection_count
    _connection_count += 1
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=200)

    async def _redis_reader():
        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(CHANNEL)
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                raw = msg["data"]
                try:
                    event_obj = json.loads(raw)
                    etype = event_obj.get("type", "")
                    if topics and etype not in topics:
                        continue
                    sse_line = (
                        f"event: {etype}\n"
                        f"data: {json.dumps(event_obj, ensure_ascii=False)}\n\n"
                    )
                    await queue.put(sse_line)
                except (json.JSONDecodeError, Exception):
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await pubsub.unsubscribe(CHANNEL)
            except Exception:
                pass

    async def _pinger():
        try:
            while True:
                await asyncio.sleep(PING_INTERVAL)
                ts = int(time.time())
                await queue.put(f'event: ping\ndata: {{"ts":{ts}}}\n\n')
        except asyncio.CancelledError:
            pass

    reader_task = asyncio.create_task(_redis_reader())
    ping_task = asyncio.create_task(_pinger())

    try:
        while True:
            line = await queue.get()
            yield line
    except asyncio.CancelledError:
        pass
    except GeneratorExit:
        pass
    finally:
        reader_task.cancel()
        ping_task.cancel()
        _connection_count -= 1
        logger.debug("SSE client disconnected, total={}", _connection_count)
