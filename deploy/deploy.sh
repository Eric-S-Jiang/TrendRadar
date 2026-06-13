#!/bin/bash
# GPXX V3 一键部署脚本
# 使用：cd /data/docker/stock/deploy && chmod +x deploy.sh && ./deploy.sh
# 更新：./deploy.sh --update

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$SCRIPT_DIR/.env.production"
DATA_DIR="$PROJECT_DIR/data"   # 数据目录与项目同级：/data/docker/stock/data

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
die()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# 兼容 docker compose v2（插件）和 docker-compose v1
if docker compose version > /dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose > /dev/null 2>&1; then
    DC="docker-compose"
else
    die "未找到 docker compose 或 docker-compose，请先安装"
fi
log "使用: $DC"

echo "================================================="
echo "  GPXX V3 部署脚本"
echo "  项目目录: $PROJECT_DIR"
echo "  数据目录: $DATA_DIR"
echo "================================================="

# ── 1. 检查 env 文件 ──────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
    warn ".env.production 不存在，从模板创建..."
    cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
    die "请先编辑 $ENV_FILE 填写 JWT_SECRET / REDIS_PASSWORD / DEEPSEEK_API_KEY，然后重新运行"
fi

# 检查必填项未被替换（跳过注释行）
if grep -v '^\s*#' "$ENV_FILE" | grep -q "REPLACE_WITH"; then
    die ".env.production 中仍有未填写的 REPLACE_WITH_* 字段，请先编辑"
fi
log "环境变量文件检查通过"

# ── 2. 创建数据目录 ───────────────────────────────────────
mkdir -p "$DATA_DIR/sqlite" \
         "$DATA_DIR/redis" \
         "$DATA_DIR/logs" \
         "$DATA_DIR/frontend" \
         "$DATA_DIR/trend-config"
log "数据目录已就绪: $DATA_DIR"

# ── 3. 复制 TrendRadar 配置（首次部署） ───────────────────
if [ ! -f "$DATA_DIR/trend-config/trendradar.yaml" ]; then
    if [ -f "$PROJECT_DIR/config/config.yaml" ]; then
        cp "$PROJECT_DIR/config/config.yaml" "$DATA_DIR/trend-config/trendradar.yaml"
        log "TrendRadar 配置已复制"
    else
        warn "未找到 config/config.yaml，TrendRadar 采集容器可能无法启动"
    fi
fi

# ── 4. 写入 .env 供 docker compose 自动读取 ───────────────
# docker-compose v1 / v2 均支持自动读取同目录下的 .env 文件
cp "$ENV_FILE" "$SCRIPT_DIR/.env"

# 追加数据目录路径（供 docker-compose.yml 变量替换）
echo "DATA_DIR=$DATA_DIR" >> "$SCRIPT_DIR/.env"
log "已生成 .env"

# ── 5. 构建镜像 ──────────────────────────────────────────
cd "$SCRIPT_DIR"
log "开始构建镜像（可能需要 3-5 分钟）..."
if [ "$1" = "--update" ]; then
    $DC build --no-cache gpxx-backend
else
    $DC build gpxx-backend
fi
log "镜像构建完成"

# ── 6. 启动容器 ──────────────────────────────────────────
log "启动所有容器..."
$DC up -d
log "容器已启动"

# ── 7. 等待 backend 健康检查 ─────────────────────────────
log "等待后端健康检查（最多 60 秒）..."
for i in $(seq 1 12); do
    if docker inspect --format='{{.State.Health.Status}}' gpxx-backend 2>/dev/null | grep -q "healthy"; then
        log "后端健康检查通过"
        break
    fi
    if [ $i -eq 12 ]; then
        warn "健康检查超时，请手动检查: $DC logs gpxx-backend"
    fi
    sleep 5
done

# ── 8. 验证接口 ───────────────────────────────────────────
log "验证 /api/health..."
if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
    log "接口验证通过"
else
    warn "后端可能尚未就绪，稍后手动验证: curl http://localhost:8000/api/health"
fi

# ── 9. 输出状态和常用命令 ────────────────────────────────
echo ""
echo "================================================="
echo -e "${GREEN}部署完成！${NC}"
echo "================================================="
echo ""
$DC ps
echo ""
echo "常用命令："
echo "  查看日志:    $DC logs -f gpxx-backend"
echo "  重启后端:    $DC restart gpxx-backend"
echo "  查看状态:    $DC ps"
echo "  停止服务:    $DC down"
echo "  更新重部署:  ./deploy.sh --update"
echo ""
echo "前端部署（在 Windows 开发机执行）："
echo "  cd d:/project/gpxx && npm run build"
echo "  scp -r dist/ root@8.159.159.48:/opt/gpxx/data/frontend/dist/"
echo "  或: .\\scripts\\deploy-frontend.ps1 -Server root@8.159.159.48"
