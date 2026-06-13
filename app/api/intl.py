"""国际数据接口 — /api/intl/*

对照 GPXX-V3-接口契约.md §2.14-2.17。
"""
from fastapi import APIRouter

from app.core.envelope import ok
from app.services import eastmoney

router = APIRouter()


@router.get("/eu")
async def eu():
    """欧洲指数（DAX / 富时100 / CAC40）。"""
    return ok(await eastmoney.fetch_eu_idx())


@router.get("/commodities")
async def commodities():
    """大宗商品（原油 / 黄金 / 沪铜）。"""
    return ok(await eastmoney.fetch_commodities())


@router.get("/fx")
async def fx():
    """汇率（美元指数 / 离岸人民币）。"""
    return ok(await eastmoney.fetch_fx())


@router.get("/macro")
async def macro():
    """宏观指标（VIXY情绪ETF / 10Y美债期货）。"""
    return ok(await eastmoney.fetch_macro())
