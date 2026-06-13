"""APScheduler 定时任务。

两个任务：
  - 每 2 分钟：检查新浪新闻，若有新条目则发布 news.new 事件
  - 每 30 秒：发布 quote.update 事件（客户端收到后自行刷新行情）
"""
import asyncio
import json
import time
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.core.redis import get_redis
from app.services.sse import CHANNEL

_scheduler: AsyncIOScheduler | None = None
_last_news_ids: set[str] = set()


# ── 发布工具 ─────────────────────────────────────────────────────────────────

async def _publish(event_type: str, data: dict[str, Any]) -> None:
    try:
        redis = await get_redis()
        payload = json.dumps({"type": event_type, "ts": int(time.time()), **data},
                             ensure_ascii=False)
        await redis.publish(CHANNEL, payload)
    except Exception as exc:
        logger.warning("SSE publish failed: {}", exc)


# ── 定时任务 ─────────────────────────────────────────────────────────────────

async def _task_news_new() -> None:
    """每 2 分钟：检查新浪新闻是否有新条目，有则发布 news.new。"""
    global _last_news_ids
    try:
        from app.services.sina import fetch_sina_news
        items = await fetch_sina_news(20)
        current_ids = {item["id"] for item in items if item.get("id")}
        new_ids = current_ids - _last_news_ids
        if new_ids and _last_news_ids:
            new_items = [i for i in items if i.get("id") in new_ids][:5]
            preview = new_items[0]["title"][:30] if new_items else ""
            await _publish("news.new", {"count": len(new_ids), "preview": preview})
            logger.debug("news.new published: {} new items", len(new_ids))
        _last_news_ids = current_ids
    except Exception as exc:
        logger.warning("_task_news_new failed: {}", exc)


async def _task_quote_update() -> None:
    """每 30 秒：发布 quote.update 信号（客户端自行刷新行情）。"""
    from app.services.sse import get_connection_count
    if get_connection_count() == 0:
        return
    try:
        await _publish("quote.update", {})
    except Exception as exc:
        logger.warning("_task_quote_update failed: {}", exc)


# ── 生命周期 ─────────────────────────────────────────────────────────────────

def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        _scheduler.add_job(_task_news_new,    "interval", minutes=2,  id="news_new",    max_instances=1)
        _scheduler.add_job(_task_quote_update, "interval", seconds=30, id="quote_update", max_instances=1)
    return _scheduler


async def start_scheduler() -> None:
    sch = get_scheduler()
    if not sch.running:
        sch.start()
        logger.info("APScheduler started")


async def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
    _scheduler = None
