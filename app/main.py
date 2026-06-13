"""FastAPI 入口：组装路由 + 中间件 + 生命周期 + 全局异常处理。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
# 监听 starlette 版本：fastapi.HTTPException 是它的子类，但 FastAPI 内部 404/405
# 用的是 starlette 原版，监听基类才能全部拦截。
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.core.envelope import err

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Starting gpxx-backend v{}", "3.1.0")
    from app.tasks.scheduler import start_scheduler, stop_scheduler
    await start_scheduler()
    yield
    await stop_scheduler()
    logger.info("Shutting down gpxx-backend")


app = FastAPI(
    title="GPXX Backend",
    version="3.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# —— 全局异常处理器：把所有错误包装成统一 envelope ——

@app.exception_handler(StarletteHTTPException)
async def _handle_http_exc(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
    """HTTPException 自动包装（含 FastAPI 内置 404/405 等）。

    支持两种 detail 写法：
      1. 字符串：raise HTTPException(401, "未登录")
         → {"code": "401", "message": "未登录", "data": null}
      2. 业务码 dict：raise HTTPException(400, detail={"code":"1001","message":"邮箱已注册"})
         → {"code": "1001", "message": "邮箱已注册", "data": null}
    """
    if isinstance(exc.detail, dict) and "code" in exc.detail and "message" in exc.detail:
        body = err(exc.detail["code"], exc.detail["message"], exc.detail.get("data"))
    else:
        body = err(str(exc.status_code), str(exc.detail) if exc.detail else "")
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def _handle_validation(_req: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic 参数校验失败 → 422 envelope。

    Pydantic 2.x 的 errors() 可能在 ctx 里塞 ValueError 实例（自定义 validator 抛的），
    JSON 序列化会炸，所以这里手动洗一次。
    """
    safe_errors = []
    for e in exc.errors():
        item = {k: v for k, v in e.items() if k != "ctx"}
        ctx = e.get("ctx")
        if ctx:
            # 把 ctx 里所有非 JSON-safe 的值转成 str
            item["ctx"] = {k: str(v) for k, v in ctx.items()}
        safe_errors.append(item)
    return JSONResponse(
        status_code=422,
        content=err("422", "参数校验失败", {"errors": safe_errors}),
    )


@app.exception_handler(Exception)
async def _handle_uncaught(_req: Request, exc: Exception) -> JSONResponse:
    """兜底：任何未捕获异常 → 500 envelope。不泄露堆栈。"""
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content=err("500", "服务器内部错误"),
    )


# —— 路由注册 ——
from app.api import ai, auth, flow, fund, health, intl, market, news, quote, search, sectors, stream, user  # noqa: E402

app.include_router(health.router,   prefix="/api/health",   tags=["health"])
app.include_router(auth.router,     prefix="/api/auth",     tags=["auth"])
app.include_router(quote.router,    prefix="/api/quote",    tags=["quote"])
app.include_router(sectors.router,  prefix="/api/sectors",  tags=["sectors"])
app.include_router(flow.router,     prefix="/api/flow",     tags=["flow"])
app.include_router(market.router,   prefix="/api/market",   tags=["market"])
app.include_router(intl.router,     prefix="/api/intl",     tags=["intl"])
app.include_router(search.router,   prefix="/api/search",   tags=["search"])
app.include_router(fund.router,     prefix="/api/fund",     tags=["fund"])
app.include_router(news.router,     prefix="/api/news",     tags=["news"])
app.include_router(ai.router,       prefix="/api/ai",       tags=["ai"])
app.include_router(user.router,     prefix="/api/user",     tags=["user"])
app.include_router(stream.router,   prefix="/api/stream",   tags=["stream"])
