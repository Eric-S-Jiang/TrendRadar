"""认证接口请求/响应 schema。

对照 GPXX-V3-接口契约.md §1。
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterReq(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  # bcrypt 72 字节上限
    nickname: str | None = Field(default=None, max_length=50)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        """≥8 位，含字母 + 数字。

        前端已校验，这里是后端兜底（防绕过）。
        """
        if not any(c.isalpha() for c in v):
            raise ValueError("密码必须包含字母")
        if not any(c.isdigit() for c in v):
            raise ValueError("密码必须包含数字")
        return v


class LoginReq(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class ChangePasswordReq(BaseModel):
    old_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def _new_password_strength(cls, v: str) -> str:
        if not any(c.isalpha() for c in v):
            raise ValueError("密码必须包含字母")
        if not any(c.isdigit() for c in v):
            raise ValueError("密码必须包含数字")
        return v


class UserResp(BaseModel):
    """对外返回的 user 对象。不含 password_hash。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    nickname: str | None = None
    avatar_url: str | None = None
    role: Literal["user", "pro", "admin"]
    legacy_imported: int = 0
    density: str | None = None
    created_at: datetime
    last_login_at: datetime | None = None


class SessionResp(BaseModel):
    """单个活跃会话信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    device_info: str | None = None
    ip_address: str | None = None
    created_at: datetime
    expires_at: datetime
    is_current: bool = False
