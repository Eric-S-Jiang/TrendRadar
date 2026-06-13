"""D9 新浪财经新闻接口 端到端验收脚本。

预期 Part A + Part B 共 8 项 PASS。

Part A: 单元测试（_parse_ctime）
Part B: 路由层测试（HTTP 层，mock sina service 函数）
Part C (可选): 真实联网探测，标记为 NETWORK
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fakeredis.aioredis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def main() -> int:
    from app.core import redis as redis_mod
    redis_mod.set_redis(fakeredis.aioredis.FakeRedis(decode_responses=True))

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

    print("=== D9 Sina Finance News ===\n")

    from app.services.sina import _parse_ctime

    # ──────────────────────────────────────────────────────────────────────
    # Part A: unit tests
    # ──────────────────────────────────────────────────────────────────────

    def t01_parse_ctime_valid():
        ts = _parse_ctime("2024-01-15 10:30:00")
        assert isinstance(ts, int) and ts > 0

    def t02_parse_ctime_invalid():
        assert _parse_ctime("") == 0
        assert _parse_ctime("bad-date") == 0
        assert _parse_ctime(None) == 0

    def t03_parse_ctime_truncate():
        ts = _parse_ctime("2024-06-01 08:00:00")
        assert ts > 1_700_000_000

    case("A01 _parse_ctime valid datetime", t01_parse_ctime_valid)
    case("A02 _parse_ctime invalid/empty → 0", t02_parse_ctime_invalid)
    case("A03 _parse_ctime reasonable value", t03_parse_ctime_truncate)

    # ──────────────────────────────────────────────────────────────────────
    # Part B: route tests with mocked service
    # ──────────────────────────────────────────────────────────────────────

    _MOCK_NEWS = [
        {
            "id": "n001",
            "title": "A股市场今日行情",
            "url": "https://finance.sina.com.cn/xxx",
            "ctime": 1718000000,
            "ctime_str": "2024-06-10 10:00",
            "source": "新浪财经",
            "intro": "今日A股市场....",
        },
        {
            "id": "n002",
            "title": "央行发布最新政策",
            "url": "https://finance.sina.com.cn/yyy",
            "ctime": 1718001000,
            "ctime_str": "2024-06-10 10:16",
            "source": "财联社",
            "intro": "央行公告...",
        },
    ]

    def t04_news_sina_200():
        with patch("app.services.sina.fetch_sina_news", new=AsyncMock(return_value=_MOCK_NEWS)):
            r = client.get("/api/news/sina")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == "200"
        assert isinstance(body["data"], list)
        assert len(body["data"]) == 2

    def t05_news_sina_fields():
        with patch("app.services.sina.fetch_sina_news", new=AsyncMock(return_value=_MOCK_NEWS)):
            r = client.get("/api/news/sina")
        item = r.json()["data"][0]
        for key in ("id", "title", "url", "ctime", "ctime_str", "source", "intro"):
            assert key in item, f"missing field: {key}"

    def t06_news_sina_num_param():
        with patch("app.services.sina.fetch_sina_news", new=AsyncMock(return_value=_MOCK_NEWS)) as mock:
            client.get("/api/news/sina?num=20")
        mock.assert_called_once_with(20)

    def t07_news_sina_num_validation_low():
        r = client.get("/api/news/sina?num=0")
        assert r.status_code == 422

    def t08_news_sina_num_validation_high():
        r = client.get("/api/news/sina?num=101")
        assert r.status_code == 422

    case("B04 GET /api/news/sina → 200 envelope", t04_news_sina_200)
    case("B05 news items contain required fields", t05_news_sina_fields)
    case("B06 num param forwarded to service", t06_news_sina_num_param)
    case("B07 num=0 → 422", t07_news_sina_num_validation_low)
    case("B08 num=101 → 422", t08_news_sina_num_validation_high)

    # ──────────────────────────────────────────────────────────────────────
    # Part C: live network (optional)
    # ──────────────────────────────────────────────────────────────────────
    import os
    if os.getenv("NETWORK"):
        import asyncio
        from app.services.sina import fetch_sina_news

        async def _live():
            items = await fetch_sina_news(10)
            assert isinstance(items, list)
            if items:
                assert "title" in items[0]
                assert "ctime" in items[0]
            return len(items)

        try:
            n = asyncio.run(_live())
            print(f"  [PASS] L01 live fetch_sina_news(10): {n} items")
            passed += 1
        except Exception as e:
            print(f"  [ERROR] L01 live: {type(e).__name__}: {e}")
            failed += 1

    print(f"\nResult: {passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
