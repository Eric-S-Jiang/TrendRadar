"""行业板块接口 — /api/sectors/*

对照 GPXX-V3-接口契约.md §2.6-2.7。
"""
from fastapi import APIRouter

from app.core.envelope import ok
from app.services import eastmoney

router = APIRouter()


@router.get("")
async def sectors():
    """行业板块涨跌榜（前18，按涨幅排序）。"""
    return ok(await eastmoney.fetch_sectors())


@router.get("/breadth")
async def breadth():
    """市场宽度：上涨/下跌家数 + 涨跌停统计。"""
    return ok(await eastmoney.fetch_market_breadth())
