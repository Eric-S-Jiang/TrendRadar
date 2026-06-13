"""D4 缓存装饰器 + 健康检查 端到端验收脚本。

预期 13 项测试全部 PASS。
"""
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fakeredis.aioredis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def main() -> int:
    # 注入 fakeredis
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

    print("=== D4 cache + health ===\n")

    # ------------------------------------------------------------
    # Part A: cache 装饰器单元测试
    # ------------------------------------------------------------
    from app.services.cache import cache, invalidate, _make_key

    call_count = {"n": 0}

    @cache(prefix="d4:test", ttl=60)
    async def expensive(x: int, y: int = 0) -> dict:
        call_count["n"] += 1
        return {"sum": x + y, "n": call_count["n"]}

    def t01_cache_hit():
        call_count["n"] = 0
        # 先清 redis
        asyncio.run(_flushdb(redis_mod))
        # 第一次：未命中，执行函数
        r1 = asyncio.run(expensive(1, y=2))
        assert r1 == {"sum": 3, "n": 1}, r1
        # 第二次：命中，不执行函数
        r2 = asyncio.run(expensive(1, y=2))
        assert r2 == {"sum": 3, "n": 1}, r2
        assert call_count["n"] == 1, f"function should run once, ran {call_count['n']}"

    def t02_cache_different_args():
        # 不同参数不命中
        r3 = asyncio.run(expensive(2, y=3))
        assert r3 == {"sum": 5, "n": 2}
        assert call_count["n"] == 2

    def t03_cache_kwarg_order_irrelevant():
        # kwargs 顺序无关（_make_key 用 sorted）
        k1 = _make_key((1,), {"a": 1, "b": 2})
        k2 = _make_key((1,), {"b": 2, "a": 1})
        assert k1 == k2, "kwargs order should not affect key"

    def t04_cache_dynamic_ttl():
        # ttl 是函数
        ttl_calls = {"n": 0}

        def ttl_fn():
            ttl_calls["n"] += 1
            return 30

        @cache(prefix="d4:dyn", ttl=ttl_fn)
        async def f(x: int) -> int:
            return x * 2

        asyncio.run(_flushdb(redis_mod))
        r1 = asyncio.run(f(5))
        r2 = asyncio.run(f(5))  # 命中，不调 ttl_fn
        assert r1 == 10
        assert r2 == 10
        assert ttl_calls["n"] == 1, f"ttl_fn should be called once (on miss), got {ttl_calls['n']}"

    def t05_cache_serializes_non_json():
        # default=str 处理 datetime
        @cache(prefix="d4:dt", ttl=60)
        async def with_date() -> dict:
            return {"now": datetime(2026, 6, 7, 12, 0, 0)}

        asyncio.run(_flushdb(redis_mod))
        r1 = asyncio.run(with_date())
        r2 = asyncio.run(with_date())
        # 第二次从 Redis 拿出来是 str（json round-trip）
        assert isinstance(r2["now"], str)
        assert "2026-06-07" in r2["now"]

    def t06_cache_redis_unavailable_fallback():
        # Redis 挂了应该走原函数（不能让业务请求失败）
        original = redis_mod._redis
        # 把 redis 替换成会抛错的对象
        class BrokenRedis:
            async def get(self, *a, **kw): raise ConnectionError("boom")
            async def setex(self, *a, **kw): raise ConnectionError("boom")

        redis_mod.set_redis(BrokenRedis())  # type: ignore

        try:
            call_count["n"] = 0
            r = asyncio.run(expensive(99, y=1))
            assert r["sum"] == 100
            # 失败两次（读+写）但仍返回正确值
        finally:
            redis_mod.set_redis(original)

    def t07_invalidate():
        # 主动失效
        asyncio.run(_flushdb(redis_mod))
        # 写几个 key
        asyncio.run(expensive(11))
        asyncio.run(expensive(12))
        deleted = asyncio.run(invalidate("d4:test"))
        assert deleted >= 2, f"should delete ≥2 keys, got {deleted}"

    # ------------------------------------------------------------
    # Part B: calendar
    # ------------------------------------------------------------
    def t08_is_trading_weekend():
        from app.services.calendar import is_trading, TZ
        # 2026-06-06 (Sat) 10:00 SH
        sat = TZ.localize(datetime(2026, 6, 6, 10, 0, 0))
        assert is_trading(sat) is False, "Saturday should be non-trading"

    def t09_is_trading_morning():
        from app.services.calendar import is_trading, TZ
        # 2026-06-08 (Mon) 10:00 SH
        mon10 = TZ.localize(datetime(2026, 6, 8, 10, 0, 0))
        assert is_trading(mon10) is True, "Monday 10:00 should be trading"
        # 边界 11:30 仍在窗口内（含等于）
        mon1130 = TZ.localize(datetime(2026, 6, 8, 11, 30, 0))
        assert is_trading(mon1130) is True
        # 12:00 不在
        mon12 = TZ.localize(datetime(2026, 6, 8, 12, 0, 0))
        assert is_trading(mon12) is False

    # ------------------------------------------------------------
    # Part C: health routes
    # ------------------------------------------------------------
    def t10_health_basic():
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"code": "200", "message": "ok", "data": {"alive": True}}

    def t11_health_db():
        r = client.get("/api/health/db")
        assert r.status_code == 200
        data = r.json()["data"]
        # 业务库已经在 D2 建好了
        assert data["business"] is True
        # trend.db 在 D15 之前不存在或没有 platforms 表
        assert data["trend"] is False

    def t12_health_redis():
        r = client.get("/api/health/redis")
        assert r.status_code == 200
        assert r.json()["data"]["redis"] is True

    def t13_health_sources_cached():
        """health/sources 第一次调 _probe_sources，第二次走缓存。

        用 monkeypatch 替换 probe_sources，避免真访问外网。
        """
        asyncio.run(_flushdb(redis_mod))

        call = {"n": 0}

        async def mock_probe():
            call["n"] += 1
            return {
                "tencent": {"ok": True, "status": 200, "latency_ms": 100},
                "eastmoney": {"ok": True, "status": 200, "latency_ms": 80},
                "sina": {"ok": True, "status": 200, "latency_ms": 150},
                "checked_at": "2026-06-07T00:00:00+00:00",
            }

        from app.api import health as health_mod
        with patch.object(health_mod, "probe_sources", mock_probe):
            r1 = client.get("/api/health/sources")
            assert r1.status_code == 200
            assert r1.json()["data"]["tencent"]["ok"] is True

            r2 = client.get("/api/health/sources")
            assert r2.status_code == 200
            assert r2.json()["data"]["tencent"]["ok"] is True

            assert call["n"] == 1, f"probe_sources should run once (cache hit on 2nd), ran {call['n']}"

    cases = [
        ("01 cache: miss → hit (function runs once)", t01_cache_hit),
        ("02 cache: different args → different key", t02_cache_different_args),
        ("03 cache: kwarg order does not affect key", t03_cache_kwarg_order_irrelevant),
        ("04 cache: dynamic TTL (callable)", t04_cache_dynamic_ttl),
        ("05 cache: serializes datetime via default=str", t05_cache_serializes_non_json),
        ("06 cache: Redis broken → fallback to fn (no error)", t06_cache_redis_unavailable_fallback),
        ("07 cache: invalidate() removes keys", t07_invalidate),
        ("08 calendar: weekend → not trading", t08_is_trading_weekend),
        ("09 calendar: weekday windows correct", t09_is_trading_morning),
        ("10 health: basic alive", t10_health_basic),
        ("11 health/db: business=true, trend=false (D15 前)", t11_health_db),
        ("12 health/redis: ping ok", t12_health_redis),
        ("13 health/sources: cached 5min (probe called once)", t13_health_sources_cached),
    ]

    for name, fn in cases:
        case(name, fn)

    print(f"\n=== {passed} passed, {failed} failed ===")
    return 0 if failed == 0 else 1


async def _flushdb(redis_mod):
    r = await redis_mod.get_redis()
    await r.flushdb()


if __name__ == "__main__":
    sys.exit(main())
