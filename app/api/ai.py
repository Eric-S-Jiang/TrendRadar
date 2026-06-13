"""AI 接口 — D10-D11 实现。

端点参见 GPXX-V3-接口契约.md §4。
"""
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy import select

from app.core.envelope import ok
from app.deps import CurrentUser, DbDep, RedisDep
from app.models.ai_cache import AiAnalysisCache, UserAiHistory
from app.services import deepseek
from app.config import get_settings

router = APIRouter()
settings = get_settings()

# 缓存有效期：8 小时（同一天内复用同一份分析结果）
_CACHE_TTL_H = 8


# ── Schema ──────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    indices:    list[dict]    = []
    sectors:    list[dict]    = []
    north:      dict | None   = None
    stockData:  list[dict]    = []
    wl:         list[Any]     = []
    news:       list[dict]    = []
    use_deep:   bool          = True
    compact:    bool          = False
    extra_data: dict | None   = None


# ── 限流助手 ─────────────────────────────────────────────────────────────────

async def _check_ai_limit(user_id: int, role: str, redis) -> None:
    """AI 每日限流。超限抛 HTTP 429。"""
    limit = (
        settings.AI_LIMIT_PRO_PER_DAY
        if role in ("pro", "admin")
        else settings.AI_LIMIT_USER_PER_DAY
    )
    window = 86400
    key = f"ai:analyze:{user_id}"
    now = time.time()

    await redis.zremrangebyscore(key, 0, now - window)
    count = await redis.zcard(key)

    if count >= limit:
        oldest = await redis.zrange(key, 0, 0, withscores=True)
        if oldest:
            retry_after = int(window - (now - oldest[0][1])) + 1
        else:
            retry_after = window
        raise HTTPException(
            status_code=429,
            detail={"code": "429", "message": f"AI 分析次数已达今日上限（{limit}/day）"},
            headers={"Retry-After": str(retry_after)},
        )

    await redis.zadd(key, {f"{now}:{time.monotonic_ns()}": now})
    await redis.expire(key, window)


# ── 端点 ─────────────────────────────────────────────────────────────────────

@router.post("/analyze")
async def analyze(
    body: AnalyzeRequest,
    user: CurrentUser,
    db: DbDep,
    redis: RedisDep,
):
    """AI 市场分析。Bearer + 每日限流（user 20次, pro 100次）。"""
    await _check_ai_limit(user.id, user.role, redis)

    # 构建入参 dict（compact 处理）
    data = body.model_dump(exclude={"use_deep", "compact", "extra_data"})
    if body.compact:
        data = deepseek.apply_compact(data)

    model = (
        settings.DEEPSEEK_MODEL_DEEP if body.use_deep else settings.DEEPSEEK_MODEL
    )
    input_hash = deepseek.compute_hash(data, model)

    # 命中缓存？
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    res = await db.execute(
        select(AiAnalysisCache).where(
            AiAnalysisCache.input_hash == input_hash,
            AiAnalysisCache.model == model,
            AiAnalysisCache.expires_at > now_utc,
        )
    )
    cache_row = res.scalar_one_or_none()

    if cache_row:
        import json as _json
        result = _json.loads(cache_row.result_json)
        if "_meta" not in result:
            result["_meta"] = {}
        result["_meta"]["cached"] = True
        result["_meta"]["model"] = model
    else:
        result = await deepseek.call_deepseek(data, model)

        # 写入 ai_analysis_cache
        import json as _json
        expires_at = now_utc + timedelta(hours=_CACHE_TTL_H)
        cache_row = AiAnalysisCache(
            user_id=user.id,
            input_hash=input_hash,
            input_summary=deepseek.build_input_summary(data),
            model=model,
            result_json=_json.dumps(result, ensure_ascii=False),
            token_usage=result.get("_meta", {}).get("token_usage"),
            expires_at=expires_at,
        )
        db.add(cache_row)
        await db.flush()   # 让 cache_row.id 填充

    # 写入 / 更新 user_ai_history
    date_key = datetime.now(timezone.utc).strftime("%Y%m%d")
    # CST 偏移
    cst_hour = (datetime.now(timezone.utc).hour + 8) % 24
    date_key_cst = (
        datetime.now(timezone.utc) + timedelta(hours=8)
    ).strftime("%Y%m%d")
    time_key = deepseek.get_time_key()

    res2 = await db.execute(
        select(UserAiHistory).where(
            UserAiHistory.user_id == user.id,
            UserAiHistory.date_key == date_key_cst,
            UserAiHistory.time_key == time_key,
        )
    )
    hist_row = res2.scalar_one_or_none()
    if hist_row:
        hist_row.cache_id = cache_row.id
    else:
        db.add(UserAiHistory(
            user_id=user.id,
            date_key=date_key_cst,
            time_key=time_key,
            cache_id=cache_row.id,
        ))

    await db.commit()
    return ok(result)


@router.get("/history")
async def history(user: CurrentUser, db: DbDep):
    """获取当前用户 AI 分析历史索引。"""
    res = await db.execute(
        select(UserAiHistory)
        .where(UserAiHistory.user_id == user.id)
        .order_by(UserAiHistory.created_at.desc())
        .limit(90)
    )
    rows = res.scalars().all()
    return ok([
        {
            "date_key": r.date_key,
            "time_key": r.time_key,
            "cache_id": r.cache_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ])


@router.get("/history/{date_key}/{time_key}")
async def history_detail(
    date_key: str = Path(..., description="日期，如 20260605"),
    time_key: str = Path(..., description="盘前 | 盘中 | 盘后"),
    user: CurrentUser = None,
    db: DbDep = None,
):
    """获取指定日期时段的 AI 分析结果。"""
    res = await db.execute(
        select(UserAiHistory).where(
            UserAiHistory.user_id == user.id,
            UserAiHistory.date_key == date_key,
            UserAiHistory.time_key == time_key,
        )
    )
    hist = res.scalar_one_or_none()
    if not hist:
        raise HTTPException(status_code=404, detail="分析记录不存在")

    res2 = await db.execute(
        select(AiAnalysisCache).where(AiAnalysisCache.id == hist.cache_id)
    )
    cache = res2.scalar_one_or_none()
    if not cache:
        raise HTTPException(status_code=404, detail="分析结果已过期或不存在")

    import json as _json
    result = _json.loads(cache.result_json)
    return ok(result)
