"""密码哈希 + JWT 签发/校验 + refresh token 生成。

设计：
- 密码哈希：bcrypt 4.x 直用（passlib 1.7.x 与 bcrypt 4.x 自检不兼容，跳过 passlib）
- Access token：JWT，HS256，15 分钟过期
- Refresh token：随机 64 字符（base64url），无加密，存 DB
"""
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()

# bcrypt 输入上限 72 字节（这是 bcrypt 算法本身的限制）。
# Schemas 层已经限制 password ≤ 72 字符，这里再做一次 bytes 截断兜底
# （比如用户输入了 Unicode emoji，1 char 可能 4 字节）。
_BCRYPT_MAX_BYTES = 72
_BCRYPT_ROUNDS = 12


def hash_password(plain: str) -> str:
    """bcrypt 哈希；cost=12。"""
    pwd = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pwd, bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """常量时间比较；plain 错误返回 False，不抛异常。"""
    try:
        pwd = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(pwd, hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, role: str) -> str:
    """签发 access JWT。

    Claims:
      sub: 用户 id（字符串）
      role: 'user' / 'pro' / 'admin'
      iat: issued at（unix 秒）
      exp: expire（unix 秒）
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_ACCESS_TTL_MIN)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """解析 access JWT。失败返回 None（统一由路由层抛 401）。"""
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        return None


def generate_refresh_token() -> str:
    """随机 refresh token。

    secrets.token_urlsafe(48) → ~64 字符 base64url，
    熵约 384 bit，碰撞概率忽略不计。
    """
    return secrets.token_urlsafe(48)
