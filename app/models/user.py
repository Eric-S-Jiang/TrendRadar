"""用户 + 会话表。

对应 GPXX-V3-前后端分离与TrendRadar集成方案.md §5.1。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50))
    avatar_url: Mapped[str | None] = mapped_column(String(500))

    # 'user' | 'pro' | 'admin'
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False)

    # SQLite 无 BOOLEAN，统一用 INTEGER 0/1
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    email_verified: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # legacy-import 幂等标志：首次成功导入后置 1
    legacy_imported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 用户偏好（V3.1 修订：把 density 直接存 users 表，避免新建 user_preferences 表）
    density: Mapped[str | None] = mapped_column(String(20))  # 'compact' | 'full' | 'trading'

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    # 关系
    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    refresh_token: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    device_info: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="sessions")
