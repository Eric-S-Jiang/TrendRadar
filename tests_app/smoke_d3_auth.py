"""D3 auth 端到端验收脚本。

用法：
    .venv/Scripts/python.exe tests_app/smoke_d3_auth.py

预期：12 项测试全部 PASS。

技巧：
- 用 fakeredis 替换真 Redis（脱离 docker 也能跑）
- 每次运行前清空 users 表（避免 dup 错误）
"""
import asyncio
import sys
from pathlib import Path

# 把项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fakeredis.aioredis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def main() -> int:
    # 1. 注入 fakeredis（必须在 import app.main 之前）
    from app.core import redis as redis_mod
    redis_mod.set_redis(fakeredis.aioredis.FakeRedis(decode_responses=True))

    # 2. 清空 users 表（让脚本可重复运行）
    asyncio.run(_reset_users())

    # 3. 启动 app + TestClient
    from app.main import app
    client = TestClient(app)

    passed = 0
    failed = 0

    def case(name: str, fn) -> None:
        nonlocal passed, failed
        try:
            fn()
            print(f"  [PASS] {name}")
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
            failed += 1

    print("=== D3 auth end-to-end ===\n")

    # 共享上下文
    state = {}

    def t01_register_weak_password():
        r = client.post("/api/auth/register", json={
            "email": "weak@example.com",
            "password": "onlyletters",
        })
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"
        body = r.json()
        assert body["code"] == "422"
        assert body["data"] is not None and "errors" in body["data"]

    def t02_register_success():
        r = client.post("/api/auth/register", json={
            "email": "alice@example.com",
            "password": "pass1234",
            "nickname": "Alice",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == "200"
        data = body["data"]
        assert "access_token" in data and data["access_token"]
        assert data["user"]["email"] == "alice@example.com"
        assert data["user"]["role"] == "user"
        assert data["user"]["legacy_imported"] == 0
        # 检查 cookie
        assert "gpxx_refresh" in client.cookies, "refresh cookie not set"
        state["access"] = data["access_token"]
        state["refresh_cookie"] = client.cookies["gpxx_refresh"]

    def t03_register_duplicate():
        r = client.post("/api/auth/register", json={
            "email": "alice@example.com",
            "password": "pass1234",
        })
        assert r.status_code == 400
        body = r.json()
        assert body["code"] == "1001", f"expected business code 1001, got {body['code']}"

    def t04_login_wrong_password():
        # 用一个新的 client 避免 cookie 干扰
        c = TestClient(app)
        r = c.post("/api/auth/login", json={
            "email": "alice@example.com",
            "password": "wrong-password-123",
        })
        assert r.status_code == 401
        body = r.json()
        assert body["code"] == "401"

    def t05_login_success():
        c = TestClient(app)
        r = c.post("/api/auth/login", json={
            "email": "alice@example.com",
            "password": "pass1234",
        })
        assert r.status_code == 200
        body = r.json()
        access = body["data"]["access_token"]
        assert access
        state["access_login"] = access
        state["refresh_cookie_login"] = c.cookies["gpxx_refresh"]

    def t06_me_with_bearer():
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {state['access']}"})
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["email"] == "alice@example.com"

    def t07_me_without_token():
        r = client.get("/api/auth/me")
        assert r.status_code == 401
        body = r.json()
        assert body["code"] == "401"

    def t08_me_with_garbage_token():
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
        assert r.status_code == 401

    def t09_refresh_with_cookie():
        c = TestClient(app)
        c.cookies.set("gpxx_refresh", state["refresh_cookie"])
        r = c.post("/api/auth/refresh")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "access_token" in body["data"]
        assert body["data"]["access_token"]
        state["access_refreshed"] = body["data"]["access_token"]

    def t10_refresh_without_cookie():
        c = TestClient(app)
        r = c.post("/api/auth/refresh")
        assert r.status_code == 401
        assert r.json()["code"] == "1101"

    def t11_logout_revokes_session():
        c = TestClient(app)
        c.cookies.set("gpxx_refresh", state["refresh_cookie"])
        r = c.post("/api/auth/logout")
        assert r.status_code == 200
        # 登出后再 refresh 应失败
        r2 = c.post("/api/auth/refresh")
        # 注意：TestClient 退出 logout 时已经 delete_cookie，需要重新塞
        c.cookies.set("gpxx_refresh", state["refresh_cookie"])
        r3 = c.post("/api/auth/refresh")
        assert r3.status_code == 401, "logout 后 refresh 应失败"

    def t12_login_rate_limit():
        # 清掉前面用例累积的 login 限流计数（与生产无关，仅测试隔离）
        async def _clear():
            r = await redis_mod.get_redis()
            await r.flushdb()
        asyncio.run(_clear())

        c = TestClient(app)
        # 5 次失败登录（AUTH_LIMIT_PER_MIN_PER_IP=5），第 6 次应该 429
        for i in range(5):
            r = c.post("/api/auth/login", json={
                "email": "alice@example.com",
                "password": "wrong",
            })
            assert r.status_code == 401, f"iter {i}: {r.text}"
        r = c.post("/api/auth/login", json={
            "email": "alice@example.com",
            "password": "wrong",
        })
        assert r.status_code == 429, f"expected 429 after 5 fails, got {r.status_code}"
        assert r.headers.get("Retry-After") == "60"
        body = r.json()
        assert body["code"] == "429"

    cases = [
        ("01 register: weak password → 422 envelope", t01_register_weak_password),
        ("02 register: success → access + cookie + user", t02_register_success),
        ("03 register: duplicate email → 1001 envelope", t03_register_duplicate),
        ("04 login: wrong password → 401", t04_login_wrong_password),
        ("05 login: success → access + cookie", t05_login_success),
        ("06 me: Bearer token → 200 user", t06_me_with_bearer),
        ("07 me: no token → 401 envelope", t07_me_without_token),
        ("08 me: malformed token → 401", t08_me_with_garbage_token),
        ("09 refresh: with cookie → new access", t09_refresh_with_cookie),
        ("10 refresh: no cookie → 1101 envelope", t10_refresh_without_cookie),
        ("11 logout: revokes session, refresh after fails", t11_logout_revokes_session),
        ("12 login: 5/min rate limit → 429 + Retry-After", t12_login_rate_limit),
    ]

    for name, fn in cases:
        case(name, fn)

    print(f"\n=== {passed} passed, {failed} failed ===")
    return 0 if failed == 0 else 1


async def _reset_users() -> None:
    """清空 users 表（cascade 会清掉 sessions）。"""
    from sqlalchemy import delete
    from app.core.db import BusinessSession
    from app.models.user import User
    async with BusinessSession() as s:
        await s.execute(delete(User))
        await s.commit()


if __name__ == "__main__":
    sys.exit(main())
