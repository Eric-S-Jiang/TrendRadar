"""DeepSeek AI 分析服务。

调用 DeepSeek Chat API（OpenAI 兼容接口），返回结构化 JSON 分析报告。
"""
import hashlib
import json
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException

from app.config import get_settings

settings = get_settings()

_SYSTEM_PROMPT = (
    "你是专业的A股量化分析师。根据用户提供的市场数据，输出结构化 JSON 分析报告。\n"
    "只输出 JSON，不添加任何其他文字。格式严格如下：\n"
    '{"events":[{"title":"事件标题","category":"policy|market|macro",'
    '"impact":0.0,"sectors":[],"stocks":[]}],'
    '"sectors":[{"name":"板块名","view":"bullish|neutral|bearish","reason":"理由","weight":0.0}],'
    '"signals":[{"type":"watch|buy|sell","code":"sh600519","action":"hold|buy|sell|watch","reason":"理由"}],'
    '"watchlist_view":[{"code":"sh600519","rating":"bullish|neutral|bearish","comment":"点评"}]}'
)


def compute_hash(data: dict, model: str) -> str:
    """SHA-256 of (canonical JSON + model) → 64-char hex string."""
    payload = json.dumps({"data": data, "model": model}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def get_time_key() -> str:
    """当前 CST 时段：盘前 / 盘中 / 盘后。"""
    now = datetime.now(timezone.utc)
    h = (now.hour + 8) % 24
    m = now.minute
    if h < 9 or (h == 9 and m < 30):
        return "盘前"
    if h < 15 or (h == 15 and m == 0):
        return "盘中"
    return "盘后"


def apply_compact(data: dict) -> dict:
    """compact=True 时剥离 stockData[].usT / .cnT，节省约 50% token。"""
    if not data.get("stockData"):
        return data
    result = dict(data)
    result["stockData"] = [
        {k: v for k, v in s.items() if k not in ("usT", "cnT")}
        for s in data["stockData"]
    ]
    return result


def build_input_summary(data: dict) -> str:
    """生成 ≤500 字符的输入摘要（存入 ai_analysis_cache.input_summary）。"""
    codes = [s.get("code", "") for s in (data.get("stockData") or [])[:5]]
    return (
        f"indices={len(data.get('indices') or [])}, "
        f"sectors={len(data.get('sectors') or [])}, "
        f"stocks={','.join(codes)}"
    )[:500]


def _build_prompt(data: dict) -> str:
    parts: list[str] = []
    if data.get("indices"):
        parts.append(f"[主要指数]\n{json.dumps(data['indices'], ensure_ascii=False)}")
    if data.get("sectors"):
        parts.append(f"[板块行情(前5)]\n{json.dumps(data['sectors'][:5], ensure_ascii=False)}")
    if data.get("north"):
        parts.append(f"[北向资金]\n{json.dumps(data['north'], ensure_ascii=False)}")
    if data.get("news"):
        titles = [n.get("title", "") for n in data["news"][:10]]
        parts.append(f"[财经新闻(前10)]\n{json.dumps(titles, ensure_ascii=False)}")
    if data.get("stockData"):
        brief = [{"code": s.get("code"), "name": s.get("name")} for s in data["stockData"]]
        parts.append(f"[自选股]\n{json.dumps(brief, ensure_ascii=False)}")
    if data.get("wl"):
        parts.append(f"[关注列表]\n{json.dumps(list(data['wl'])[:10], ensure_ascii=False)}")
    return "\n\n".join(parts) or "无市场数据"


async def call_deepseek(data: dict, model: str) -> dict:
    """调用 DeepSeek API。

    Returns structured analysis dict.
    Raises HTTPException(503) if API key missing or DeepSeek unreachable.
    """
    if not settings.DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=503,
            detail={"code": "503", "message": "DeepSeek 暂时不可用"},
        )

    try:
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(
                f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": _build_prompt(data)},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.3,
                },
            )
            r.raise_for_status()
            resp = r.json()
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "503", "message": "DeepSeek 暂时不可用"},
        ) from exc

    content = resp["choices"][0]["message"]["content"]
    token_usage = (resp.get("usage") or {}).get("total_tokens", 0)

    result: dict = json.loads(content)
    result.setdefault("events", [])
    result.setdefault("sectors", [])
    result.setdefault("signals", [])
    result.setdefault("watchlist_view", [])
    result["_meta"] = {
        "model": model,
        "token_usage": token_usage,
        "cached": False,
    }
    return result
