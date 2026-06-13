"""导出全部 ORM 模型。

import 本包就能触发所有模型注册到 Base.metadata，
Alembic autogenerate 才能发现它们。
"""
from app.models.ai_cache import AiAnalysisCache, UserAiHistory
from app.models.favorite import UserFavoriteNews
from app.models.feedback import UserFeedback
from app.models.user import User, UserSession
from app.models.watchlist import UserWatchlist

__all__ = [
    "User",
    "UserSession",
    "UserWatchlist",
    "UserFavoriteNews",
    "AiAnalysisCache",
    "UserAiHistory",
    "UserFeedback",
]
