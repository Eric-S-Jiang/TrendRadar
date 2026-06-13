"""东方财富数据抓取服务。

对照 GPXX-V3-接口契约.md §2 及 src/api/eastmoney.js / src/utils/constants.js。

API 实际域名（Vite proxy 解析）：
    push2     → https://push2.eastmoney.com
    push2his  → https://push2his.eastmoney.com
    em-data   → https://datacenter-web.eastmoney.com
    emsearch  → https://searchapi.eastmoney.com
"""
import asyncio
import time

import httpx

from app.services.cache import cache
from app.services.calendar import quote_ttl

_PUSH2 = "https://push2.eastmoney.com"
_PUSH2HIS = "https://push2his.eastmoney.com"
_EM_DATA = "https://datacenter-web.eastmoney.com"
_EMSEARCH = "https://searchapi.eastmoney.com"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HDR_PUSH2 = {"Referer": "https://www.eastmoney.com/", "User-Agent": _UA}
_HDR_DATA = {"Referer": "https://data.eastmoney.com/", "User-Agent": _UA}


def _pf(v) -> float:
    """安全 parseFloat（与前端 utils/market.js pf 行为一致）。"""
    if v is None or v == "-" or v == "":
        return 0.0
    try:
        n = float(v)
        if n != n or n == float("inf") or n == float("-inf"):
            return 0.0
        return n
    except (ValueError, TypeError):
        return 0.0


def _safe_pct(v) -> float:
    """涨跌幅安全解析：过滤 unix 时间戳等异常大值（|v| >= 100 视为无效）。"""
    n = _pf(v)
    return n if abs(n) < 100 else 0.0


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

async def _get_push2(path: str, **params) -> dict:
    async with httpx.AsyncClient(timeout=10.0, headers=_HDR_PUSH2) as c:
        r = await c.get(f"{_PUSH2}{path}", params=params)
        r.raise_for_status()
        return r.json()


async def _get_push2his(path: str, **params) -> dict:
    async with httpx.AsyncClient(timeout=10.0, headers=_HDR_PUSH2) as c:
        r = await c.get(f"{_PUSH2HIS}{path}", params=params)
        r.raise_for_status()
        return r.json()


async def _get_em_data(**params) -> dict:
    async with httpx.AsyncClient(timeout=10.0, headers=_HDR_DATA) as c:
        r = await c.get(f"{_EM_DATA}/api/data/v1/get", params=params)
        r.raise_for_status()
        return r.json()


# ─── Sectors ─────────────────────────────────────────────────────────────────

@cache(prefix="sectors:list", ttl=quote_ttl)
async def fetch_sectors() -> list[dict]:
    """行业板块涨跌（前 18 个，按涨幅排序）。

    字段：f2=价, f3=涨跌幅, f4=涨跌额, f12=代码, f14=名称,
           f62=主力净流入, f104=上涨家数, f105=下跌家数,
           f124=3日涨幅, f125=5日涨幅
    """
    d = await _get_push2(
        "/api/qt/clist/get",
        pn=1, pz=20, po=1, np=1,
        ut="bd1d9ddb04089700cf9c27f6f7426281",
        fltt=2, invt=2, fid="f3",
        fs="m:90+t:2+f:!50",
        fields="f2,f3,f4,f12,f14,f62,f104,f105,f124,f125",
    )
    rows = ((d.get("data") or {}).get("diff")) or []
    out = []
    for s in rows[:18]:
        out.append({
            "code": str(s.get("f12") or ""),
            "name": str(s.get("f14") or ""),
            "price": _pf(s.get("f2")),
            "pct": _pf(s.get("f3")),
            "change": _pf(s.get("f4")),
            "pct3d": _safe_pct(s.get("f124")),
            "pct5d": _safe_pct(s.get("f125")),
            "up_count": int(s.get("f104") or 0),
            "down_count": int(s.get("f105") or 0),
            "main_inflow": _pf(s.get("f62")),
            "leader": None,
            "leader_pct": None,
        })
    return out


