#!/usr/bin/env bash
# Daily News - 系统服务一键安装
# 用法：./scripts/install.sh
# 不要用 sudo 直接调用本脚本；脚本会在需要时自行 sudo 提权。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ─── 用户检测 ────────────────────────────────────────────────
if [[ $EUID -eq 0 ]]; then
    if [[ -z "${SUDO_USER:-}" ]]; then
        echo "❌ 请勿直接用 root 运行本脚本，请用普通用户（脚本按需自动提权）"
        exit 1
    fi
    RUN_USER="$SUDO_USER"
else
    RUN_USER="$USER"
fi
RUN_GROUP="$(id -gn "$RUN_USER")"

# ─── uv 检测 ─────────────────────────────────────────────────
UV_BIN="$(command -v uv || true)"
if [[ -z "$UV_BIN" ]]; then
    echo "❌ 找不到 uv 命令，请先安装：https://docs.astral.sh/uv/"
    exit 1
fi

# ─── systemd 检测 ────────────────────────────────────────────
if ! command -v systemctl >/dev/null 2>&1; then
    echo "❌ 系统未检测到 systemctl（非 systemd 系统），本脚本仅支持 systemd Linux"
    exit 1
fi

cd "$PROJECT_DIR"

echo "🚀 Daily News - 系统服务安装"
echo "────────────────────────────────────────"
echo "  项目目录: $PROJECT_DIR"
echo "  运行身份: $RUN_USER:$RUN_GROUP"
echo "  uv 路径:  $UV_BIN"
echo "────────────────────────────────────────"
echo ""

# 提前提权一次，后续 sudo 命令直接复用凭据缓存
echo "🔐 需要 sudo 权限来写入 /etc/systemd/system/"
sudo -v
echo ""

# ─── [1/7] 同步依赖 ──────────────────────────────────────────
echo "📦 [1/7] 同步依赖 (uv sync)..."
uv sync
echo "✓ 依赖已就绪"
echo ""

# ─── [2/7] 验证 .env ────────────────────────────────────────
echo "🔐 [2/7] 验证 .env..."
if [[ ! -f "$PROJECT_DIR/.env" ]]; then
    echo "❌ .env 不存在，请先复制 .env.example 并填入 API Key"
    exit 1
fi
echo "✓ .env 存在"
echo ""

# ─── [3/7] LLM 健康检查 ─────────────────────────────────────
echo "🔍 [3/7] 校验 LLM 接口（仅在此处校验，运行时不再校验）..."
if ! uv run python -m src.main check; then
    echo ""
    echo "❌ LLM 校验失败，已中止安装"
    echo "请检查 config.json 中的 llm.baseUrl/model 以及 .env 中的 API Key"
    exit 1
fi
echo ""

# ─── [4/7] 生成单元文件 ─────────────────────────────────────
echo "📝 [4/7] 渲染 systemd 单元模板..."
STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGE_DIR"' EXIT

uv run python "$PROJECT_DIR/scripts/_gen_units.py" \
    --project-dir "$PROJECT_DIR" \
    --user "$RUN_USER" \
    --group "$RUN_GROUP" \
    --uv-bin "$UV_BIN" \
    --output-dir "$STAGE_DIR"

# 同时渲染 daily-news 包装脚本（/usr/local/bin/daily-news）
sed "s|{{PROJECT_DIR}}|$PROJECT_DIR|g" \
    "$PROJECT_DIR/scripts/daily-news.tmpl" > "$STAGE_DIR/daily-news"
echo "  ✓ daily-news"
echo ""

# ─── [4.5/7] 构建前端 ──────────────────────────────────────
echo "🎨 [4.5/7] 构建归档前端 (web/)..."
NPM_BIN="$(command -v npm || true)"
if [[ -z "$NPM_BIN" ]]; then
    echo "⚠️ 未检测到 npm,跳过前端构建;归档 Web 将提示 503,可后续手动执行: cd web && npm ci && npm run build"
elif [[ ! -d "$PROJECT_DIR/web/dist" || "$PROJECT_DIR/web/package-lock.json" -nt "$PROJECT_DIR/web/dist/index.html" ]]; then
    (cd "$PROJECT_DIR/web" && npm ci && npm run build)
    echo "✓ 前端构建完成"
else
    echo "✓ 前端产物已是最新,跳过构建"
fi
echo ""

