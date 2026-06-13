"""用户业务数据 — D14 实现。

端点参见 GPXX-V3-接口契约.md §5。
"""
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select, delete

from app.core.envelope import ok
from app.deps import CurrentUser, DbDep
from app.models.watchlist import UserWatchlist
from app.models.feedback import UserFeedback

router = APIRouter()


# ── Schema ──────────────────────────────────────────────────────────────────

class WatchItem(BaseModel):
    code: str
    name: str
    market: str = "cn"
    note: str | None = None


class FeedbackIn(BaseModel):
    target_type: str   # ai_analysis | watch | topic | sector | news
    target_id: str
    rating: int        # 1=赞 / -1=踩 / 0=取消
    comment: str | None = None


class LegacyWatchItem(BaseModel):
    code: str
    name: str
    market: str = "cn"


class LegacyFeedbackItem(BaseModel):
    date: str
    type: str
    id: str
    feedback: str   # 'correct' | 'wrong'


class LegacyImportBody(BaseModel):
    watchlist: list[LegacyWatchItem] = []
    feedback: list[LegacyFeedbackItem] = []
    density: str | None = None


# ── 自选股 ────────────────────────────────────────────────────────────────────

@router.get("/watchlist")
async def get_watchlist(user: CurrentUser, db: DbDep):
    """获取自选股列表，按 sort_order ASC。"""
    res = await db.execute(
        select(UserWatchlist)
        .where(UserWatchlist.user_id == user.id)
        .order_by(UserWatchlist.sort_order.asc())
    )
    rows = res.scalars().all()
    return ok([
        {"code": r.code, "name": r.name, "market": r.market, "note": r.note}
        for r in rows
    ])


@router.put("/watchlist")
async def put_watchlist(body: list[WatchItem], user: CurrentUser, db: DbDep):
    """全量替换自选股（先删后插）。"""
    await db.execute(delete(UserWatchlist).where(UserWatchlist.user_id == user.id))
    for i, item in enumerate(body):
        db.add(UserWatchlist(
            user_id=user.id,
            code=item.code,
            name=item.name,
            market=item.market,
            note=item.note,
            sort_order=i,
        ))
    await db.commit()
    return ok({"ok": True, "count": len(body)})


# ── 反馈 ─────────────────────────────────────────────────────────────────────

@router.post("/feedback")
async def post_feedback(body: FeedbackIn, user: CurrentUser, db: DbDep):
    """提交反馈（upsert）。rating=0 则删除。"""
    res = await db.execute(
        select(UserFeedback).where(
            UserFeedback.user_id == user.id,
            UserFeedback.target_type == body.target_type,
            UserFeedback.target_id == body.target_id,
        )
    )
    row = res.scalar_one_or_none()
    if body.rating == 0:
        if row:
            await db.delete(row)
    elif row:
        row.rating = body.rating
        row.comment = body.comment
    else:
        db.add(UserFeedback(
            user_id=user.id,
            target_type=body.target_type,
            target_id=body.target_id,
            rating=body.rating,
            comment=body.comment,
        ))
    await db.commit()
    return ok({"ok": True})


@router.get("/feedback")
async def get_feedback(user: CurrentUser, db: DbDep):
    """获取反馈列表（最近 200 条）。"""
    res = await db.execute(
        select(UserFeedback)
        .where(UserFeedback.user_id == user.id)
        .order_by(UserFeedback.created_at.desc())
        .limit(200)
    )
    rows = res.scalars().all()
    return ok([
        {
            "target_type": r.target_type,
            "target_id": r.target_id,
            "rating": r.rating,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ])


# ── legacy-import ─────────────────────────────────────────────────────────────

@router.post("/legacy-import")
async def legacy_import(body: LegacyImportBody, user: CurrentUser, db: DbDep):
    """从旧前端 localStorage 导入数据（幂等，只执行一次）。"""
    if user.legacy_imported:
        return ok({"ok": True, "skipped": True, "reason": "already imported"})

    # 导入自选股（与现有合并，code 去重）
    existing = await db.execute(
        select(UserWatchlist.code).where(UserWatchlist.user_id == user.id)
    )
    existing_codes = {r[0] for r in existing}

    max_order_result = await db.scalar(
        select(UserWatchlist.sort_order)
        .where(UserWatchlist.user_id == user.id)
        .order_by(UserWatchlist.sort_order.desc())
        .limit(1)
    )
    max_order = max_order_result if max_order_result is not None else -1

    wl_count = 0
    for i, item in enumerate(body.watchlist):
        if item.code not in existing_codes:
            db.add(UserWatchlist(
                user_id=user.id,
                code=item.code,
                name=item.name,
                market=item.market,
                sort_order=max_order + i + 1,
            ))
            wl_count += 1

    # 导入反馈（correct→1, wrong→-1，其余跳过）
    rating_map = {"correct": 1, "wrong": -1}
    fb_count = 0
    for fb in body.feedback:
        rating = rating_map.get(fb.feedback, 0)
        if rating == 0:
            continue
        db.add(UserFeedback(
            user_id=user.id,
            target_type=fb.type,
            target_id=f"{fb.date}_{fb.id}",
            rating=rating,
        ))
        fb_count += 1

    if body.density:
        user.density = body.density

    user.legacy_imported = 1
    await db.commit()
    return ok({
        "ok": True,
        "imported": {
            "watchlist": wl_count,
            "feedback": fb_count,
            "density": bool(body.density),
        },
    })
