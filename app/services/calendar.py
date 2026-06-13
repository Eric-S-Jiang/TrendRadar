"""A 股交易时段判断。

用于行情缓存的动态 TTL：交易时段 15s（实时性优先），休市 5min（节省外部 API 调用）。

不考虑节假日 — 节假日缓存命中也只是数据"卡住"，最坏 5min 后会重试。
后期如要精准，可以接入 trading_calendar 库或东财日历接口。
"""
from datetime import datetime

import pytz

TZ = pytz.timezone("Asia/Shanghai")

# 分钟数表示的时间窗口
_AM_OPEN = 9 * 60 + 30   # 09:30
_AM_CLOSE = 11 * 60 + 30  # 11:30
_PM_OPEN = 13 * 60        # 13:00
_PM_CLOSE = 15 * 60       # 15:00


def is_trading(now: datetime | None = None) -> bool:
    """当前是否 A 股交易时段。

    Args:
        now: 可选，用于测试；默认取当前时间
    """
    now = now or datetime.now(TZ)
    # 周末
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return (_AM_OPEN <= hm <= _AM_CLOSE) or (_PM_OPEN <= hm <= _PM_CLOSE)


def quote_ttl() -> int:
    """行情类缓存的动态 TTL：交易时段 15s / 休市 5min。"""
    return 15 if is_trading() else 300
