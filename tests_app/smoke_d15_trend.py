"""D15-D17 TrendRadar 热点接口端到端验收脚本。

预期共 13 项 PASS：
  A01-A04  trend service 单元测试（读实际 DB 文件）
  B05-B13  路由层测试（真实 SQLite + fakeredis）
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fakeredis.aioredis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def main() -> int:
    from app.core import redis as redis_mod
    redis_mod.set_redis(fakeredis.aioredis.FakeRedis(decode_responses=True))

    asyncio.run(_reset_data())

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

    print("=== D15-D17 TrendRadar ===\n")

    from app.services import trend as trend_svc

    # ──────────────────────────────────────────────────────────────────────
    # Part A: trend service unit tests（需要实际 DB 文件）
    # ──────────────────────────────────────────────────────────────────────

    latest_date = trend_svc.get_latest_date()

    def t01_get_db_dates():
        dates = trend_svc.get_db_dates()
        assert isinstance(dates, list)
        if dates:
            assert len(dates[0]) == 10, f"date format wrong: {dates[0]}"

    def t02_get_latest_date():
        if not latest_date:
            print("    (skip: no trend DB files found)")
            return
        assert len(latest_date) == 10
        assert "-" in latest_date

    def t03_fetch_platforms():
        if not latest_date:
            print("    (skip: no trend DB files)")
            return
        platforms = asyncio.run(trend_svc.fetch_platforms())
        assert isinstance(platforms, list)
        if platforms:
            p = platforms[0]
            assert "id" in p
            assert "name" in p
            assert "item_count" in p

    def t04_fetch_latest():
        if not latest_date:
            print("    (skip: no trend DB files)")
            return
        items = asyncio.run(trend_svc.fetch_latest(limit=5))
        assert isinstance(items, list)
        if items:
            item = items[0]
            assert "id" in item
            assert "title" in item
            assert "platform_id" in item
            assert "rank" in item

    case("A01 get_db_dates returns list", t01_get_db_dates)
    case("A02 get_latest_date format", t02_get_latest_date)
    case("A03 fetch_platforms returns platforms", t03_fetch_platforms)
    case("A04 fetch_latest returns news items", t04_fetch_latest)

    # ──────────────────────────────────────────────────────────────────────
    # Part B: route tests
    # ──────────────────────────────────────────────────────────────────────

    state = {}

    def setup_user():
        r = client.post("/api/auth/register", json={
            "email": "trend_test@example.com",
            "password": "pass1234",
        })
        assert r.status_code == 200, f"register failed: {r.text}"
        state["token"] = r.json()["data"]["access_token"]

    try:
        setup_user()
    except Exception as e:
        print(f"  [ERROR] setup_user: {e}")

    headers = {"Authorization": f"Bearer {state.get('token', '')}"}

    def t05_trend_platforms():
        r = client.get("/api/news/trend/platforms")
        assert r.status_code == 200
        data = r.json()["data"]
        assert isinstance(data, list)

    def t06_trend_latest():
        r = client.get("/api/news/trend/latest?limit=5")
        assert r.status_code == 200
        data = r.json()["data"]
        assert isinstance(data, list)

    def t07_trend_latest_with_platform():
        if not latest_date:
            print("    (skip: no trend DB files)")
            return
        # 取第一个平台再查
        r = client.get("/api/news/trend/platforms")
        platforms = r.json()["data"]
        if not platforms:
            print("    (skip: no platforms in DB)")
            return
        pid = platforms[0]["id"]
        r2 = client.get(f"/api/news/trend/latest?platform={pid}&limit=3")
        assert r2.status_code == 200
        items = r2.json()["data"]
        assert isinstance(items, list)
        for item in items:
            assert item["platform_id"] == pid

    def t08_trend_search():
        r = client.get("/api/news/trend/search?q=a")
        assert r.status_code == 200
        assert isinstance(r.json()["data"], list)

    def t09_trend_search_empty_q():
        r = client.get("/api/news/trend/search?q=")
        assert r.status_code in (422, 200)

    def t10_trend_rank_history():
        r = client.get("/api/news/trend/1/rank-history")
        assert r.status_code == 200
        data = r.json()["data"]
        assert isinstance(data, list)
        if data:
            assert "rank" in data[0]
            assert "crawl_time" in data[0]

    def t11_favorite_no_auth():
        r = client.post("/api/news/trend/1/favorite")
        assert r.status_code == 401

    def t12_favorite_add():
        if not latest_date:
            print("    (skip: no trend DB files)")
            return
        # 取第一个存在的 news_item id
        r_items = client.get("/api/news/trend/latest?limit=1")
        items = r_items.json()["data"]
        if not items:
            print("    (skip: no news items in DB)")
            return
        news_id = items[0]["id"]
        state["news_id"] = news_id

        r = client.post(
            f"/api/news/trend/{news_id}/favorite?date={latest_date}",
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["data"]["ok"] is True

        # 幂等：再次收藏不应报错
        r2 = client.post(
            f"/api/news/trend/{news_id}/favorite?date={latest_date}",
            headers=headers,
        )
        assert r2.status_code == 200

    def t13_favorite_list_and_delete():
        if not latest_date or "news_id" not in state:
            print("    (skip: depends on t12)")
            return
        news_id = state["news_id"]

        # GET favorites
        r = client.get("/api/news/trend/favorites", headers=headers)
        assert r.status_code == 200
        favs = r.json()["data"]
        assert isinstance(favs, list)
        assert any(f["news_item_id"] == news_id for f in favs)

        # DELETE
        r2 = client.delete(
            f"/api/news/trend/{news_id}/favorite?date={latest_date}",
            headers=headers,
        )
        assert r2.status_code == 200

        # 验证已删除
        r3 = client.get("/api/news/trend/favorites", headers=headers)
        favs_after = r3.json()["data"]
        assert not any(f["news_item_id"] == news_id for f in favs_after)

    case("B05 GET /api/news/trend/platforms", t05_trend_platforms)
    case("B06 GET /api/news/trend/latest", t06_trend_latest)
    case("B07 GET /api/news/trend/latest?platform=xxx", t07_trend_latest_with_platform)
    case("B08 GET /api/news/trend/search", t08_trend_search)
    case("B09 GET /api/news/trend/search empty q → 422/200", t09_trend_search_empty_q)
    case("B10 GET /api/news/trend/{id}/rank-history", t10_trend_rank_history)
    case("B11 POST /api/news/trend/{id}/favorite requires auth", t11_favorite_no_auth)
    case("B12 POST /api/news/trend/{id}/favorite → ok + idempotent", t12_favorite_add)
    case("B13 GET favorites + DELETE favorite", t13_favorite_list_and_delete)

    print(f"\nResult: {passed} passed, {failed} failed")
    return failed


async def _reset_data() -> None:
    from sqlalchemy import delete, select
    from app.core.db import BusinessSession
    from app.models.user import User
    from app.models.favorite import UserFavoriteNews
    async with BusinessSession() as s:
        res = await s.execute(
            select(User.id).where(User.email == "trend_test@example.com")
        )
        ids = [r[0] for r in res]
        if ids:
            await s.execute(delete(UserFavoriteNews).where(UserFavoriteNews.user_id.in_(ids)))
        await s.execute(delete(User).where(User.email == "trend_test@example.com"))
        await s.commit()


if __name__ == "__main__":
    raise SystemExit(main())
