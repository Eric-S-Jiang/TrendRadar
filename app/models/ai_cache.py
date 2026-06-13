"""AI 分析结果缓存 + 用户历史索引。"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AiAnalysisCache(Base):
    """全用户共享的输入指纹缓存。

    同样的 input + model 组合，结果可命中缓存，节省 token。
    """

    __tablename__ = "ai_analysis_cache"
    __table_args__ = (
        UniqueConstraint("input_hash", "model", name="uq_ai_cache_hash_model"),
        Index("idx_ai_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 可空：公共缓存（任何用户输入都可写入并被其他用户命中）
    user_id: Mapped[int | None] = mapped_column(Integer)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA256
    input_summary: Mapped[str | None] = mapped_column(String(500))
    model: Mapped[str] = mapped_column(String(50), nullable=False)
    # SQLite 无原生 JSON 类型，存 TEXT；读取时 json.loads
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    token_usage: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class UserAiHistory(Base):
    """用户的 AI 历史索引（替代前端 histKeys localStorage）。

    指向 ai_analysis_cache，按 date_key + time_key 索引。
    """

    __tablename__ = "user_ai_history"
    __table_args__ = (
        UniqueConstraint("user_id", "date_key", "time_key", name="uq_ai_hist_user_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    date_key: Mapped[str] = mapped_column(String(8), nullable=False)  # '20260605'
    time_key: Mapped[str] = mapped_column(String(20), nullable=False)  # '盘前' | '盘中' | '盘后'
    cache_id: Mapped[int] = mapped_column(
        ForeignKey("ai_analysis_cache.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
