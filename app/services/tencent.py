"""腾讯财经数据抓取（替代前端 src/api/tencent.js）。

来源：http://qt.gtimg.cn/q=sh600519,sz000001,...
返回是 GBK 编码字符串，每行格式：
    v_sh600519="1~贵州茅台~600519~1750.00~1730.20~...~20260515161405~+20.30~1.17~1755~1730~...~1.23~...";

字段索引（严格对照 src/api/tencent.js v1.1 实际语义）：
    [1]  名称
    [3]  现价
    [4]  昨收
    [30] 时间 "yyyyMMddhhmmss"（CST）
    [31] 涨跌额
    [32] 涨跌幅 (%)
    [33] 最高
    [34] 最低
    [36] 换手率 (%)  ← 注意：契约字段名沿用前端 "turnover"，含义是换手率而非成交额

注意：前端没用 volume / open 字段，且这两个索引在腾讯接口里位置不固定，
故后端不返回这两个字段，避免给错值。
"""
from datetime import datetime, timedelta, timezone

import httpx

from app.services.cache import cache
from app.services.calendar import quote_ttl

_TENCENT_BASE = "http://qt.gtimg.cn/q="
_CST = timezone(timedelta(hours=8))


def _pf(v: str) -> float:
    """安全 parseFloat：空串 / NaN / Inf 都返回 0（与前端 utils/market.js 的 pf 一致）。"""
    if not v:
        return 0.0
    try:
        n = float(v)
        if n != n or n == float("inf") or n == float("-inf"):  # NaN / Inf
            return 0.0
        return n
    except (ValueError, TypeError):
        return 0.0


def _parse_ts(raw: str) -> int:
    """腾讯时间戳 '20260515161405' → unix 秒（按 CST 解析）。

    任何异常返回 0。
    """
    if not raw:
        return 0
    s = "".join(c for c in str(raw) if c.isdigit())
    if len(s) < 14:
        return 0
    try:
        dt = datetime.strptime(s[:14], "%Y%m%d%H%M%S").replace(tzinfo=_CST)
        return int(dt.timestamp())
    except ValueError:
        return 0


def _parse_line(line: str) -> dict | None:
    """单行 'v_sh600519="..."' → 业务对象。

    长度不足 / 字段无法解析返回 None（外层过滤掉）。
    """
    line = line.strip()
    if not line or "=" not in line:
        return None

    key_part, val_part = line.split("=", 1)
    val_part = val_part.strip().rstrip(";").strip().strip('"')
    if not val_part:
        return None

    fields = val_part.split("~")
    if len(fields) < 35:  # 至少到 high(33), low(34)
        return None

    code = key_part.strip()
    if code.startswith("v_"):
        code = code[2:]

    price = _pf(fields[3])
    prev_close = _pf(fields[4])

    # 涨跌额：优先 f[31]，缺失时算
    amount_raw = fields[31] if len(fields) > 31 else ""
    amount = _pf(amount_raw) if amount_raw else (price - prev_close)

    # 涨跌幅：优先 f[32]
    pct_raw = fields[32] if len(fields) > 32 else ""
    if pct_raw:
        pct = _pf(pct_raw)
    elif prev_close > 0:
        pct = amount / prev_close * 100
    else:
        pct = 0.0

    high = _pf(fields[33])
    low = _pf(fields[34])

    # 换手率（前端字段名 turnover，语义是换手率%）
    turnover_rate: float | None = None
    if len(fields) > 36 and fields[36]:
        turnover_rate = _pf(fields[36])

    ts = _parse_ts(fields[30]) if len(fields) > 30 else 0

    return {
        "code": code,
        "name": fields[1],
        "price": price,
        "prev_close": prev_close,
        "amount": amount,
        "pct": pct,
        "high": high,
        "low": low,
        "turnover": turnover_rate,  # 换手率 (%) — 字段名沿用前端 parseStock 输出
        "ts": ts,                    # unix 秒（CST 解析）
    }


async def _fetch_raw(codes: tuple[str, ...]) -> str:
    """同步逻辑搬到这里，方便测试时 monkeypatch。

    返回 GBK 解码后的文本。
    """
    query = ",".join(codes)
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{_TENCENT_BASE}{query}")
        r.raise_for_status()
        # 关键：腾讯返回 GBK，errors='replace' 防止个别坏字符炸整批
        return r.content.decode("gbk", errors="replace")


# 单一公开入口：按 codes 批量取
@cache(prefix="quote:batch", ttl=quote_ttl)
async def fetch_batch(codes: tuple[str, ...]) -> list[dict]:
    """codes 必须是 tuple（hashable，参与 cache key 计算）。"""
    if not codes:
        return []
    raw = await _fetch_raw(codes)
    out: list[dict] = []
    for line in raw.split(";"):
        parsed = _parse_line(line)
        if parsed:
            out.append(parsed)
    return out


# 便捷封装：A股主要指数
_CN_IDX = ("sh000001", "sz399001", "sz399006", "sh000300")
# 美股主要指数
_US_IDX = ("usDJI",   "usIXIC",   "usINX")


async def fetch_cn_idx() -> list[dict]:
    return await fetch_batch(_CN_IDX)


async def fetch_us_idx() -> list[dict]:
    return await fetch_batch(_US_IDX)
