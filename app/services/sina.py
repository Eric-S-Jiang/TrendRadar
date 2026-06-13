"""新浪财经新闻抓取服务。

API: https://feed.mix.sina.com.cn/api/roll/get
Referer: https://finance.sina.com.cn/
lid=2516 → 财经滚动新闻
"""
import random
from datetime import datetime

import httpx

from app.services.cache import cache

_SINA_URL = "https://feed.mix.sina.com.cn"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "Referer": "https://finance.sina.com.cn/",
    "User-Agent": _UA,
}


def _parse_ctime(ctime_str: str) -> int:
    """'YYYY-MM-DD HH:MM:SS' → Unix timestamp, fallback 0."""
    try:
        return int(datetime.strptime(str(ctime_str), "%Y-%m-%d %H:%M:%S").timestamp())
    except (ValueError, TypeError):
        return 0


@cache(prefix="news:sina", ttl=120)
async def fetch_sina_news(num: int = 50) -> list[dict]:
    """新浪财经滚动新闻（lid=2516）。"""
    params = {
        "pagetype": "06",
        "lid": "2516",
        "num": str(num),
        "page": "1",
        "r": str(random.random()),
    }
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(
            f"{_SINA_URL}/api/roll/get",
            params=params,
            headers=_HEADERS,
        )
        r.raise_for_status()
        data = r.json()

    rows = ((data.get("result") or {}).get("data")) or []
    result = []
    for item in rows:
        ctime_raw = str(item.get("ctime") or "")
        result.append({
            "id": str(item.get("id") or ""),
            "title": str(item.get("title") or "").strip(),
            "url": str(item.get("url") or ""),
            "ctime": _parse_ctime(ctime_raw),
            "ctime_str": ctime_raw[:16],
            "source": str(item.get("media_name") or ""),
            "intro": str(item.get("intro") or "").strip(),
        })
    return result
