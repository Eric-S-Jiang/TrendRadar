"""复用的 FastAPI Depends。"""
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_business_db, get_trend_db
from app.core.redis import get_redis
from app.core.security import decode_access_token
from app.models.user import User

if TYPE_CHECKING:
    from redis.asyncio import Redis


DbDep = Annotated[AsyncSession, Depends(get_business_db)]
TrendDbDep = Annotated[AsyncSession, Depends(get_trend_db)]


async def _redis_dep() -> "Redis":
    return await get_redis()


RedisDep = Annotated["Redis", Depends(_redis_dep)]


async def _current_user_optional(
    authorization: Annotated[str | None, Header()] = None,
    db: DbDep = None,
) -> User | None:
    """无 token / token 无效都返回 None（不抛 401）。

    用于游客可见的端点（如 /api/quote/*）。
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    payload = decode_access_token(token)
    if not payload:
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return None
    res = await db.execute(
        select(User).where(User.id == user_id, User.is_active == 1)
    )
    return res.scalar_one_or_none()


async def _current_user_required(
    user: Annotated[User | None, Depends(_current_user_optional)],
) -> User:
    """必须登录。失败抛 401，全局 handler 包成 envelope。"""
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return user


CurrentUserOptional = Annotated[User | None, Depends(_current_user_optional)]
CurrentUser = Annotated[User, Depends(_current_user_required)]
