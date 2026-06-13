"""D5 腾讯财经接口 端到端验收脚本。

预期 14 项测试 PASS。

Part A: 字段解析 / GBK 解码 / 时间戳（纯单元，用真实样本数据）
Part B: 路由接口（HTTP 层，mock _fetch_raw）
Part C (可选): 真实联网探测，标记为 NETWORK，失败不影响 D5 验收
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fakeredis.aioredis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# 真实样本（截自腾讯接口实际返回，已 GBK 解码为字符串形式）
# 字段索引以前端 src/api/tencent.js 注释为准 — 用 list+join 拼接更稳
def _make_sample(code: str = "sh600519") -> str:
    fields = (
        ["1", "贵州茅台", "600519", "1750.50", "1730.20", "1735.00", "12345", "6789", "5556"]
        + [""] * 21  # fields[9..29] 空
        + [
            "20260515161405",  # [30] time
            "20.30",           # [31] amount
            "1.17",            # [32] pct
            "1755.00",         # [33] high
            "1730.00",         # [34] low
            "",                # [35] reserved
            "1.23",            # [36] turnover rate %
        ]
    )
    return f'v_{code}="' + "~".join(fields) + '";'


_SAMPLE_GUIZHOUMAOTAI = _make_sample("sh600519")


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

    print("=== D5 quote (Tencent Finance) ===\n")

    from app.services.tencent import _parse_line, _parse_ts, _pf, fetch_batch

    # ------------------------------------------------------------
    # Part A: parser unit tests
    # ------------------------------------------------------------
    def t01_pf_safety():
        assert _pf("1.5") == 1.5
        assert _pf("") == 0.0
        assert _pf("not-a-num") == 0.0
        assert _pf("nan") == 0.0
        assert _pf("inf") == 0.0

    def t02_parse_ts_cst():
        # 2026-05-15 16:14:05 CST = 2026-05-15 08:14:05 UTC
        ts = _parse_ts("20260515161405")
        # 期望约等于：datetime(2026,5,15,8,14,5,tzinfo=UTC).timestamp()
        expected = int(datetime(2026, 5, 15, 16, 14, 5, tzinfo=timezone(timedelta(hours=8))).timestamp())
        assert ts == expected, f"ts={ts}, expected={expected}"

    def t03_parse_ts_invalid():
        assert _parse_ts("") == 0
        assert _parse_ts("not-a-time") == 0
        assert _parse_ts("123") == 0
        assert _parse_ts(None) == 0  # type: ignore

    def t04_parse_line_full():
        parsed = _parse_line(_SAMPLE_GUIZHOUMAOTAI)
        assert parsed is not None
        assert parsed["code"] == "sh600519"
        assert parsed["name"] == "贵州茅台"
        assert parsed["price"] == 1750.50
        assert parsed["prev_close"] == 1730.20
        assert parsed["amount"] == 20.30
        assert parsed["pct"] == 1.17
        assert parsed["high"] == 1755.00
        assert parsed["low"] == 1730.00
        assert parsed["turnover"] == 1.23, f"turnover should be 1.23 (换手率%), got {parsed['turnover']}"
        assert parsed["ts"] > 0

    def t05_parse_line_truncated():
        # 字段不足时返回 None
        assert _parse_line('v_sh000001="1~上证~600519";') is None

    def t06_parse_line_garbage():
        assert _parse_line("") is None
        assert _parse_line("garbage no equal sign") is None
        assert _parse_line('v_x="";') is None

    def _make_test_line(code, overrides=None):
        """生成完整 37 字段的 line。overrides: {field_index: value}。"""
        fields = ["1", "A", "", "100.0", "95.0"] + [""] * 25 + ["20260101120000", "", "", "110", "90", "", "0"]
        for idx, val in (overrides or {}).items():
            fields[idx] = val
        return f'v_{code}="' + "~".join(fields) + '";'

    def t07_parse_amount_fallback_when_missing():
        # f[31] 空 → amount = price - prev_close = 5.0
        # f[32] = "5" → pct 用 f[32]
        line = _make_test_line("sh000001", {31: "", 32: "5"})
        p = _parse_line(line)
        assert p is not None
        assert abs(p["amount"] - 5.0) < 0.01, f"amount fallback failed: {p['amount']}"
        assert p["pct"] == 5.0

    def t08_parse_pct_fallback():
        # f[31] = "5", f[32] = "" → pct = 5 / 95 * 100
        line = _make_test_line("sh000001", {31: "5", 32: ""})
        p = _parse_line(line)
        assert p is not None
        assert abs(p["pct"] - 5.263157894736842) < 0.01, f"pct fallback failed: {p['pct']}"

    # ------------------------------------------------------------
    # Part B: route layer with mocked _fetch_raw
    # ------------------------------------------------------------
    async def _fake_fetch_raw(codes):
        # 返回组合的样本数据（每个 code 都用茅台模板）
        return "\n".join(_make_sample(code) for code in codes)

    def t09_route_batch():
        # 清缓存
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.tencent._fetch_raw", _fake_fetch_raw):
            r = client.get("/api/quote/batch?codes=sh600519,sz000001")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["code"] == "200"
            data = body["data"]
            assert isinstance(data, list)
            assert len(data) == 2
            assert data[0]["code"] == "sh600519"
            assert data[1]["code"] == "sz000001"

    def t10_route_idx_cn():
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.tencent._fetch_raw", _fake_fetch_raw):
            r = client.get("/api/quote/idx/cn")
            assert r.status_code == 200
            data = r.json()["data"]
            assert len(data) == 4
            codes = {d["code"] for d in data}
            assert codes == {"sh000001", "sz399001", "sz399006", "sh000300"}

    def t11_route_idx_us():
        asyncio.run(_flushdb(redis_mod))
        with patch("app.services.tencent._fetch_raw", _fake_fetch_raw):
            r = client.get("/api/quote/idx/us")
            data = r.json()["data"]
            codes = {d["code"] for d in data}
            assert codes == {"usDJI", "usIXIC", "usINX"}

    def t12_route_cache_hit():
        """同一参数第二次调用应命中 Redis 缓存（_fetch_raw 只调一次）。"""
        asyncio.run(_flushdb(redis_mod))
        call_count = {"n": 0}

        async def counting_fetch(codes):
            call_count["n"] += 1
            return await _fake_fetch_raw(codes)

        with patch("app.services.tencent._fetch_raw", counting_fetch):
            r1 = client.get("/api/quote/batch?codes=sh600519")
            r2 = client.get("/api/quote/batch?codes=sh600519")
            assert r1.json() == r2.json()
            assert call_count["n"] == 1, f"_fetch_raw called {call_count['n']} times (expected 1)"

    def t13_route_empty_codes():
        r = client.get("/api/quote/batch?codes=")
        # 空 codes：fetch_batch 直接返回 []
        assert r.status_code == 200
        assert r.json()["data"] == []

    def t14_route_codes_missing():
        # 参数 codes 必填，缺失应 422
        r = client.get("/api/quote/batch")
        assert r.status_code == 422
        assert r.json()["code"] == "422"

    cases = [
        ("01 _pf safety: empty/NaN/Inf → 0", t01_pf_safety),
        ("02 _parse_ts: CST yyyyMMddhhmmss → unix sec", t02_parse_ts_cst),
        ("03 _parse_ts: invalid input → 0", t03_parse_ts_invalid),
        ("04 _parse_line: full sample → 9 fields match", t04_parse_line_full),
        ("05 _parse_line: truncated → None", t05_parse_line_truncated),
        ("06 _parse_line: garbage → None", t06_parse_line_garbage),
        ("07 amount fallback: f[31] empty → price-prev_close", t07_parse_amount_fallback_when_missing),
        ("08 pct fallback: f[32] empty → amount/prev*100", t08_parse_pct_fallback),
        ("09 GET /api/quote/batch (mocked)", t09_route_batch),
        ("10 GET /api/quote/idx/cn (4 indices)", t10_route_idx_cn),
        ("11 GET /api/quote/idx/us (3 indices)", t11_route_idx_us),
        ("12 cache hit: _fetch_raw called once for repeat", t12_route_cache_hit),
        ("13 empty codes → []", t13_route_empty_codes),
        ("14 missing codes param → 422 envelope", t14_route_codes_missing),
    ]

    for name, fn in cases:
        case(name, fn)

    # ------------------------------------------------------------
    # Part C: optional live network probe
    # ------------------------------------------------------------
    if os.environ.get("GPXX_TEST_NETWORK") == "1":
        print()
        print("=== Live network probe ===")

        def t_live_cn_idx():
            asyncio.run(_flushdb(redis_mod))
            r = client.get("/api/quote/idx/cn")
            assert r.status_code == 200
            data = r.json()["data"]
            assert len(data) > 0
            sh = next((d for d in data if d["code"] == "sh000001"), None)
            assert sh is not None
            assert sh["name"], "name empty (GBK decode failed?)"
            assert sh["price"] > 0
            print(f"    上证: {sh['name']} {sh['price']} ({sh['pct']:+.2f}%)")

        case("L01 GET /api/quote/idx/cn live", t_live_cn_idx)
    else:
        skipped(
            "L01 GET /api/quote/idx/cn live",
            "set GPXX_TEST_NETWORK=1 to enable",
        )

    print(f"\n=== {passed} passed, {failed} failed ===")
    return 0 if failed == 0 else 1


async def _flushdb(redis_mod):
    r = await redis_mod.get_redis()
    await r.flushdb()


if __name__ == "__main__":
    sys.exit(main())
