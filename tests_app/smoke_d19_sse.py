"""D19-D23 SSE 实时推送验收脚本。

预期共 8 项 PASS：
  A01-A03  单元（service 层 pub/sub 逻辑）
  B04-B08  路由层测试（scheduler + 端点注册 + 限流 + 任务调用）

SSE 是无限流，HTTP 层测试使用 mock 有限 generator 避免阻塞。
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fakeredis.aioredis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def main() -> int:
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    from app.core import redis as redis_mod
    redis_mod.set_redis(fake_redis)

    from app.main import app
    client = TestClient(app)

    passed = 0
    failed = 0

    def case(name, fn):
        nonlocal passed, failed
        try:
            fn()
            print(f"  [PASS] {name}")
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
            failed += 1

    print("=== D19-D23 SSE ===\n")

    from app.services import sse as sse_svc
    from app.core import redis as redis_mod

    # ──────────────────────────────────────────────────────────────────────
    # Part A: unit tests（直接测 service 层）
    # ──────────────────────────────────────────────────────────────────────

    def t01_connection_count_zero():
        assert sse_svc.get_connection_count() == 0

    def t02_channel_constant():
        assert sse_svc.CHANNEL == "gpxx:events"
        assert sse_svc.PING_INTERVAL == 15

    def t03_publish_and_receive():
        """向 fakeredis 发布事件，event_generator 应能收到。"""
        events_received = []

        async def _run():
            redis = await redis_mod.get_redis()

            async def _publish():
                await asyncio.sleep(0.08)
                payload = json.dumps({
                    "type": "news.new",
                    "ts": int(time.time()),
                    "preview": "test news",
                })
                await redis.publish(sse_svc.CHANNEL, payload)

            async def _collect():
                gen = sse_svc.event_generator(redis, {"news.new"})
                async for line in gen:
                    events_received.append(line)
                    break

            pub = asyncio.create_task(_publish())
            col = asyncio.create_task(_collect())
            done, pending = await asyncio.wait(
                [pub, col], timeout=2.0, return_when=asyncio.ALL_COMPLETED
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

        asyncio.run(_run())
        assert len(events_received) >= 1, "should receive at least 1 event"
        line = events_received[0]
        assert "event: news.new" in line, f"unexpected: {line!r}"
        assert "data:" in line

    case("A01 initial connection count = 0", t01_connection_count_zero)
    case("A02 channel/ping constants correct", t02_channel_constant)
    case("A03 publish event → generator receives it", t03_publish_and_receive)

    # ──────────────────────────────────────────────────────────────────────
    # Part B: route tests
    # ──────────────────────────────────────────────────────────────────────

    def t04_scheduler_running():
        """APScheduler 配置了正确的 jobs（手动启动，不依赖 lifespan）。"""
        from app.tasks.scheduler import start_scheduler, stop_scheduler, get_scheduler
        asyncio.run(start_scheduler())
        sch = get_scheduler()
        assert sch.running, "APScheduler should be running after start_scheduler()"
        ids = [j.id for j in sch.get_jobs()]
        assert "news_new" in ids, f"jobs: {ids}"
        assert "quote_update" in ids, f"jobs: {ids}"

    def _finite_generator(*args, **kwargs):
        """有限 SSE generator，用于 HTTP 层测试，避免阻塞。"""
        async def _gen():
            yield 'event: ping\ndata: {"ts":1}\n\n'
        return _gen()

    def t05_sse_returns_event_stream():
        """GET /api/stream → 200 + text/event-stream（mock 有限流）。"""
        with patch("app.services.sse.event_generator", side_effect=_finite_generator):
            r = client.get("/api/stream")
        assert r.status_code == 200, f"status={r.status_code}, body={r.text}"
        ct = r.headers.get("content-type", "")
        assert "text/event-stream" in ct, f"content-type={ct!r}"

    def t06_sse_topic_filter_param():
        """topics 参数被接受（不报 422）。"""
        with patch("app.services.sse.event_generator", side_effect=_finite_generator):
            r = client.get("/api/stream?topics=news.new,quote.update")
        assert r.status_code == 200

    def t07_sse_max_connections_503():
        """超出连接数上限 → 503。"""
        with patch.object(sse_svc, "get_connection_count", return_value=9999):
            r = client.get("/api/stream")
            assert r.status_code == 503, f"expected 503, got {r.status_code}"

    def t08_scheduler_publish():
        """直接调用 scheduler 任务函数，验证不抛异常。"""
        from app.tasks.scheduler import _task_quote_update, _task_news_new
        asyncio.run(_task_quote_update())
        # news_new 需要访问新浪，mock 掉
        async def _mock_news(num=50):
            return [{"id": "1", "title": "test"}]
        with patch("app.services.sina.fetch_sina_news", new=AsyncMock(side_effect=_mock_news)):
            asyncio.run(_task_news_new())

    case("B04 APScheduler running with correct jobs", t04_scheduler_running)
    case("B05 GET /api/stream → 200 + text/event-stream", t05_sse_returns_event_stream)
    case("B06 GET /api/stream?topics=... → 200", t06_sse_topic_filter_param)
    case("B07 GET /api/stream over limit → 503", t07_sse_max_connections_503)
    case("B08 scheduler tasks run without error", t08_scheduler_publish)

    print(f"\nResult: {passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