@cache(prefix="sectors:breadth", ttl=quote_ttl)
async def fetch_market_breadth() -> dict | None:
    """市场宽度：全行业上涨/下跌家数 + 涨跌停统计。

    内部并发两个 Eastmoney clist 请求合并结果。
    """
    breadth_coro = _get_push2(
        "/api/qt/clist/get",
        pn=1, pz=120, po=1, np=1,
        ut="bd1d9ddb04089700cf9c27f6f7426281",
        fltt=2, invt=2, fid="f3",
        fs="m:90+t:2+f:!50",
        fields="f104,f105",
    )
    limit_coro = _get_push2(
        "/api/qt/clist/get",
        pn=1, pz=100, po=1,
        fid="f3",
        fs="m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2",
        fields="f12,f3",
        ut="bd1d9ddb04089700cf9c27f6f7426281",
    )
    bd, ld = await asyncio.gather(breadth_coro, limit_coro, return_exceptions=True)

    up = down = 0
    if not isinstance(bd, Exception):
        rows = ((bd.get("data") or {}).get("diff")) or []
        up = sum(int(x.get("f104") or 0) for x in rows)
        down = sum(int(x.get("f105") or 0) for x in rows)

    limit_up = limit_down = 0
    if not isinstance(ld, Exception):
        rows = ((ld.get("data") or {}).get("diff")) or []
        limit_up = sum(1 for x in rows if _pf(x.get("f3")) >= 9.5)
        limit_down = sum(1 for x in rows if _pf(x.get("f3")) <= -9.5)

    if not up and not down:
        return None
    return {
        "up_count": up,
        "down_count": down,
        "flat_count": None,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "ts": int(time.time()),
    }


# ─── Flow ─────────────────────────────────────────────────────────────────────

@cache(prefix="flow:north", ttl=quote_ttl)
async def fetch_north() -> dict | None:
    """北向 / 南向资金当日净流入（亿元）。

    API 原始单位万元，除以 10000 转亿元。
    """
    d = await _get_push2(
        "/api/qt/kamt/get",
        fields1="f1,f2,f3,f4,f5",
        fields2="f51,f52,f53,f54,f55,f56",
        ut="b2884a393a59ad64002292a3e90d46a5",
    )
    data = d.get("data") or {}
    if not data:
        return None

    def _amt(obj, key="dayNetAmtIn") -> float:
        return _pf((obj or {}).get(key)) / 10000

    hk_to_sh = _amt(data.get("hk2sh"))
    hk_to_sz = _amt(data.get("hk2sz"))
    sh_to_hk = _amt(data.get("sh2hk"))
    sz_to_hk = _amt(data.get("sz2hk"))

    return {
        "north_net": round(hk_to_sh + hk_to_sz, 4),
        "south_net": round(sh_to_hk + sz_to_hk, 4),
        "hk_to_sh": round(hk_to_sh, 4),
        "hk_to_sz": round(hk_to_sz, 4),
        "sh_to_hk": round(sh_to_hk, 4),
        "sz_to_hk": round(sz_to_hk, 4),
        "ts": int(time.time()),
    }


@cache(prefix="flow:north:history", ttl=300)
async def fetch_north_history() -> dict | None:
    """近 5 日北向资金日净流入历史。

    API 返回 CSV 行 "YYYY-MM-DD,金额"，沪深合并后取最近 5 日。
    """
    d = await _get_push2his(
        "/api/qt/kamt.kline/get",
        fields1="f1,f3,f5",
        fields2="f51,f52",
        klt=101, lmt=10,
        ut="b2884a393a59ad64002292a3e90d46a5",
    )
    data = d.get("data") or {}
    sh_lines: list = data.get("hk2sh") or []
    sz_lines: list = data.get("hk2sz") or []
    if not sh_lines and not sz_lines:
        return None

    day_map: dict = {}
    for line in sh_lines:
        parts = (line or "").split(",")
        if len(parts) >= 2 and parts[0]:
            day_map[parts[0]] = {"date": parts[0], "sh": _pf(parts[1]), "sz": 0.0}
    for line in sz_lines:
        parts = (line or "").split(",")
        if len(parts) >= 2 and parts[0]:
            item = day_map.setdefault(parts[0], {"date": parts[0], "sh": 0.0, "sz": 0.0})
            item["sz"] = _pf(parts[1])

    parsed = sorted(day_map.values(), key=lambda x: x["date"])[-5:]
    days = [{"date": x["date"], "net": round(x["sh"] + x["sz"], 4)} for x in parsed]
    return {"days": days, "cum5d": round(sum(x["net"] for x in days), 4)}


