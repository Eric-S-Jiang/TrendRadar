"""SSE 实时推送 — D19-D23 实现。

端点参见 GPXX-V3-接口契约.md §6。
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.deps import RedisDep
from app.services import sse

router = APIRouter()
settings = get_settings()


@router.get("")
async def stream_events(
    topics: str = Query(
        default="",
        description="逗号分隔的事件类型，如 news.new,quote.update。空表示订阅全部。",
    ),
    redis: RedisDep = None,
):
    """SSE 实时推送入口。

    - 每 15s 自动发送 ping 心跳。
    - 超过最大连接数（{max}）返回 503。
    """.format(max=settings.SSE_MAX_CONNECTIONS)

    if sse.get_connection_count() >= settings.SSE_MAX_CONNECTIONS:
        raise HTTPException(status_code=503, detail="SSE 连接数已达上限，请稍后重试")

    topic_set: set[str] | None = None
    if topics.strip():
        topic_set = {t.strip() for t in topics.split(",") if t.strip()}

    return StreamingResponse(
        sse.event_generator(redis, topic_set),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Nginx 禁止缓冲
        },
    )
