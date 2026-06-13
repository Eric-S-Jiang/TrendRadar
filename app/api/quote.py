"""行情接口 — /api/quote/*

对照 GPXX-V3-接口契约.md §2。
"""
from fastapi import APIRouter, Query

from app.core.envelope import ok
from app.services import eastmoney, tencent

router = APIRouter()


@router.get("/batch")
async def batch(
    codes: str = Query(
        ...,
        description="逗号分隔，如 sh600519,sz000001",
        max_length=2000,
        examples=["sh600519,sz000001"],
    ),
):
    """批量取股票/指数行情。

    code 形如 sh600519 / sz000001 / usAAPL（含市场前缀）。
    """
    code_list = tuple(c.strip() for c in codes.split(",") if c.strip())
    return ok(await tencent.fetch_batch(code_list))


@router.get("/idx/cn")
async def idx_cn():
    """A股主要指数：上证 / 深证 / 创业板 / 沪深300。"""
    return ok(await tencent.fetch_cn_idx())


@router.get("/idx/us")
async def idx_us():
    """美股主要指数：道指 / 纳指 / 标普。"""
    return ok(await tencent.fetch_us_idx())


@router.get("/idx/intl")
async def idx_intl():
    """港/日/韩指数：恒生 / 日经225 / 韩综。"""
    return ok(await eastmoney.fetch_intl_idx())


@router.get("/kline")
async def kline(
    secid: str = Query(..., description="东财证券ID，如 1.000001（沪市）/ 0.399001（深市）"),
    days: int = Query(default=20, ge=1, le=365, description="K线条数"),
    period: int = Query(default=101, description="101=日线 / 102=周线 / 103=月线"),
):
    """历史 K 线数据（东财 push2his）。"""
    return ok(await eastmoney.fetch_kline(secid, period, days))