@cache(prefix="flow:main", ttl=quote_ttl)
async def fetch_main_capital() -> dict | None:
    """主力资金：汇总全行业板块 f62（主力净流入，单位元）转亿元。"""
    d = await _get_push2(
        "/api/qt/clist/get",
        pn=1, pz=120, po=1, np=1,
        ut="bd1d9ddb04089700cf9c27f6f7426281",
        fltt=2, invt=2, fid="f3",
        fs="m:90+t:2+f:!50",
        fields="f14,f62",
    )
    rows = ((d.get("data") or {}).get("diff")) or []
    if not rows:
        return None

    amounts = [_pf(x.get("f62")) for x in rows]
    total = sum(amounts)
    inflow = sum(a for a in amounts if a > 0)
    outflow = sum(a for a in amounts if a < 0)
    top3 = [
        {"name": str(rows[i].get("f14") or ""), "amt_yi": round(_pf(rows[i].get("f62")) / 1e8, 4)}
        for i in range(min(3, len(rows)))
    ]
    return {
        "total_yi": round(total / 1e8, 4),
        "inflow_yi": round(inflow / 1e8, 4),
        "outflow_yi": round(outflow / 1e8, 4),
        "top3": top3,
        "ts": int(time.time()),
    }


@cache(prefix="flow:margin", ttl=1800)
async def fetch_margin() -> dict | None:
    """两融余额（东财 datacenter-web API，非实时，30 分钟缓存）。

    API 原始单位：元，转亿元时除以 1e8。
    """
    d = await _get_em_data(
        reportName="RPTA_RZRQ_LSHJ",
        columns="DIM_DATE,RZRQYE,RZYE,RQYE,RZJME",
        pageSize=90,
        sortColumns="DIM_DATE",
        sortTypes=-1,
        source="WEB",
        client="WEB",
    )
    rows = ((d.get("result") or {}).get("data")) or []
    if not rows:
        return None

    to_yi = lambda v: round(_pf(v) / 1e8, 2)
    r0 = rows[0]
    return {
        "total_balance": to_yi(r0.get("RZRQYE")),
        "financing_balance": to_yi(r0.get("RZYE")),
        "securities_balance": to_yi(r0.get("RQYE")),
        "day_change": to_yi(r0.get("RZJME")),
        "date": (str(r0.get("DIM_DATE") or ""))[:10],
    }


# ─── Market stats ─────────────────────────────────────────────────────────────

@cache(prefix="market:limit", ttl=quote_ttl)
async def fetch_limit_stats() -> dict | None:
    """涨跌停统计：沪深主板 + 创业板 + 科创板涨停 / 跌停家数。"""
    d = await _get_push2(
        "/api/qt/clist/get",
        pn=1, pz=100, po=1,
        fid="f3",
        fs="m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2",
        fields="f12,f3",
        ut="bd1d9ddb04089700cf9c27f6f7426281",
    )
    rows = ((d.get("data") or {}).get("diff")) or []
    limit_up = sum(1 for x in rows if _pf(x.get("f3")) >= 9.5)
    limit_down = sum(1 for x in rows if _pf(x.get("f3")) <= -9.5)
    return {
        "limit_up": limit_up,
        "limit_down": limit_down,
        "natural_limit_up": None,
        "broken_limit_up": None,
        "ts": int(time.time()),
    }


