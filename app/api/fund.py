"""基金接口 — /api/fund/*

对照 GPXX-V3-接口契约.md §2.19。
"""
from fastapi import APIRouter

from app.core.envelope import ok
from app.services import eastmoney

router = APIRouter()


@router.get("/top-holdings")
async def top_holdings():
    """公募基金重仓股 TOP 100（东财 datacenter，6 小时缓存）。

    返回字段：code, name, fund_count（持仓基金数量）, total_value（持仓总市值，亿元）。
    按 fund_count DESC 排序。API 故障时返回空列表。
    """
    try:
        return ok(await eastmoney.fetch_top_holdings())
    except Exception:
        return ok([])