# ─── [5/7] 安装到 systemd ───────────────────────────────────
echo "📥 [5/7] 安装到系统..."
sudo install -m 644 "$STAGE_DIR/dnews-fetch.service" /etc/systemd/system/
sudo install -m 644 "$STAGE_DIR/dnews-fetch.timer"   /etc/systemd/system/
sudo install -m 644 "$STAGE_DIR/dnews-push.service"  /etc/systemd/system/
sudo install -m 644 "$STAGE_DIR/dnews-push.timer"    /etc/systemd/system/
sudo install -m 644 "$STAGE_DIR/dnews-web.service"   /etc/systemd/system/

# 日志保留策略（journald 命名空间 drop-in）
sudo mkdir -p /etc/systemd/journald@dnews.conf.d
sudo install -m 644 "$STAGE_DIR/journald-dnews.conf" \
    /etc/systemd/journald@dnews.conf.d/retention.conf

# daily-news 包装脚本到系统 PATH
sudo install -m 755 "$STAGE_DIR/daily-news" /usr/local/bin/daily-news

sudo systemctl daemon-reload

# 命名空间 journald 实例首次会在 fetch/push 首次产出日志时自动拉起；
# 若已存在（重装场景），重启以加载新保留策略。
sudo systemctl restart systemd-journald@dnews.service 2>/dev/null || true

echo "✓ 单元文件 + daily-news 包装脚本已安装"
echo ""

# ─── [7/7] 启用并启动服务 ─────────────────────────────────
echo "🚦 [7/7] 启用并（重）启动服务..."
# 先 enable 注册开机自启
sudo systemctl enable dnews-fetch.timer dnews-push.timer
# 再 restart 强制按新单元文件重置内存中的 timer 状态
# （enable --now 对已运行的 timer 是 no-op，无法应用新 OnCalendar/OnActiveSec 等改动）
sudo systemctl restart dnews-fetch.timer dnews-push.timer

# web 归档是常驻 service(非 timer),enable --now 直接拉起
sudo systemctl enable --now dnews-web.service
sudo systemctl restart dnews-web.service
echo ""

# ─── 完成 ───────────────────────────────────────────────────
echo "✅ 安装完成！"
echo ""
echo "下次触发时间："
echo "  fetch:  每 $(grep fetch_interval_minutes "$PROJECT_DIR/config.json" | head -1 | grep -o '[0-9]\+') 分钟"
echo "  日报:   $(systemd-analyze calendar "*-*-* $(grep -A2 push_cron "$PROJECT_DIR/config.json" | grep -o '[0-9]\+ [0-9]\+' | head -1 | awk '{printf "%02d:%02d:00", $2, $1}')" 2>/dev/null | grep 'Next elapse' | sed 's/.*Next elapse: //' || echo '未配置')"
# 周报:取第一条 weekly_cron(分 时 * * 星期),转成 systemd OnCalendar 再解析
_WEEKLY_CRON="$(grep -A5 weekly_cron "$PROJECT_DIR/config.json" | grep -o '"[^"]*"' | sed -n '2p' | tr -d '"')"
_WEEKLY_ONCAL="$("$UV_BIN" run python - "$_WEEKLY_CRON" <<'PY'
import sys
m, h, _, _, dow = sys.argv[1].split()
names = {"0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed", "4": "Thu", "5": "Fri", "6": "Sat", "7": "Sun"}
d = names.get(dow, "")
if d:
    print(f"{d} *-*-* {int(h):02d}:{int(m):02d}:00")
else:
    print(f"*-*-* {int(h):02d}:{int(m):02d}:00")
PY
)"
echo "  周报:   $(systemd-analyze calendar "$_WEEKLY_ONCAL" 2>/dev/null | grep 'Next elapse' | sed 's/.*Next elapse: //' || echo '未配置')"
echo ""
echo "systemd timer 状态："
systemctl list-timers 'dnews-*' --no-pager || true
echo ""
echo "常用命令（系统 PATH 中可直接调用）："
echo "  daily-news status      查看状态 + 最近日志"
echo "  daily-news logs        实时跟随日志"
echo "  daily-news stop        停止"
echo "  daily-news start       启动"
echo "  daily-news restart     重启 timer"
echo ""
WEB_URL="$(uv run python -c "import json;c=json.load(open('config.json'));w=c.get('web',{});print(f\"http://{w.get('host','127.0.0.1')}:{w.get('port',8000)}\")" 2>/dev/null || echo 'http://127.0.0.1:8000')"
echo "归档 Web:  $WEB_URL  (daily-news status 可查看 dnews-web 状态)"
echo ""
echo "手动立即触发一次任务（不影响下次调度）："
echo "  sudo systemctl start dnews-fetch.service"
echo "  sudo systemctl start dnews-push.service"
echo ""
echo "卸载：$PROJECT_DIR/scripts/uninstall.sh"