@cache(prefix="market:turnover", ttl=quote_ttl)
async def fetch_turnover() -> dict | None:
    """两市成交额（亿元），从上证 / 深证指数的 f6 字段提取。"""
    d = await _get_push2(
        "/api/qt/ulist.np/get",
        secids="1.000001,0.399001",
        fields="f6,f12",
        fltt=2, invt=2,
    )
    rows = ((d.get("data") or {}).get("diff")) or []
    if not rows:
        return None

    total = sum(_pf(x.get("f6")) for x in rows)
    if not total:
        return None

    sh_row = next((x for x in rows if str(x.get("f12")) == "000001"), None)
    sz_row = next((x for x in rows if str(x.get("f12")) == "399001"), None)
    sh = _pf(sh_row.get("f6")) if sh_row else 0.0
    sz = _pf(sz_row.get("f6")) if sz_row else 0.0

    return {
        "total": round(total / 1e8, 2),
        "sh": round(sh / 1e8, 2),
        "sz": round(sz / 1e8, 2),
        "unit": "亿元",
        "ts": int(time.time()),
    }


# ─── International / global ───────────────────────────────────────────────────

async def _fetch_ulist(secids: tuple[str, ...]) -> list[dict]:
    """通用 ulist 行情（双 key 匹配：优先 f13.f12 完整 secid，回退 f12）。

    对照 src/api/eastmoney.js fetchUlist()。
    字段：f2=最新价, f3=涨跌幅, f12=代码, f13=市场号, f14=名称
    """
    d = await _get_push2(
        "/api/qt/ulist.np/get",
        secids=",".join(secids),
        fields="f2,f3,f12,f13,f14",
        fltt=2, invt=2,
    )
    rows = ((d.get("data") or {}).get("diff")) or []
    by_full: dict = {}
    by_code: dict = {}
    for s in rows:
        code = str(s.get("f12") or "")
        mkt = s.get("f13")
        if mkt is not None:
            by_full[f"{mkt}.{code}"] = s
        if code:
            by_code[code] = s

    result = []
    for secid in secids:
        code_part = secid.split(".")[-1]
        s = by_full.get(secid) or by_code.get(code_part)
        price = _pf(s.get("f2")) if s else 0.0
        pct = _pf(s.get("f3")) if s else 0.0
        name = str((s.get("f14") or "")) if s else ""
        result.append({
            "secid": secid,
            "code": code_part,
            "name": name,
            "price": price,
            "pct": pct,
            "ts": int(time.time()),
        })
    return result


_INTL_SECIDS = ("100.HSI", "100.N225", "100.KS11")
_EU_SECIDS = ("100.GDAXI", "100.FTSE", "100.FCHI")
_COMMODITY_SECIDS = ("102.CL00Y", "101.GC00Y", "113.CUM")
_FX_SECIDS = ("100.UDI", "133.USDCNH")
_MACRO_SECIDS = ("107.VIXY", "103.TY00Y")


@cache(prefix="intl:idx", ttl=quote_ttl)
async def fetch_intl_idx() -> list[dict]:
    """港/日/韩指数（恒生 / 日经225 / 韩综）。"""
    return await _fetch_ulist(_INTL_SECIDS)


@cache(prefix="intl:eu", ttl=quote_ttl)
async def fetch_eu_idx() -> list[dict]:
    """欧洲指数（DAX / 富时100 / CAC40）。"""
    return await _fetch_ulist(_EU_SECIDS)


@cache(prefix="intl:commodities", ttl=quote_ttl)
async def fetch_commodities() -> list[dict]:
    """大宗商品（NYMEX原油 / COMEX黄金 / 沪铜）。"""
    return await _fetch_ulist(_COMMODITY_SECIDS)


@cache(prefix="intl:fx", ttl=quote_ttl)
async def fetch_fx() -> list[dict]:
    """汇率（美元指数 / 离岸人民币）。"""
    return await _fetch_ulist(_FX_SECIDS)


