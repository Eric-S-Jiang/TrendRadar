"""D10-D11 AI 接口端到端验收脚本。

预期 Part A + Part B 共 12 项 PASS。

Part A: 单元测试（deepseek helpers）
Part B: 路由层测试（mock deepseek.call_deepseek + 真实 DB + fakeredis）
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fakeredis.aioredis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


_MOCK_ANALYSIS = {
    "events": [
        {"title": "央行降准", "category": "policy", "impact": 0.8, "sectors": ["银行"], "stocks": []},
    ],
    "sectors": [
        {"name": "白酒", "view": "bullish", "reason": "资金流入", "weight": 0.7},
    ],
    "signals": [
        {"type": "watch", "code": "sh600519", "action": "hold", "reason": "强势整理"},
    ],
    "watchlist_view": [
        {"code": "sh600519", "rating": "bullish", "comment": "持续关注"},
    ],
    "_meta": {"model": "deepseek-chat", "token_usage": 1500, "cached": False},
}


def main() -> int:
    # 注入 fakeredis
    from app.core import redis as redis_mod
    redis_mod.set_redis(fakeredis.aioredis.FakeRedis(decode_responses=True))

    # 清理 AI 测试数据
    asyncio.run(_reset_ai_data())

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

    print("=== D10-D11 AI Analysis ===\n")

    from app.services.deepseek import (
        apply_compact, build_input_summary, compute_hash, get_time_key,
    )

    # ──────────────────────────────────────────────────────────────────────
    # Part A: unit tests
    # ──────────────────────────────────────────────────────────────────────

    def t01_compute_hash_stable():
        h1 = compute_hash({"indices": [], "sectors": []}, "deepseek-chat")
        h2 = compute_hash({"sectors": [], "indices": []}, "deepseek-chat")
        assert h1 == h2, "hash should be order-independent"
        assert len(h1) == 64

    def t02_compute_hash_model_diff():
        h1 = compute_hash({"data": 1}, "deepseek-chat")
        h2 = compute_hash({"data": 1}, "deepseek-reasoner")
        assert h1 != h2

    def t03_get_time_key():
        tk = get_time_key()
        assert tk in ("盘前", "盘中", "盘后")

    def t04_apply_compact_strips_fields():
        data = {"stockData": [{"code": "sh600519", "name": "茅台", "usT": [1, 2], "cnT": [3, 4]}]}
        result = apply_compact(data)
        assert "usT" not in result["stockData"][0]
        assert "cnT" not in result["stockData"][0]
        assert result["stockData"][0]["code"] == "sh600519"

    def t05_build_input_summary():
        data = {
            "indices": [1, 2],
            "sectors": [1],
            "stockData": [{"code": "sh600519"}, {"code": "sz000001"}],
        }
        s = build_input_summary(data)
        assert "indices=2" in s
        assert "sh600519" in s
        assert len(s) <= 500

    case("A01 compute_hash stable + 64-char", t01_compute_hash_stable)
    case("A02 compute_hash differs by model", t02_compute_hash_model_diff)
    case("A03 get_time_key valid value", t03_get_time_key)
    case("A04 apply_compact removes usT/cnT", t04_apply_compact_strips_fields)
    case("A05 build_input_summary ≤500 chars", t05_build_input_summary)

    # ──────────────────────────────────────────────────────────────────────
    # Part B: route tests
    # ──────────────────────────────────────────────────────────────────────

    # 注册测试用户并登录
    state = {}

    def setup_user():
        r = client.post("/api/auth/register", json={
            "email": "ai_test@example.com",
            "password": "pass1234",
        })
        assert r.status_code == 200, f"register failed: {r.text}"
        state["token"] = r.json()["data"]["access_token"]

    try:
        setup_user()
    except Exception as e:
        print(f"  [ERROR] setup_user: {e}")

    headers = {"Authorization": f"Bearer {state.get('token', '')}"}

    def t06_analyze_no_auth():
        r = client.post("/api/ai/analyze", json={})
        assert r.status_code == 401

    def t07_analyze_success():
        with patch("app.services.deepseek.call_deepseek", new=AsyncMock(return_value=_MOCK_ANALYSIS)):
            r = client.post("/api/ai/analyze", json={
                "indices": [{"code": "sh000001", "name": "上证"}],
                "sectors": [],
                "use_deep": False,
                "compact": False,
            }, headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == "200"
        data = body["data"]
        assert "events" in data
        assert "sectors" in data
        assert "signals" in data
        assert "_meta" in data

    def t08_analyze_cache_hit():
        """同一 input_hash 第二次调用应命中缓存（cached=True）。"""
        payload = {"indices": [{"code": "sz399001"}], "use_deep": False}
        with patch("app.services.deepseek.call_deepseek", new=AsyncMock(return_value=_MOCK_ANALYSIS)):
            client.post("/api/ai/analyze", json=payload, headers=headers)
        # 第二次：mock 不应被调用（若被调用说明缓存未命中）
        mock = AsyncMock(return_value=_MOCK_ANALYSIS)
        with patch("app.services.deepseek.call_deepseek", new=mock):
            r2 = client.post("/api/ai/analyze", json=payload, headers=headers)
        assert r2.status_code == 200
        assert r2.json()["data"]["_meta"]["cached"] is True
        mock.assert_not_called()

    def t09_analyze_compact_mode():
        """compact=True 应正常返回 200（mock 验证 apply_compact 不崩）。"""
        with patch("app.services.deepseek.call_deepseek", new=AsyncMock(return_value=_MOCK_ANALYSIS)):
            r = client.post("/api/ai/analyze", json={
                "stockData": [{"code": "sh600519", "name": "茅台", "usT": [], "cnT": []}],
                "compact": True,
                "use_deep": False,
            }, headers=headers)
        assert r.status_code == 200

    def t10_history_list():
        r = client.get("/api/ai/history", headers=headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert isinstance(data, list)
        if data:
            item = data[0]
            assert "date_key" in item
            assert "time_key" in item
            assert "cache_id" in item
            assert "created_at" in item

    def t11_history_detail():
        r = client.get("/api/ai/history", headers=headers)
        hist = r.json()["data"]
        if not hist:
            print("    (skip: no history entries yet)")
            return
        item = hist[0]
        r2 = client.get(
            f"/api/ai/history/{item['date_key']}/{item['time_key']}",
            headers=headers,
        )
        assert r2.status_code == 200
        assert r2.json()["code"] == "200"

    def t12_history_detail_404():
        r = client.get("/api/ai/history/99991231/盘后", headers=headers)
        assert r.status_code == 404

    case("B06 POST /api/ai/analyze requires auth", t06_analyze_no_auth)
    case("B07 POST /api/ai/analyze → 200 with mock", t07_analyze_success)
    case("B08 POST /api/ai/analyze cache hit → cached=True", t08_analyze_cache_hit)
    case("B09 POST /api/ai/analyze compact mode", t09_analyze_compact_mode)
    case("B10 GET /api/ai/history → list", t10_history_list)
    case("B11 GET /api/ai/history/{date}/{time} → detail", t11_history_detail)
    case("B12 GET /api/ai/history/nonexistent → 404", t12_history_detail_404)

    print(f"\nResult: {passed} passed, {failed} failed")
    return failed


async def _reset_ai_data() -> None:
    """清空 AI 测试数据和测试用户，让脚本可重复运行。"""
    from sqlalchemy import delete
    from app.core.db import BusinessSession
    from app.models.user import User
    from app.models.ai_cache import AiAnalysisCache, UserAiHistory
    async with BusinessSession() as s:
        await s.execute(delete(UserAiHistory))
        await s.execute(delete(AiAnalysisCache))
        await s.execute(delete(User).where(User.email == "ai_test@example.com"))
        await s.commit()


if __name__ == "__main__":
    raise SystemExit(main())
