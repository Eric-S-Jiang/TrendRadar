"""认证接口 — /api/auth/*。

对照 GPXX-V3-接口契约.md §1。
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from sqlalchemy import select, update

from app.config import get_settings
from app.core.envelope import ok
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    verify_password,
)
from app.deps import CurrentUser, DbDep
from app.models.user import User, UserSession
from app.schemas.auth import ChangePasswordReq, LoginReq, RegisterReq, SessionResp, UserResp
from app.services.ratelimit import check_rate_limit

settings = get_settings()
router = APIRouter()

REFRESH_COOKIE_NAME = "gpxx_refresh"
REFRESH_COOKIE_PATH = "/api/auth"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # SQLite TIMESTAMP 用 naive UTC


def _client_ip(req: Request) -> str:
    return req.client.host if req.client else "0.0.0.0"


def _set_refresh_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.JWT_REFRESH_TTL_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=False,  # 生产 HTTPS 时改 True
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(resp: Response) -> None:
    resp.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


async def _issue_session(
    db,
    user: User,
    response: Response,
    req: Request,
) -> str:
    """签发 refresh token + 写入 user_sessions + 设置 cookie，返回 access token。"""
    refresh = generate_refresh_token()
    sess = UserSession(
        user_id=user.id,
        refresh_token=refresh,
        expires_at=_utcnow() + timedelta(days=settings.JWT_REFRESH_TTL_DAYS),
        ip_address=_client_ip(req),
        device_info=(req.headers.get("user-agent") or "")[:255],
    )
    db.add(sess)
    user.last_login_at = _utcnow()
    await db.commit()
    _set_refresh_cookie(response, refresh)
    return create_access_token(user.id, user.role)


# ============================================================
# 1.1 POST /api/auth/register
# ============================================================
@router.post("/register")
async def register(
    req: RegisterReq,
    response: Response,
    http_req: Request,
    db: DbDep,
):
    await check_rate_limit(
        f"auth:reg:{_client_ip(http_req)}",
        limit=settings.REGISTER_LIMIT_PER_HOUR_PER_IP,
        window_sec=3600,
        message="请求过于频繁，请 3600 秒后重试",
    )

    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail={"code": "1001", "message": "邮箱已注册"},
        )

    user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        nickname=req.nickname,
    )
    db.add(user)
    await db.flush()  # 拿 user.id

    access = await _issue_session(db, user, response, http_req)
    return ok({
        "access_token": access,
        "user": UserResp.model_validate(user).model_dump(mode="json"),
    })


# ============================================================
# 1.2 POST /api/auth/login
# ============================================================
@router.post("/login")
async def login(
    req: LoginReq,
    response: Response,
    http_req: Request,
    db: DbDep,
):
    await check_rate_limit(
        f"auth:login:{_client_ip(http_req)}",
        limit=settings.AUTH_LIMIT_PER_MIN_PER_IP,
        window_sec=60,
        message="请求过于频繁，请 60 秒后重试",
    )

    res = await db.execute(
        select(User).where(User.email == req.email, User.is_active == 1)
    )
    user = res.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    access = await _issue_session(db, user, response, http_req)
    return ok({
        "access_token": access,
        "user": UserResp.model_validate(user).model_dump(mode="json"),
    })


# ============================================================
# 1.3 POST /api/auth/refresh
# ============================================================
@router.post("/refresh")
async def refresh_token(
    db: DbDep,
    gpxx_refresh: str | None = Cookie(default=None),
):
    if not gpxx_refresh:
        raise HTTPException(
            status_code=401,
            detail={"code": "1101", "message": "缺少 refresh token"},
        )

    res = await db.execute(
        select(UserSession).where(
            UserSession.refresh_token == gpxx_refresh,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > _utcnow(),
        )
    )
    session = res.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=401,
            detail={"code": "1101", "message": "refresh token 无效或过期"},
        )

    user = await db.get(User, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail={"code": "1101", "message": "用户已禁用"},
        )

    access = create_access_token(user.id, user.role)
    return ok({"access_token": access})


# ============================================================
# 1.4 POST /api/auth/logout
# ============================================================
@router.post("/logout")
async def logout(
    response: Response,
    db: DbDep,
    gpxx_refresh: str | None = Cookie(default=None),
):
    if gpxx_refresh:
        await db.execute(
            update(UserSession)
            .where(
                UserSession.refresh_token == gpxx_refresh,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=_utcnow())
        )
        await db.commit()
    _clear_refresh_cookie(response)
    return ok({"ok": True})


# ============================================================
# 1.5 GET /api/auth/me
# ============================================================
@router.get("/me")
async def me(user: CurrentUser):
    return ok(UserResp.model_validate(user).model_dump(mode="json"))


# ============================================================
# 1.6 POST /api/auth/change-password
# ============================================================
@router.post("/change-password")
async def change_password(
    req: ChangePasswordReq,
    user: CurrentUser,
    db: DbDep,
):
    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(
            status_code=400,
            detail={"code": "1003", "message": "原密码错误"},
        )
    user.password_hash = hash_password(req.new_password)
    # 撤销除当前外的所有会话（迫使其他设备重新登录）
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_utcnow())
    )
    await db.commit()
    return ok({"ok": True})


# ============================================================
# 1.7 GET /api/auth/sessions
# ============================================================
@router.get("/sessions")
async def list_sessions(
    user: CurrentUser,
    db: DbDep,
    gpxx_refresh: str | None = Cookie(default=None),
):
    res = await db.execute(
        select(UserSession)
        .where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > _utcnow(),
        )
        .order_by(UserSession.created_at.desc())
    )
    items = []
    for s in res.scalars():
        item = SessionResp.model_validate(s).model_dump(mode="json")
        item["is_current"] = (s.refresh_token == gpxx_refresh)
        items.append(item)
    return ok(items)


# ============================================================
# 1.8 DELETE /api/auth/sessions/{session_id}
# ============================================================
@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: int,
    user: CurrentUser,
    db: DbDep,
):
    res = await db.execute(
        select(UserSession).where(
            UserSession.id == session_id,
            UserSession.user_id == user.id,  # 只能撤销自己的
        )
    )
    sess = res.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    if sess.revoked_at is None:
        sess.revoked_at = _utcnow()
        await db.commit()
    return ok({"ok": True})
