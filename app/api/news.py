"""新闻接口（含 TrendRadar 子路由） — D9 / D15-D17 实现。

端点参见 GPXX-V3-接口契约.md §3。
"""
from fastapi import APIRouter, HTTPException, Path, Query
from sqlalchemy import select, delete

from app.core.envelope import ok
from app.deps import CurrentUser, DbDep
from app.models.favorite import UserFavoriteNews
from app.services import sina, trend

router = APIRouter()


# ── 新浪新闻（D9） ────────────────────────────────────────────────────────────

@router.get("/sina")
async def news_sina(
    num: int = Query(default=50, ge=1, le=100, description="返回条数"),
):
    """新浪财经滚动新闻（lid=2516）。"""
    return ok(await sina.fetch_sina_news(num))


# ── TrendRadar 热点（D15-D17） ─────────────────────────────────────────────────

@router.get("/trend/platforms")
async def trend_platforms(
    date: str | None = Query(default=None, description="日期 YYYY-MM-DD，默认最新"),
):
    """平台列表（按该日数据量 DESC）。"""
    return ok(await trend.fetch_platforms(date))


@router.get("/trend/latest")
async def trend_latest(
    platform: str | None = Query(default=None, description="平台 ID，如 cls-hot"),
    limit: int = Query(default=30, ge=1, le=200),
    date: str | None = Query(default=None, description="日期 YYYY-MM-DD，默认最新"),
):
    """最新热点列表（按 updated_at DESC）。"""
    return ok(await trend.fetch_latest(platform, limit, date))


@router.get("/trend/search")
async def trend_search(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
):
    """热点标题全文搜索（最近 3 天）。"""
    if not q.strip():
        return ok([])
    return ok(await trend.fetch_search(q.strip(), limit))


@router.get("/trend/{news_id}/rank-history")
async def trend_rank_history(
    news_id: int = Path(..., description="news_items.id"),
    date: str | None = Query(default=None, description="日期 YYYY-MM-DD，默认最新"),
):
    """指定新闻的排名趋势（最多 200 点）。"""
    return ok(await trend.fetch_rank_history(news_id, date))


# ── 收藏（D17） ────────────────────────────────────────────────────────────────

@router.post("/trend/{news_id}/favorite")
async def add_favorite(
    news_id: int = Path(...),
    date: str | None = Query(default=None, description="日期 YYYY-MM-DD，默认最新"),
    user: CurrentUser = None,
    db: DbDep = None,
):
    """收藏热点（幂等）。"""
    date_str = date or trend.get_latest_date()
    if not date_str:
        raise HTTPException(status_code=503, detail="暂无热点数据")

    # 从 trend DB 读取元数据（缓存到 favorite 行）
    item = await trend.fetch_news_item(news_id, date_str)
    if not item:
        raise HTTPException(status_code=404, detail="新闻不存在")

    # 幂等 upsert
    res = await db.execute(
        select(UserFavoriteNews).where(
            UserFavoriteNews.user_id == user.id,
            UserFavoriteNews.news_item_id == news_id,
            UserFavoriteNews.news_date == date_str,
        )
    )
    existing = res.scalar_one_or_none()
    if not existing:
        db.add(UserFavoriteNews(
            user_id=user.id,
            news_item_id=news_id,
            news_date=date_str,
            title=item.get("title"),
            url=item.get("url"),
            platform_id=item.get("platform_id"),
        ))
        await db.commit()
    return ok({"ok": True})


@router.delete("/trend/{news_id}/favorite")
async def remove_favorite(
    news_id: int = Path(...),
    date: str | None = Query(default=None),
    user: CurrentUser = None,
    db: DbDep = None,
):
    """取消收藏。"""
    date_str = date or trend.get_latest_date()
    if not date_str:
        raise HTTPException(status_code=503, detail="暂无热点数据")

    await db.execute(
        delete(UserFavoriteNews).where(
            UserFavoriteNews.user_id == user.id,
            UserFavoriteNews.news_item_id == news_id,
            UserFavoriteNews.news_date == date_str,
        )
    )
    await db.commit()
    return ok({"ok": True})


@router.get("/trend/favorites")
async def get_favorites(user: CurrentUser, db: DbDep):
    """获取收藏列表（最近 200 条）。"""
    res = await db.execute(
        select(UserFavoriteNews)
        .where(UserFavoriteNews.user_id == user.id)
        .order_by(UserFavoriteNews.created_at.desc())
        .limit(200)
    )
    rows = res.scalars().all()
    return ok([
        {
            "news_item_id": r.news_item_id,
            "news_date": r.news_date,
            "title": r.title,
            "url": r.url,
            "platform_id": r.platform_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ])
