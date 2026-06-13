"""统一响应外壳 — {code, message, data}.

所有 /api/* 接口都遵循这个结构（SSE 流式端点除外）。

路由用法：
    from app.core.envelope import ok

    @router.get("/me")
    async def me(user: CurrentUser):
        return ok({"id": user.id, "email": user.email})

错误用法（在 main.py 全局异常处理器中包装）：
    raise HTTPException(status_code=401, detail="未登录")
    # 自动转为 {"code": "401", "message": "未登录", "data": null}

    # 业务扩展码：传 dict 给 detail
    raise HTTPException(status_code=400, detail={"code": "1001", "message": "邮箱已注册"})

业务码规范见 GPXX-V3-后端实施方案.md §3.8.5。
"""
from typing import Any


def ok(data: Any = None, message: str = "ok") -> dict:
    """成功响应。HTTP status 由 FastAPI 默认为 200。"""
    return {"code": "200", "message": message, "data": data}


def err(code: str, message: str, data: Any = None) -> dict:
    """错误响应 body。HTTP status 由抛出方决定。

    code 通常是 HTTP status 的字符串化（"400" / "401" / "429"），
    业务扩展码用 4 位数字字符串（"1001" / "1101" 等）。
    """
    return {"code": code, "message": message, "data": data}
