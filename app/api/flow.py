"""资金流向接口 — /api/flow/*

对照 GPXX-V3-接口契约.md §2.8-2.11。
"""
from fastapi import APIRouter

from app.core.envelope import ok
from app.services import eastmoney

router = APIRouter()


@router.get("/north")
async def north():
    """北向/南向资金当日净流入（亿元）。"""
    return ok(await eastmoney.fetch_north())


@router.get("/north/history")
async def north_history():
    """近5日北向资金历史。"""
    return ok(await eastmoney.fetch_north_history())


@router.get("/main-capital")
async def main_capital():
    """主力资金：全行业板块主力净流入汇总。"""
    return ok(await eastmoney.fetch_main_capital())


@router.get("/margin")
async def margin():
    """两融余额（历史日数据，30分钟缓存）。"""
    return ok(await eastmoney.fetch_margin())
