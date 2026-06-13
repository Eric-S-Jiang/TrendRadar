"""市场统计接口 — /api/market/*

对照 GPXX-V3-接口契约.md §2.12-2.13。
"""
from fastapi import APIRouter

from app.core.envelope import ok
from app.services import eastmoney

router = APIRouter()


@router.get("/limit-stats")
async def limit_stats():
    """涨跌停统计（沪深主板 + 创业板 + 科创板）。"""
    return ok(await eastmoney.fetch_limit_stats())


@router.get("/turnover")
async def turnover():
    """两市成交额（亿元）。"""
    return ok(await eastmoney.fetch_turnover())
