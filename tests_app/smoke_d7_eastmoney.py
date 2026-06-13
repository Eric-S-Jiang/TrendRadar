"""D7 东方财富接口 端到端验收脚本。

预期 22 项测试 PASS。

Part A: 单元测试（_pf + _fetch_ulist 结构解析，mock _get_push2）
Part B: 路由层测试（HTTP 层，mock eastmoney service 函数）
Part C (可选): 真实联网探测，标记为 NETWORK
"""
import asyncio
import os
import sys
import time
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

    def skipped(name, reason):
        print(f"  [SKIP] {name}: {reason}")

    print("=== D7 eastmoney (Eastmoney Finance) ===\n")

    from app.services.eastmoney import _pf

    # ──────────────────────────────────────────────────────────────────────
    # Part A: unit tests
    # ──────────────────────────────────────────────────────────────────────

    def t01_pf_safety():
        assert _pf(None) == 0.0
        assert _pf("-") == 0.0
        assert _pf("") == 0.0
        assert _pf("nan") == 0.0
        assert _pf(float("nan")) == 0.0
        assert _pf(float("inf")) == 0.0
        assert _pf("-inf") == 0.0
        assert _pf("3.14") == 3.14
        assert _pf(100) == 100.0

    def t02_pf_numeric():
        assert _pf("1.17") == 1.17
        assert _pf("-0.5") == -0.5
        assert _pf(0) == 0.0

    # ──────────────────────────────────────────────────────────────────────
    # Part B: route tests with mocked service functions
    # ──────────────────────────────────────────────────────────────────────

    _MOCK_SECTORS = [
        {
            "code": "BK0438", "name": "白酒", "price": 12000.50,
            "pct": 2.35, "change": 280.30, "pct3d": 3.1, "pct5d": 4.2,
            "up_count": 45, "down_count": 12,
            "main_inflow": 3.5e8, "leader": None, "leader_pct": None,
        }
    ]
    _MOCK_BREADTH = {
        "up_count": 2100, "down_count": 1800, "flat_count": None,
        "limit_up": 45, "limit_down": 12, "ts": int(time.time()),
    }
    _MOCK_NORTH = {
        "north_net": 25.3, "south_net": -8.5,
        "hk_to_sh": 12.0, "hk_to_sz": 13.3,
        "sh_to_hk": -3.0, "sz_to_hk": -5.5,
        "ts": int(time.time()),
    }
    _MOCK_NORTH_HIST = {
        "days": [{"date": "2026-06-04", "net": 12.1}, {"date": "2026-06-05", "net": 25.3}],
        "cum5d": 37.4,
    }
    _MOCK_MAIN_CAP = {
        "total_yi": 30.5, "inflow_yi": 40.1, "outflow_yi": -9.6,
        "top3": [{"name": "银行", "amt_yi": 12.3}],
        "ts": int(time.time()),
    }
    _MOCK_MARGIN = {
        "total_balance": 16500.2, "financing_balance": 16200.0,
        "securities_balance": 300.2, "day_change": -50.3, "date": "2026-06-04",
    }
    _MOCK_LIMIT = {
        "limit_up": 45, "limit_down": 12,
        "natural_limit_up": None, "broken_limit_up": None,
        "ts": int(time.time()),
    }
    _MOCK_TURNOVER = {
        "total": 9500.3, "sh": 4200.1, "sz": 5300.2,
        "unit": "亿元", "ts": int(time.time()),
    }
    _MOCK_INTL = [
        {"secid": "100.HSI", "code": "HSI", "name": "恒生指数", "price": 17800.0, "pct": -0.5, "ts": int(time.time())},
        {"secid": "100.N225", "code": "N225", "name": "日经225", "price": 38000.0, "pct": 0.3, "ts": int(time.time())},
        {"secid": "100.KS11", "code": "KS11", "name": "韩国综指", "price": 2550.0, "pct": 0.1, "ts": int(time.time())},
    ]
    _MOCK_KLINE = {
        "secid": "1.000001", "code": "000001", "name": "上证指数",
        "klines": ["2026-06-04,3090.00,3100.00,3115.00,3085.00,12345678,0.32"],
    }
    _MOCK_SEARCH = [
        {"code": "sh600519", "name": "贵州茅台", "market": "cn", "match_type": "name"},
    ]

    async def _flushdb(redis_mod):
        r = await redis_mod.get_redis()
        await r.flushdb()

    def t03_sectors_route():
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.eastmoney.fetch_sectors", AsyncMock(return_value=_MOCK_SECTORS)):
            r = client.get("/api/sectors")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["code"] == "200"
            data = body["data"]
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["code"] == "BK0438"
            assert data[0]["name"] == "白酒"
            assert data[0]["pct"] == 2.35

    def t04_sectors_breadth_route():
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.eastmoney.fetch_market_breadth", AsyncMock(return_value=_MOCK_BREADTH)):
            r = client.get("/api/sectors/breadth")
            assert r.status_code == 200
            data = r.json()["data"]
            assert data["up_count"] == 2100
            assert data["limit_up"] == 45

    def t05_flow_north_route():
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.eastmoney.fetch_north", AsyncMock(return_value=_MOCK_NORTH)):
            r = client.get("/api/flow/north")
            assert r.status_code == 200
            data = r.json()["data"]
            assert data["north_net"] == 25.3
            assert data["hk_to_sh"] == 12.0

    def t06_flow_north_history_route():
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.eastmoney.fetch_north_history", AsyncMock(return_value=_MOCK_NORTH_HIST)):
            r = client.get("/api/flow/north/history")
            assert r.status_code == 200
            data = r.json()["data"]
            assert "days" in data
            assert len(data["days"]) == 2
            assert data["cum5d"] == 37.4

    def t07_flow_main_capital_route():
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.eastmoney.fetch_main_capital", AsyncMock(return_value=_MOCK_MAIN_CAP)):
            r = client.get("/api/flow/main-capital")
            assert r.status_code == 200
            data = r.json()["data"]
            assert data["total_yi"] == 30.5
            assert isinstance(data["top3"], list)

    def t08_flow_margin_route():
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.eastmoney.fetch_margin", AsyncMock(return_value=_MOCK_MARGIN)):
            r = client.get("/api/flow/margin")
            assert r.status_code == 200
            data = r.json()["data"]
            assert data["total_balance"] == 16500.2
            assert data["date"] == "2026-06-04"

    def t09_market_limit_stats_route():
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.eastmoney.fetch_limit_stats", AsyncMock(return_value=_MOCK_LIMIT)):
            r = client.get("/api/market/limit-stats")
            assert r.status_code == 200
            data = r.json()["data"]
            assert data["limit_up"] == 45
            assert data["limit_down"] == 12

    def t10_market_turnover_route():
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.eastmoney.fetch_turnover", AsyncMock(return_value=_MOCK_TURNOVER)):
            r = client.get("/api/market/turnover")
            assert r.status_code == 200
            data = r.json()["data"]
            assert data["total"] == 9500.3
            assert data["unit"] == "亿元"

    def t11_quote_idx_intl_route():
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.eastmoney.fetch_intl_idx", AsyncMock(return_value=_MOCK_INTL)):
            r = client.get("/api/quote/idx/intl")
            assert r.status_code == 200
            data = r.json()["data"]
            assert len(data) == 3
            codes = {d["code"] for d in data}
            assert codes == {"HSI", "N225", "KS11"}

    def t12_quote_kline_route():
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.eastmoney.fetch_kline", AsyncMock(return_value=_MOCK_KLINE)):
            r = client.get("/api/quote/kline?secid=1.000001&days=1")
            assert r.status_code == 200
            data = r.json()["data"]
            assert data["secid"] == "1.000001"
            assert isinstance(data["klines"], list)

    def t13_intl_eu_route():
        asyncio.run(_flushdb(redis_mod))
        mock_eu = [{"secid": "100.GDAXI", "code": "GDAXI", "name": "德国DAX", "price": 18000.0, "pct": 0.5, "ts": int(time.time())}]
        with patch("app.services.eastmoney.fetch_eu_idx", AsyncMock(return_value=mock_eu)):
            r = client.get("/api/intl/eu")
            assert r.status_code == 200
            assert r.json()["code"] == "200"

    def t14_intl_commodities_route():
        asyncio.run(_flushdb(redis_mod))
        mock_comm = [{"secid": "102.CL00Y", "code": "CL00Y", "name": "NYMEX原油", "price": 75.0, "pct": -0.3, "ts": int(time.time())}]
        with patch("app.services.eastmoney.fetch_commodities", AsyncMock(return_value=mock_comm)):
            r = client.get("/api/intl/commodities")
            assert r.status_code == 200

    def t15_intl_fx_route():
        asyncio.run(_flushdb(redis_mod))
        mock_fx = [{"secid": "100.UDI", "code": "UDI", "name": "美元指数", "price": 104.5, "pct": 0.1, "ts": int(time.time())}]
        with patch("app.services.eastmoney.fetch_fx", AsyncMock(return_value=mock_fx)):
            r = client.get("/api/intl/fx")
            assert r.status_code == 200

    def t16_intl_macro_route():
        asyncio.run(_flushdb(redis_mod))
        mock_macro = [{"secid": "107.VIXY", "code": "VIXY", "name": "VIXY情绪ETF", "price": 22.5, "pct": 2.3, "ts": int(time.time())}]
        with patch("app.services.eastmoney.fetch_macro", AsyncMock(return_value=mock_macro)):
            r = client.get("/api/intl/macro")
            assert r.status_code == 200

    def t17_search_route():
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.eastmoney.fetch_search", AsyncMock(return_value=_MOCK_SEARCH)):
            r = client.get("/api/search/stock?q=茅台")
            assert r.status_code == 200
            data = r.json()["data"]
            assert len(data) == 1
            assert data[0]["code"] == "sh600519"
            assert data[0]["name"] == "贵州茅台"

    def t18_search_missing_q():
        r = client.get("/api/search/stock")
        assert r.status_code == 422
        assert r.json()["code"] == "422"

    def t19_fund_top_holdings_route():
        mock_data = [
            {"code": "sh600519", "name": "贵州茅台", "fund_count": 680, "total_value": 1250.30},
            {"code": "sh601318", "name": "中国平安", "fund_count": 530, "total_value": 980.10},
            {"code": "sz000858", "name": "五粮液",   "fund_count": 420, "total_value": 760.50},
        ]
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.eastmoney.fetch_top_holdings", AsyncMock(return_value=mock_data)):
            r = client.get("/api/fund/top-holdings")
        assert r.status_code == 200
        data = r.json()["data"]
        assert isinstance(data, list)
        assert len(data) == 3
        item = data[0]
        assert item["code"] == "sh600519"
        assert item["name"] == "贵州茅台"
        assert isinstance(item["fund_count"], int)
        assert isinstance(item["total_value"], float)

    def t20_kline_missing_secid():
        r = client.get("/api/quote/kline")
        assert r.status_code == 422

    def t21_sectors_null_breadth():
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.eastmoney.fetch_market_breadth", AsyncMock(return_value=None)):
            r = client.get("/api/sectors/breadth")
            assert r.status_code == 200
            assert r.json()["data"] is None

    def t22_north_null():
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.eastmoney.fetch_north", AsyncMock(return_value=None)):
            r = client.get("/api/flow/north")
            assert r.status_code == 200
            assert r.json()["data"] is None

    cases = [
        ("01 _pf: None/dash/empty/NaN/Inf → 0", t01_pf_safety),
        ("02 _pf: numeric strings", t02_pf_numeric),
        ("03 GET /api/sectors (mocked)", t03_sectors_route),
        ("04 GET /api/sectors/breadth (mocked)", t04_sectors_breadth_route),
        ("05 GET /api/flow/north (mocked)", t05_flow_north_route),
        ("06 GET /api/flow/north/history (mocked)", t06_flow_north_history_route),
        ("07 GET /api/flow/main-capital (mocked)", t07_flow_main_capital_route),
        ("08 GET /api/flow/margin (mocked)", t08_flow_margin_route),
        ("09 GET /api/market/limit-stats (mocked)", t09_market_limit_stats_route),
        ("10 GET /api/market/turnover (mocked)", t10_market_turnover_route),
        ("11 GET /api/quote/idx/intl (mocked)", t11_quote_idx_intl_route),
        ("12 GET /api/quote/kline (mocked)", t12_quote_kline_route),
        ("13 GET /api/intl/eu (mocked)", t13_intl_eu_route),
        ("14 GET /api/intl/commodities (mocked)", t14_intl_commodities_route),
        ("15 GET /api/intl/fx (mocked)", t15_intl_fx_route),
        ("16 GET /api/intl/macro (mocked)", t16_intl_macro_route),
        ("17 GET /api/search/stock (mocked)", t17_search_route),
        ("18 GET /api/search/stock missing q → 422", t18_search_missing_q),
        ("19 GET /api/fund/top-holdings (mocked)", t19_fund_top_holdings_route),
        ("20 GET /api/quote/kline missing secid → 422", t20_kline_missing_secid),
        ("21 sectors/breadth null → data:null", t21_sectors_null_breadth),
        ("22 flow/north null → data:null", t22_north_null),
    ]

    for name, fn in cases:
        case(name, fn)

    # ──────────────────────────────────────────────────────────────────────
    # Part C: optional live network probe
    # ──────────────────────────────────────────────────────────────────────
    if os.environ.get("GPXX_TEST_NETWORK") == "1":
        print()
        print("=== Live network probe ===")

        def t_live_sectors():
            asyncio.run(_flushdb(redis_mod))
            r = client.get("/api/sectors")
            assert r.status_code == 200
            data = r.json()["data"]
            assert len(data) > 0
            s = data[0]
            assert s.get("name"), "sector name empty"
            print(f"    板块#1: {s['name']} {s['pct']:+.2f}%  主力:{s['main_inflow']/1e8:.1f}亿")

        def t_live_north():
            asyncio.run(_flushdb(redis_mod))
            r = client.get("/api/flow/north")
            assert r.status_code == 200
            data = r.json()["data"]
            if data:
                print(f"    北向: 沪{data['hk_to_sh']:.2f}亿 深{data['hk_to_sz']:.2f}亿 合计{data['north_net']:.2f}亿")
            else:
                print("    北向: 无数据（休市?）")

        def t_live_intl():
            asyncio.run(_flushdb(redis_mod))
            r = client.get("/api/quote/idx/intl")
            assert r.status_code == 200
            data = r.json()["data"]
            for d in data:
                print(f"    {d['name']}: {d['price']} ({d['pct']:+.2f}%)")

        case("L01 GET /api/sectors live", t_live_sectors)
        case("L02 GET /api/flow/north live", t_live_north)
        case("L03 GET /api/quote/idx/intl live", t_live_intl)
    else:
        skipped("L01-L03 live network", "set GPXX_TEST_NETWORK=1 to enable")

    print(f"\n=== {passed} passed, {failed} failed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
