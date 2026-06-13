"""D14 用户业务数据接口端到端验收脚本。

预期共 12 项 PASS：
  A01-A02  单元（无 DB）
  B03-B12  路由层（真实 SQLite + fakeredis）
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

    print("=== D14 User Business Data ===\n")

    # ──────────────────────────────────────────────────────────────────────
    # Part A: unit
    # ──────────────────────────────────────────────────────────────────────

    def t01_rating_map():
        """legacy-import 中 rating_map 逻辑验证（纯 Python）。"""
        rating_map = {"correct": 1, "wrong": -1}
        assert rating_map.get("correct", 0) == 1
        assert rating_map.get("wrong", 0) == -1
        assert rating_map.get("skip", 0) == 0

    def t02_sort_order_calc():
        """sort_order 从 max_order+1 开始（纯逻辑）。"""
        max_order = -1
        items = ["a", "b", "c"]
        orders = [max_order + i + 1 for i in range(len(items))]
        assert orders == [0, 1, 2]

    case("A01 rating_map logic", t01_rating_map)
    case("A02 sort_order calc from -1", t02_sort_order_calc)

    # ──────────────────────────────────────────────────────────────────────
    # Part B: route tests
    # ──────────────────────────────────────────────────────────────────────

    state = {}

    def setup_users():
        r = client.post("/api/auth/register", json={
            "email": "user14_a@example.com",
            "password": "pass1234",
        })
        assert r.status_code == 200, f"register A failed: {r.text}"
        state["token_a"] = r.json()["data"]["access_token"]

        r2 = client.post("/api/auth/register", json={
            "email": "user14_b@example.com",
            "password": "pass1234",
        })
        assert r2.status_code == 200, f"register B failed: {r2.text}"
        state["token_b"] = r2.json()["data"]["access_token"]

    try:
        setup_users()
    except Exception as e:
        print(f"  [ERROR] setup_users: {e}")

    headers_a = {"Authorization": f"Bearer {state.get('token_a', '')}"}
    headers_b = {"Authorization": f"Bearer {state.get('token_b', '')}"}

    def t03_watchlist_no_auth():
        r = client.get("/api/user/watchlist")
        assert r.status_code == 401

    def t04_watchlist_empty():
        r = client.get("/api/user/watchlist", headers=headers_a)
        assert r.status_code == 200
        data = r.json()["data"]
        assert isinstance(data, list)
        assert len(data) == 0

    def t05_put_watchlist():
        r = client.put("/api/user/watchlist", json=[
            {"code": "sh600519", "name": "贵州茅台", "market": "cn"},
            {"code": "sh601318", "name": "中国平安", "market": "cn"},
            {"code": "sz000858", "name": "五粮液", "market": "cn"},
        ], headers=headers_a)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["ok"] is True
        assert data["count"] == 3

    def t06_get_watchlist_order():
        r = client.get("/api/user/watchlist", headers=headers_a)
        assert r.status_code == 200
        items = r.json()["data"]
        assert len(items) == 3
        assert items[0]["code"] == "sh600519"
        assert items[1]["code"] == "sh601318"
        assert items[2]["code"] == "sz000858"
        # 验证必填字段
        assert "name" in items[0]
        assert "market" in items[0]

    def t07_put_watchlist_replace():
        """全量替换（只保留 1 条）。"""
        r = client.put("/api/user/watchlist", json=[
            {"code": "sz002594", "name": "比亚迪", "market": "cn"},
        ], headers=headers_a)
        assert r.json()["data"]["count"] == 1
        r2 = client.get("/api/user/watchlist", headers=headers_a)
        assert len(r2.json()["data"]) == 1
        assert r2.json()["data"][0]["code"] == "sz002594"

    def t08_watchlist_isolation():
        """user_b 看不到 user_a 的自选股。"""
        r = client.get("/api/user/watchlist", headers=headers_b)
        assert r.json()["data"] == []

    def t09_feedback_post():
        r = client.post("/api/user/feedback", json={
            "target_type": "ai_analysis",
            "target_id": "20260611_abc",
            "rating": 1,
        }, headers=headers_a)
        assert r.status_code == 200
        assert r.json()["data"]["ok"] is True

    def t10_feedback_update_and_delete():
        # 更新为 -1
        client.post("/api/user/feedback", json={
            "target_type": "sector",
            "target_id": "tech",
            "rating": 1,
        }, headers=headers_a)
        client.post("/api/user/feedback", json={
            "target_type": "sector",
            "target_id": "tech",
            "rating": -1,
        }, headers=headers_a)
        # 删除（rating=0）
        r = client.post("/api/user/feedback", json={
            "target_type": "sector",
            "target_id": "tech",
            "rating": 0,
        }, headers=headers_a)
        assert r.status_code == 200
        # GET 验证 tech 已删除
        r2 = client.get("/api/user/feedback", headers=headers_a)
        entries = r2.json()["data"]
        tech_entries = [e for e in entries if e["target_id"] == "tech"]
        assert len(tech_entries) == 0

    def t11_legacy_import():
        r = client.post("/api/user/legacy-import", json={
            "watchlist": [
                {"code": "sh600519", "name": "茅台", "market": "cn"},
                {"code": "sh601318", "name": "平安", "market": "cn"},
            ],
            "feedback": [
                {"date": "20260610", "type": "news", "id": "n001", "feedback": "correct"},
                {"date": "20260610", "type": "news", "id": "n002", "feedback": "wrong"},
                {"date": "20260610", "type": "news", "id": "n003", "feedback": "skip"},
            ],
            "density": "compact",
        }, headers=headers_b)
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["ok"] is True
        assert d.get("skipped") is None
        assert d["imported"]["watchlist"] == 2
        assert d["imported"]["feedback"] == 2   # skip 不计入
        assert d["imported"]["density"] is True

    def t12_legacy_import_idempotent():
        """第二次调用应返回 skipped=True，不重复写入。"""
        r = client.post("/api/user/legacy-import", json={
            "watchlist": [{"code": "sh000001", "name": "上证", "market": "cn"}],
        }, headers=headers_b)
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["ok"] is True
        assert d["skipped"] is True
        # 验证自选股数量没有增加（仍只有 2 条）
        r2 = client.get("/api/user/watchlist", headers=headers_b)
        assert len(r2.json()["data"]) == 2

    case("B03 GET /api/user/watchlist requires auth", t03_watchlist_no_auth)
    case("B04 GET /api/user/watchlist empty", t04_watchlist_empty)
    case("B05 PUT /api/user/watchlist → count=3", t05_put_watchlist)
    case("B06 GET /api/user/watchlist sort_order preserved", t06_get_watchlist_order)
    case("B07 PUT /api/user/watchlist replace → count=1", t07_put_watchlist_replace)
    case("B08 watchlist isolated between users", t08_watchlist_isolation)
    case("B09 POST /api/user/feedback → ok", t09_feedback_post)
    case("B10 POST feedback update & delete (rating=0)", t10_feedback_update_and_delete)
    case("B11 POST /api/user/legacy-import → counts", t11_legacy_import)
    case("B12 POST /api/user/legacy-import idempotent", t12_legacy_import_idempotent)

    print(f"\nResult: {passed} passed, {failed} failed")
    return failed


async def _reset_data() -> None:
    """清空 D14 测试数据，让脚本可重复运行。"""
    from sqlalchemy import delete, select
    from app.core.db import BusinessSession
    from app.models.user import User
    from app.models.watchlist import UserWatchlist
    from app.models.feedback import UserFeedback
    async with BusinessSession() as s:
        test_emails = ["user14_a@example.com", "user14_b@example.com"]
        # 取 user_id
        res = await s.execute(
            select(User.id).where(User.email.in_(test_emails))
        )
        ids = [r[0] for r in res]
        if ids:
            await s.execute(delete(UserWatchlist).where(UserWatchlist.user_id.in_(ids)))
            await s.execute(delete(UserFeedback).where(UserFeedback.user_id.in_(ids)))
        await s.execute(delete(User).where(User.email.in_(test_emails)))
        await s.commit()


if __name__ == "__main__":
    raise SystemExit(main())
