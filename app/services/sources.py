"""外部数据源可达性探测（健康检查用）。

仅在 /api/health/sources 触发，结果缓存 5min。
不阻塞健康检查整体流程：任何单源失败都返回 ok:false，不抛异常。
"""
import asyncio
import time
from datetime import datetime, timezone

import httpx

# (name, url, method) — method 选 GET 因为部分服务不支持 HEAD
_PROBES = (
    ("tencent",   "http://qt.gtimg.cn/q=sh000001",                                       "GET"),
    ("eastmoney", "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=1&fid=f3&fs=m:1+t:2", "GET"),
    ("sina",      "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2510&num=1", "GET"),
)


async def _probe_one(client: httpx.AsyncClient, name: str, url: str, method: str) -> dict:
    start = time.monotonic()
    try:
        r = await client.request(method, url)
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "ok": r.status_code < 500,
            "status": r.status_code,
            "latency_ms": latency_ms,
        }
    except Exception as e:
        return {
            "ok": False,
            "status": None,
            "latency_ms": int((time.monotonic() - start) * 1000),
            "error": type(e).__name__,
        }


async def probe_sources() -> dict:
    """并发探测全部源，返回汇总。"""
    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
        results = await asyncio.gather(
            *(_probe_one(client, name, url, method) for name, url, method in _PROBES),
            return_exceptions=False,
        )
    return {
        name: result
        for (name, _, _), result in zip(_PROBES, results)
    } | {
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