@cache(prefix="intl:macro", ttl=quote_ttl)
async def fetch_macro() -> list[dict]:
    """宏观指标（VIXY情绪ETF / 10Y美债期货）。"""
    return await _fetch_ulist(_MACRO_SECIDS)


# ─── Kline ────────────────────────────────────────────────────────────────────

@cache(prefix="kline", ttl=300)
async def fetch_kline(secid: str, period: int = 101, days: int = 20) -> dict | None:
    """历史 K 线（push2his，用于波动率计算等）。

    Args:
        secid:  东财格式，如 "1.000001"（沪市）/ "0.399001"（深市）
        period: 101=日线 / 102=周线 / 103=月线
        days:   返回条数，1-365
    """
    d = await _get_push2his(
        "/api/qt/stock/kline/get",
        secid=secid,
        klt=period,
        fqt=0,
        lmt=days,
        fields1="f1,f2,f3,f4,f5,f6",
        fields2="f51,f52,f53,f54,f55,f56,f57,f58",
    )
    data = d.get("data") or {}
    klines = data.get("klines") or []
    return {
        "secid": secid,
        "code": str(data.get("code") or ""),
        "name": str(data.get("name") or ""),
        "klines": klines,
    }


# ─── Fund top-holdings ────────────────────────────────────────────────────────

@cache(prefix="fund:top", ttl=21600)
async def fetch_top_holdings(limit: int = 100) -> list[dict]:
    """公募基金重仓股 TOP（东财 datacenter RPT_PUBLICFUND_MAIN_HOLD_NEW）。

    数据按季度披露，API 每日更新，缓存 6 小时。
    返回字段：code（含 sh/sz 前缀）、name、fund_count（持仓基金数）、
              total_value（持仓总市值，亿元）。
    """
    d = await _get_em_data(
        reportName="RPT_PUBLICFUND_MAIN_HOLD_NEW",
        columns="SCODE,SNAME,FUND_COUNT,TOTAL_SHARES,TOTAL_MARKET_CAP,CHANGE_SHARES",
        pageSize=limit,
        sortColumns="FUND_COUNT",
        sortTypes=-1,
        source="WEB",
        client="WEB",
    )
    rows = ((d.get("result") or {}).get("data")) or []
    result = []
    for r in rows:
        code_raw = str(r.get("SCODE") or "")
        if code_raw.startswith(("6", "9")):
            prefix = "sh"
        elif code_raw.startswith(("0", "2", "3")):
            prefix = "sz"
        else:
            prefix = ""
        result.append({
            "code": f"{prefix}{code_raw}" if prefix else code_raw,
            "name": str(r.get("SNAME") or ""),
            "fund_count": int(r.get("FUND_COUNT") or 0),
            "total_value": _pf(r.get("TOTAL_MARKET_CAP")),
        })
    return result


# ─── Search ───────────────────────────────────────────────────────────────────

async def fetch_search(q: str) -> list[dict]:
    """东财股票搜索（emsearch API）。

    返回 [{ code, name, market, match_type }]，
    MktNum 1=上交所(sh) / 0=深交所(sz)，其余为 intl。
    """
    async with httpx.AsyncClient(timeout=3.0) as c:
        r = await c.get(
            f"{_EMSEARCH}/api/suggest/get",
            params={"input": q, "type": 14, "token": "D43BF722C8E33BFE0923"},
        )
        r.raise_for_status()
        data = r.json()

    rows = ((data.get("QuotationCodeTable") or {}).get("Data")) or []
    result = []
    for row in rows:
        code_raw = str(row.get("Code") or "")
        mkt_num = str(row.get("MktNum") or "")
        name = str(row.get("Name") or "")
        prefix = "sh" if mkt_num == "1" else ("sz" if mkt_num == "0" else "")
        code = f"{prefix}{code_raw}" if prefix else code_raw
        result.append({
            "code": code,
            "name": name,
            "market": "cn" if prefix in ("sh", "sz") else "intl",
            "match_type": "name",
        })
    return result
