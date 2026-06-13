"""TrendRadar 每日热点 DB 查询服务。

TrendRadar 把每日爬取结果写入 output/news/YYYY-MM-DD.db。
本服务通过同步 sqlite3 + asyncio.to_thread 只读查询这些文件。
"""
import asyncio
import sqlite3
from pathlib import Path
from typing import Any

# TrendRadar 输出目录（相对项目根目录）
_TREND_DIR = Path(__file__).resolve().parent.parent.parent / "output" / "news"


# ── 路径工具 ────────────────────────────────────────────────────────────────

def get_db_dates() -> list[str]:
    """返回所有可用日期列表（YYYY-MM-DD），从最新到最旧。"""
    if not _TREND_DIR.exists():
        return []
    files = sorted(_TREND_DIR.glob("*.db"), reverse=True)
    return [f.stem for f in files]


def get_latest_date() -> str | None:
    dates = get_db_dates()
    return dates[0] if dates else None


def get_db_path(date_str: str) -> Path | None:
    p = _TREND_DIR / f"{date_str}.db"
    return p if p.exists() else None


def get_latest_db_path() -> Path | None:
    d = get_latest_date()
    return get_db_path(d) if d else None


# ── 同步查询助手 ─────────────────────────────────────────────────────────────

def _query(db_path: Path, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path), timeout=3.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _query_one(db_path: Path, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    rows = _query(db_path, sql, params)
    return rows[0] if rows else None


# ── 业务查询（async） ─────────────────────────────────────────────────────────

async def fetch_platforms(date_str: str | None = None) -> list[dict]:
    """获取平台列表（按该日数量 DESC）。"""
    db = get_db_path(date_str) if date_str else get_latest_db_path()
    if not db:
        return []

    def _do():
        return _query(db, """
            SELECT p.id, p.name, COUNT(n.id) AS item_count
            FROM platforms p
            LEFT JOIN news_items n ON n.platform_id = p.id
            WHERE p.is_active = 1
            GROUP BY p.id, p.name
            ORDER BY item_count DESC
        """)

    return await asyncio.to_thread(_do)


async def fetch_latest(
    platform_id: str | None = None,
    limit: int = 30,
    date_str: str | None = None,
) -> list[dict]:
    """获取最新热点列表（按 updated_at DESC）。"""
    db = get_db_path(date_str) if date_str else get_latest_db_path()
    if not db:
        return []

    def _do():
        if platform_id:
            return _query(db, """
                SELECT n.id, n.title, n.platform_id, p.name AS platform_name,
                       n.rank, n.url, n.first_crawl_time, n.last_crawl_time,
                       n.crawl_count, n.updated_at
                FROM news_items n
                JOIN platforms p ON p.id = n.platform_id
                WHERE n.platform_id = ?
                ORDER BY n.updated_at DESC
                LIMIT ?
            """, (platform_id, limit))
        else:
            return _query(db, """
                SELECT n.id, n.title, n.platform_id, p.name AS platform_name,
                       n.rank, n.url, n.first_crawl_time, n.last_crawl_time,
                       n.crawl_count, n.updated_at
                FROM news_items n
                JOIN platforms p ON p.id = n.platform_id
                ORDER BY n.updated_at DESC
                LIMIT ?
            """, (limit,))

    return await asyncio.to_thread(_do)


async def fetch_search(q: str, limit: int = 50, days: int = 3) -> list[dict]:
    """全文搜索（LIKE 匹配），搜最近 days 天的 DB。"""
    dates = get_db_dates()[:days]
    results: list[dict] = []

    async def search_one(date_str: str):
        db = get_db_path(date_str)
        if not db:
            return []

        def _do():
            return _query(db, """
                SELECT n.id, n.title, n.platform_id, p.name AS platform_name,
                       n.rank, n.url, n.updated_at, ? AS news_date
                FROM news_items n
                JOIN platforms p ON p.id = n.platform_id
                WHERE n.title LIKE ?
                ORDER BY n.updated_at DESC
                LIMIT ?
            """, (date_str, f"%{q}%", limit))

        return await asyncio.to_thread(_do)

    task_results = await asyncio.gather(*[search_one(d) for d in dates])
    for rows in task_results:
        results.extend(rows)

    # 按时间降序，去重（同一条新闻可能出现在多天的 DB 里）
    seen_titles: set[str] = set()
    deduped: list[dict] = []
    for r in sorted(results, key=lambda x: x.get("updated_at") or "", reverse=True):
        key = f"{r['platform_id']}:{r['title']}"
        if key not in seen_titles:
            seen_titles.add(key)
            deduped.append(r)
        if len(deduped) >= limit:
            break
    return deduped


async def fetch_rank_history(news_id: int, date_str: str | None = None) -> list[dict]:
    """获取指定新闻的排名历史（最多 200 点）。"""
    db = get_db_path(date_str) if date_str else get_latest_db_path()
    if not db:
        return []

    def _do():
        return _query(db, """
            SELECT rank, crawl_time, created_at
            FROM rank_history
            WHERE news_item_id = ?
            ORDER BY created_at ASC
            LIMIT 200
        """, (news_id,))

    return await asyncio.to_thread(_do)


async def fetch_news_item(news_id: int, date_str: str | None = None) -> dict | None:
    """获取单条新闻（用于收藏时缓存 title/url/platform_id）。"""
    db = get_db_path(date_str) if date_str else get_latest_db_path()
    if not db:
        return None

    def _do():
        return _query_one(db, """
            SELECT n.id, n.title, n.platform_id, n.url
            FROM news_items n
            WHERE n.id = ?
        """, (news_id,))

    return await asyncio.to_thread(_do)
