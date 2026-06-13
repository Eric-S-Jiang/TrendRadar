"""搜索接口 — /api/search/*

对照 GPXX-V3-接口契约.md §2.18。
"""
from fastapi import APIRouter, Query

from app.core.envelope import ok
from app.services import eastmoney

router = APIRouter()


@router.get("/stock")
async def search_stock(
    q: str = Query(..., description="搜索关键词，如 '茅台' 或 '600519'", max_length=100),
):
    """东财股票搜索。"""
    return ok(await eastmoney.fetch_search(q))
