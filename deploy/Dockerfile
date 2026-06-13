# GPXX V3 后端镜像
# 注意：context 必须是 TrendRadar 项目根目录（含 app/ 和 trendradar/）
# 构建命令：docker compose -f deploy/docker-compose.yml build
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 换阿里云镜像源（上海服务器访问更快），安装系统依赖
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates tzdata && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    rm -rf /var/lib/apt/lists/*

# 先拷依赖文件利用 layer cache
COPY requirements.txt ./
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# 拷代码：TrendRadar 原代码 + gpxx 后端 app
COPY trendradar/   ./trendradar/
COPY app/          ./app/
COPY alembic/      ./alembic/
COPY alembic.ini   ./
COPY config/       ./config/

# 准备数据/日志目录
RUN mkdir -p /data/sqlite /app/logs

EXPOSE 8000

# 启动顺序：Alembic 迁移业务库 → uvicorn 单 worker
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log"]
