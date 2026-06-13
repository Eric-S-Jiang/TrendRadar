"""热点收藏表。

news_item_id 引用 TrendRadar 每日 DB 文件的 news_items.id（跨库无 FK 约束）。
news_date + title/url/platform_id 是收藏时从当日 DB 读取的冗余字段，避免跨日查询问题。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UserFavoriteNews(Base):
    __tablename__ = "user_favorite_news"
    __table_args__ = (
        UniqueConstraint("user_id", "news_item_id", "news_date", name="uq_fav_user_news_v2"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    news_item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    news_date: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    title: Mapped[str | None] = mapped_column(String(500))
    url: Mapped[str | None] = mapped_column(String(1000))
    platform_id: Mapped[str | None] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
