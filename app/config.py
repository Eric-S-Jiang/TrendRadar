"""后端全局配置：从环境变量读取，pydantic-settings 校验。"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 数据库
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/gpxx.db"
    TREND_DATABASE_URL: str = "sqlite+aiosqlite:///./data/trend.db"

    # Redis（开发环境无 Redis 时设 USE_FAKEREDIS=true）
    REDIS_URL: str = "redis://localhost:6379/0"
    USE_FAKEREDIS: bool = False

    # JWT — 生产必须通过环境变量覆盖默认值
    JWT_SECRET: str = "dev-insecure-please-override-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TTL_MIN: int = 15
    JWT_REFRESH_TTL_DAYS: int = 30

    # DeepSeek
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_MODEL_DEEP: str = "deepseek-reasoner"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"

    # CORS — 逗号分隔字符串，由 cors_origins_list 解析为 list
    CORS_ORIGINS: str = "http://localhost:5173"

    # SSE
    SSE_MAX_CONNECTIONS: int = 100

    # 限流
    AI_LIMIT_USER_PER_DAY: int = 20
    AI_LIMIT_PRO_PER_DAY: int = 100
    AUTH_LIMIT_PER_MIN_PER_IP: int = 5
    REGISTER_LIMIT_PER_HOUR_PER_IP: int = 10

    # TrendRadar
    TRENDRADAR_CONFIG_PATH: str = "./config/trendradar.yaml"

    # 日志
    LOG_LEVEL: str = "INFO"

    # 游客模式
    GUEST_MODE_ENABLED: bool = True

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
