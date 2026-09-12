#!/bin/bash
# ============================================
# aiquant 系统启动脚本 (v2.5: 跨平台timeout兼容)
# ============================================

# macOS 必需：禁用 Objective-C fork 安全检查，避免 gunicorn 多 worker 启动时崩溃
# 错误表现：objc[xxx]: +[NSString initialize] may have been in progress in another thread when fork() was called.
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

# macOS launchd 默认 fd 软限制仅 256，uvicorn 长连接 / CLOSE_WAIT 堆积会耗尽 fd
# 导致新连接无法 accept（症状：TCP 可握手但 HTTP 永不响应），提升至 10240
ulimit -n 10240

set -e
# 容许非关键步骤失败（Streamlit UI kill、psutil 等）
set +e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

# ═══════════════════════════════════════════════════════════
# 跨平台 timeout 兼容层
# 1:1 复刻 GNU timeout 核心行为，解决 macOS 无 timeout 命令问题
# RD-Agent 通过 /bin/sh -c 'timeout DURATION CMD ...' 调用
# 当 running_timeout_period 有值时，自动使用内置脚本实现超时杀进程
# 当 running_timeout_period=None，RD-Agent 不传 timeout，不影响
# 策略：创建临时可执行脚本 + 前置 PATH，/bin/sh 和 bash 都能找到
# ═══════════════════════════════════════════════════════════
if ! command -v timeout &>/dev/null; then
    _TIMEOUT_COMPAT_DIR="$PROJECT_ROOT/.timeout_compat"
    mkdir -p "$_TIMEOUT_COMPAT_DIR"

    # 生成 /bin/sh 兼容的 timeout 可执行脚本（非 bash function，解决 /bin/sh -c 调用场景）
    cat > "$_TIMEOUT_COMPAT_DIR/timeout" << 'TIMEOUT_SCRIPT_EOF'
#!/bin/sh
# macOS timeout 兼容脚本 — 1:1 复刻 GNU timeout 核心行为
# 用法: timeout [--kill-after=DURATION] DURATION COMMAND [ARG...]
# 退出码: 124=超时被杀, 其他=COMMAND退出码

# 解析 --kill-after 选项
_kill_after=2  # 默认 SIGTERM 后等 2s 再 SIGKILL
if [ "$1" = "--kill-after" ] || [ "${1#--kill-after=}" != "$1" ]; then
    if [ "${1#--kill-after=}" != "$1" ]; then
        _ka_raw="${1#--kill-after=}"
        shift
    else
        shift
        _ka_raw="$1"
        shift
    fi
    # 解析 kill-after duration
    case "$_ka_raw" in
        *s|*S) _kill_after="${_ka_raw%[sS]}" ;;
        *m|*M) _kill_after=$(echo "${_ka_raw%[mM]} 60" | awk '{printf "%d", $1*$2}') ;;
        *h|*H) _kill_after=$(echo "${_ka_raw%[hH]} 3600" | awk '{printf "%d", $1*$2}') ;;
        *d|*D) _kill_after=$(echo "${_ka_raw%[dD]} 86400" | awk '{printf "%d", $1*$2}') ;;
        *)     _kill_after="$_ka_raw" ;;
    esac
    _kill_after=$(echo "$_kill_after" | awk '{printf "%d", $1}')
    [ "$_kill_after" -lt 0 ] 2>/dev/null && _kill_after=0
fi

if [ $# -lt 2 ]; then
    echo "timeout: missing operand" >&2
    exit 125
fi

_raw_duration="$1"
shift

# 解析 duration → 秒数（支持 30、30s、5m、1h、2d 等格式）
case "$_raw_duration" in
    *s|*S) _duration_sec="${_raw_duration%[sS]}" ;;
    *m|*M) _duration_sec="$(echo "${_raw_duration%[mM]} * 60" | bc 2>/dev/null)" ;;
    *h|*H) _duration_sec="$(echo "${_raw_duration%[hH]} * 3600" | bc 2>/dev/null)" ;;
    *d|*D) _duration_sec="$(echo "${_raw_duration%[dD]} * 86400" | bc 2>/dev/null)" ;;
    *)     _duration_sec="$_raw_duration" ;;  # 纯数字=秒
esac

# bc 不可用时的 fallback（awk 兜底）
if [ -z "$_duration_sec" ]; then
    case "$_raw_duration" in
        *m|*M) _duration_sec=$(echo "${_raw_duration%[mM]} 60" | awk '{printf "%d", $1*$2}') ;;
        *h|*H) _duration_sec=$(echo "${_raw_duration%[hH]} 3600" | awk '{printf "%d", $1*$2}') ;;
        *d|*D) _duration_sec=$(echo "${_raw_duration%[dD]} 86400" | awk '{printf "%d", $1*$2}') ;;
    esac
fi

# 确保是整数
_duration_sec=$(echo "$_duration_sec" | awk '{printf "%d", $1}')

if [ "$_duration_sec" -le 0 ] 2>/dev/null; then
    echo "timeout: invalid duration '$_raw_duration'" >&2
    exit 125
fi

# 后台启动命令
"$@" &
_cmd_pid=$!

# 轮询等待：命令结束或超时
_elapsed=0
_wait_interval=1
while [ $_elapsed -lt $_duration_sec ]; do
    if ! kill -0 $_cmd_pid 2>/dev/null; then
        wait $_cmd_pid 2>/dev/null
        exit $?
    fi
    sleep $_wait_interval
    _elapsed=$((_elapsed + _wait_interval))
done

# 超时：SIGTERM → 等 kill-after 秒 → SIGKILL
kill -TERM $_cmd_pid 2>/dev/null
sleep "$_kill_after"
if kill -0 $_cmd_pid 2>/dev/null; then
    kill -KILL $_cmd_pid 2>/dev/null
    wait $_cmd_pid 2>/dev/null
else
    wait $_cmd_pid 2>/dev/null
fi
exit 124
TIMEOUT_SCRIPT_EOF

    chmod +x "$_TIMEOUT_COMPAT_DIR/timeout"

    # 前置 PATH：确保 /bin/sh、bash、conda run 的子进程都能找到 timeout
    export PATH="$_TIMEOUT_COMPAT_DIR:$PATH"
    echo "[兼容层] macOS 检测: 已注入 timeout 兼容脚本 → $_TIMEOUT_COMPAT_DIR/timeout"
    echo "[兼容层] GNU timeout 行为 1:1 复刻（超时→SIGTERM→SIGKILL, exit 124）"
fi


# B4: 绕过系统代理（Clash/V2Ray 等会拦截 localhost 请求导致 SSE 断连）
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ── 0. Docker 环境检测 → 自动启动 → 设置 RUN_MODE ──
log_info "=== aiquant 系统启动 ==="

_docker_ready() {
    command -v docker &> /dev/null && docker info &> /dev/null 2>&1
}

# docker CLI 不在 PATH 时，补充 Docker Desktop 常见安装路径
if ! command -v docker &> /dev/null; then
    for _d in /usr/local/bin "$HOME/.docker/bin" "/Applications/Docker.app/Contents/Resources/bin"; do
        if [ -x "$_d/docker" ]; then export PATH="$_d:$PATH"; break; fi
    done
fi

# ── 优先读取 .env 中的 RUN_MODE（如果已显式设置则跳过自动检测） ──
_env_run_mode=""
if [ -f ".env" ]; then
    _env_run_mode=$(grep "^RUN_MODE=" .env | tail -1 | cut -d= -f2 | tr -d ' ')
fi
if [ -n "$_env_run_mode" ]; then
    RUN_MODE="$_env_run_mode"
    log_info ".env 已设置 RUN_MODE=${RUN_MODE}，跳过 Docker 自动检测"
else
    log_info "检测 Docker 环境..."
    if ! _docker_ready && [ -d "/Applications/Docker.app" ]; then
    log_warn "Docker Desktop 已安装但未运行，正在自动启动（约需 30-60 秒）..."
    open -a Docker || true
    _waited=0
    while [ $_waited -lt 90 ]; do
        sleep 5; _waited=$((_waited + 5))
        if _docker_ready; then break; fi
        echo "  ... 等待 Docker 就绪 (${_waited}s)"
    done
fi

if _docker_ready; then
    export RUN_MODE=docker
    log_success "Docker 运行中，使用容器模式 (RUN_MODE=docker)"
    # 回测沙箱镜像检查（docker 模式必需）
    if docker image inspect local_qlib:latest &> /dev/null; then
        log_success "回测沙箱镜像 local_qlib:latest 已就绪"
    else
        log_warn "回测沙箱镜像 local_qlib:latest 不存在"
        if [ -f "docker/build.sh" ]; then
            log_info "正在构建 local_qlib:latest（首次约需 5-15 分钟）..."
            bash docker/build.sh || log_error "镜像构建失败，回测将报错。可稍后手动执行: bash docker/build.sh"
        else
            log_error "未找到 docker/build.sh，请手动构建回测镜像"
        fi
    fi
else
    log_error "Docker 不可用"
    echo ""
    if [ -d "/Applications/Docker.app" ]; then
        echo "  Docker Desktop 启动超时，请手动完成启动："
        echo "    1. 打开「应用程序 → Docker.app」"
        echo "    2. 等待菜单栏鲸鱼图标静止（状态显示 Docker Desktop is running）"
        echo "    3. 终端执行 docker info 确认无报错"
        echo "    4. 重新运行本启动脚本"
    else
        echo "  未安装 Docker Desktop。Docker 是回测的标准沙箱环境，缺少它回测可能出现各类 bug。"
        echo "  安装步骤："
        echo "    1. 下载 Docker Desktop for Mac (Apple Silicon):"
        echo "       https://desktop.docker.com/mac/main/arm64/Docker.dmg"
        echo "    2. 安装并启动 Docker.app，等待菜单栏鲸鱼图标就绪"
        echo "    3. 终端执行 docker info 确认无报错"
        echo "    4. 重新运行本启动脚本"
    fi
    echo ""
    log_warn "将以本地模式降级启动 (RUN_MODE=local)：因子挖掘可用，但回测代码沙箱关闭"
    export RUN_MODE=local
fi
fi  # end RUN_MODE auto-detection

# 将 RUN_MODE 写入 .env（仅当 .env 中不存在时写入）
if [ -f ".env" ]; then
    if grep -q "^RUN_MODE=" .env; then
        :  # .env 已有 RUN_MODE，保留用户设置
    else
        echo "RUN_MODE=${RUN_MODE}" >> .env
        echo "MODEL_CoSTEER_env_type=conda" >> .env
    fi
else
    echo "RUN_MODE=${RUN_MODE}" > .env
    echo "MODEL_CoSTEER_env_type=conda" >> .env
fi
log_success "已写入 RUN_MODE=${RUN_MODE} 到 .env"

# ── 0b. 加载 .env 到当前 shell 环境 ──
# 确保 conda run 子进程和 RD-Agent 子进程都能继承 LLM 配置
# 使用 set -a 自动导出所有变量
if [ -f ".env" ]; then
    set -a
    # 安全加载 .env（跳过空行和注释）
    while IFS= read -r _line; do
        case "$_line" in
            ""|\#*) continue ;;
            *=*) eval "export $_line" ;;
        esac
    done < .env
    set +a
    log_success ".env 已加载到 shell 环境（共 $(grep -c '=' .env) 个变量）"
fi

# ── 1. 环境检查 ──────────────────────────

# 检查 conda
if ! command -v conda &> /dev/null; then
    log_error "conda 未安装，请先安装 Anaconda/Miniconda"
    exit 1
fi

# 激活 conda 环境
CONDA_ENV="aiquant"
if conda env list | grep -q "^${CONDA_ENV} "; then
    log_success "conda 环境 '${CONDA_ENV}' 已存在"
else
    log_warn "conda 环境 '${CONDA_ENV}' 不存在，正在创建..."
    conda create -n aiquant python=3.10 -y
    log_success "环境创建完成"
fi

# 检查 .env 文件
if [ ! -f ".env" ]; then
    log_warn ".env 文件不存在，从 .env.example 复制"
    cp .env.example .env
    log_warn "请编辑 .env 文件填入你的 API Key"
fi

# ── 2. 安装依赖（指纹缓存：清单未变则跳过，省 20-40 秒） ──
DEPS_MANIFEST="v1:fastapi uvicorn numpy pandas pyarrow loguru pydantic pydantic-settings sqlalchemy aiosqlite python-dotenv openbb akshare baostock rdagent pyqlib tradingagents"
# 跨平台 hash：优先 python（最可靠），fallback md5sum / md5 -q
DEPS_HASH=$(echo "$DEPS_MANIFEST" | python3 -c "import sys,hashlib;print(hashlib.md5(sys.stdin.read().encode()).hexdigest())" 2>/dev/null \
    || echo "$DEPS_MANIFEST" | md5sum | cut -d' ' -f1 2>/dev/null \
    || echo "$DEPS_MANIFEST" | md5 -q 2>/dev/null \
    || echo "fallback_no_hash")
DEPS_HASH_FILE=".deps_hash"

# 获取 conda 环境的 python 路径
PYTHON_BIN=$(conda run -n aiquant which python)

if [ -f "$DEPS_HASH_FILE" ] && [ "$(cat "$DEPS_HASH_FILE")" = "$DEPS_HASH" ]; then
    log_success "依赖指纹未变，跳过 pip install（删除 $DEPS_HASH_FILE 可强制重装）"
else
    log_info "安装 Python 依赖..."

    # 安装核心依赖
    $PYTHON_BIN -m pip install -q --upgrade pip

    # 基础依赖
    $PYTHON_BIN -m pip install -q \
        fastapi uvicorn \
        numpy pandas pyarrow \
        loguru pydantic pydantic-settings \
        sqlalchemy aiosqlite \
        python-dotenv

    # OpenBB-SDK + A股数据源
    $PYTHON_BIN -m pip install -q \
        openbb \
        akshare baostock

    # RD-Agent + Qlib + TradingAgents（清单已声明但之前未安装，导致自检必失败）
    $PYTHON_BIN -m pip install -q \
        rdagent pyqlib \
        celery redis \
        streamlit psutil
    # TradingAgents 可选安装（可能因依赖冲突失败，不阻塞）
    $PYTHON_BIN -m pip install -q tradingagents 2>/dev/null || log_warn "TradingAgents 安装失败（可选，不阻塞）"

    log_success "基础依赖安装完成"
    echo "$DEPS_HASH" > "$DEPS_HASH_FILE"
fi

# ── 环境自检（单进程合并检查；标记存在则跳过，省 15-30 秒） ──
SELFCHECK_MARK=".selfcheck_ok"

if [ -f "$SELFCHECK_MARK" ]; then
    log_success "环境自检标记存在，跳过自检（删除 $SELFCHECK_MARK 可重新自检）"
    RDAGENT_INSTALLED=true
else
    log_info "执行环境自检（单进程合并检查）..."
    SELFCHECK_OUTPUT=$($PYTHON_BIN - <<'PYEOF' 2>&1
import sys, os
errors, warns = [], []

# 1. RD-Agent 核心组件（必需）
try:
    import rdagent
    from rdagent.components.coder.factor_coder.config import FACTOR_COSTEER_SETTINGS
    print('[自检] RD-Agent 核心组件 OK')
except Exception as e:
    errors.append(f'RD-Agent: {e}')

# 2. Qlib（必需）
try:
    import qlib
    print('[自检] Qlib OK')
except Exception as e:
    errors.append(f'Qlib: {e}')

# 3. TradingAgents（可选）
try:
    import tradingagents
    print('[自检] TradingAgents OK')
except Exception as e:
    warns.append(f'TradingAgents(可选): {e}')

# 4. LLM 配置
if os.environ.get('CHAT_MODEL'):
    print(f"[自检] LLM 模型配置: {os.environ['CHAT_MODEL']}")
else:
    warns.append('CHAT_MODEL 未设置，LLM 可能无法工作')

# 5. Qlib 数据
qlib_path = os.path.expanduser('~/.qlib/qlib_data/cn_data')
if os.path.exists(qlib_path) and os.listdir(qlib_path):
    print(f'[自检] Qlib 数据就绪: {qlib_path}')
else:
    warns.append('Qlib 数据未就绪，请先在数据管理面板获取市场数据')

for w in warns:
    print(f'[自检] 警告: {w}')
if errors:
    print('[自检] 错误: ' + '; '.join(errors))
    sys.exit(1)
PYEOF
)
    SELFCHECK_EXIT=$?
    echo "$SELFCHECK_OUTPUT"
    if [ $SELFCHECK_EXIT -eq 0 ]; then
        log_success "环境自检通过"
        touch "$SELFCHECK_MARK"
        RDAGENT_INSTALLED=true
    else
        log_warn "自检发现必需组件缺失，尝试安装 rdagent / pyqlib..."
        $PYTHON_BIN -m pip install -q rdagent pyqlib 2>/dev/null || true
        if $PYTHON_BIN -c "import rdagent, qlib" 2>/dev/null; then
            log_success "安装后自检通过"
            touch "$SELFCHECK_MARK"
            RDAGENT_INSTALLED=true
        else
            log_error "RD-Agent/Qlib 安装失败，请手动执行: pip install rdagent pyqlib"
            exit 1
        fi
    fi
fi

# ── 3. 创建必要目录 ──────────────────────
log_info "创建必要目录..."
mkdir -p db/qlib_data/{features,instruments,calendars}
mkdir -p db/memory/reviews
mkdir -p logs

log_success "目录结构已就绪"

# ── 4. 启动服务 ──────────────────────────
log_info "正在启动服务..."

# ── 4a. 启动 Redis（任务队列 Broker） ──
log_info "启动 Redis 任务队列..."
REDIS_PID=""
# 检查 Redis 是否已在运行
if $PYTHON_BIN -c "import socket; s=socket.socket(); s.settimeout(0.5); exit(0 if s.connect_ex(('127.0.0.1',6379))==0 else 1)" 2>/dev/null; then
    log_success "Redis 已在运行（端口 6379）"
else
    REDIS_BIN=$(conda run -n aiquant which redis-server)
    if [ -z "$REDIS_BIN" ]; then
        log_error "redis-server 未安装。请运行: conda install -n aiquant -c conda-forge redis-server"
        exit 1
    fi
    # A3: 使用配置文件启动 Redis（同时启用 AOF + RDB 双持久化，避免重启丢任务进度）
    REDIS_CONF="/tmp/aiquant_redis.conf"
    mkdir -p "$PROJECT_ROOT/redis_data"
    cat > "$REDIS_CONF" << 'REDIS_EOF'
port 6379
bind 127.0.0.1
daemonize yes
# A3: RDB 持久化 — 快照策略
save 900 1
save 300 10
save 60 10000
# A3: AOF 持久化 — 追加日志
appendonly yes
appendfsync everysec
no-appendfsync-on-rewrite no
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb
loglevel warning
REDIS_EOF
    $REDIS_BIN "$REDIS_CONF"
    sleep 1
    if $PYTHON_BIN -c "import socket; s=socket.socket(); s.settimeout(0.5); exit(0 if s.connect_ex(('127.0.0.1',6379))==0 else 1)" 2>/dev/null; then
        REDIS_PID=$($PYTHON_BIN -c "
import psutil
for c in psutil.net_connections():
    if c.laddr and c.laddr.port==6379 and c.pid:
        print(c.pid); break
" 2>/dev/null)
        log_success "Redis 已启动（PID: ${REDIS_PID}, 端口: 6379）"
    else
        log_error "Redis 启动失败"
        exit 1
    fi
fi

# ── 4b. 启动 RD-Agent Streamlit UI（因子挖掘可视化） ──
if [ "${RDAGENT_INSTALLED}" = "true" ]; then
    # 先杀掉旧进程（如果存在）
    $PYTHON_BIN -c "
import psutil, os, signal
for c in psutil.net_connections():
    if c.laddr and c.laddr.port==19899 and c.pid and c.pid != os.getpid():
        try: os.kill(c.pid, signal.SIGKILL)
        except: pass
" 2>/dev/null || true
    sleep 1
    RD_UI_PORT=19899
    # 动态查找 rdagent 包路径（不再硬编码 conda 路径）
    RDAGENT_APP_PATH=$($PYTHON_BIN -c "import rdagent, os; print(os.path.join(os.path.dirname(rdagent.__file__), 'log', 'ui', 'app.py'))" 2>/dev/null)
    if [ -z "$RDAGENT_APP_PATH" ]; then
        RDAGENT_APP_PATH="/opt/anaconda3/envs/aiquant/lib/python3.10/site-packages/rdagent/log/ui/app.py"
        log_warn "动态查找 rdagent 路径失败，使用 fallback: $RDAGENT_APP_PATH"
    fi
    nohup conda run -n aiquant streamlit run \
        "$RDAGENT_APP_PATH" \
        --server.port=${RD_UI_PORT} \
        --server.headless=true \
        --browser.serverAddress=0.0.0.0 \
        -- --log_dir "${PROJECT_ROOT}/log" \
        > /tmp/rdagent_ui.log 2>&1 &
    log_success "RD-Agent Streamlit UI 已启动 → http://localhost:${RD_UI_PORT}"
    log_info "  log_dir: ${PROJECT_ROOT}/log"
fi

# ── 4c. 启动 Celery Worker（因子进化独立执行进程，自动重启） ──
log_info "启动 Celery Worker（因子进化任务队列，崩溃自动重启）..."
# 先杀掉旧 worker（如果存在）
pkill -f "celery.*backend.worker.celery_app" 2>/dev/null || true
sleep 1

# 使用独立脚本 start_worker.sh（python -m celery，避免 conda 二进制路径/引号问题）
nohup bash "$PROJECT_ROOT/start_worker.sh" > "${PROJECT_ROOT}/logs/celery_worker.log" 2>&1 &
CELERY_PID=$!
log_success "Celery Worker 已启动（PID: ${CELERY_PID}, 队列: factor_evolution, 自动重启: 开启）"

# ── 自检：等待 Worker 就绪（5秒内应完成注册） ──
sleep 5
if kill -0 "$CELERY_PID" 2>/dev/null; then
    log_success "Celery Worker 自检通过，服务端已注册"
else
    log_error "Celery Worker 启动失败！查看日志: tail -50 logs/celery_worker.log"
    log_error "提示: 可单独运行 bash start_worker.sh 排查问题"
fi

# ── 4d. 启动 API 网关（uvicorn 单进程） ──
# 必须用 uvicorn 直接启动：main.py 依赖 nest_asyncio 补丁与大量 monkey-patch，
# gunicorn UvicornWorker 模式下 worker 会在 accept 前永久卡死（已实测验证），
# 且网关内含进程级单例（RDUIManager / RDAgentEngine / 后台任务字典），多 worker 会状态分裂。
# 长任务由 Celery Worker 承担，HTTP/SSE 请求由单进程 async 事件循环并发处理。
log_info "启动 API 网关..."
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  aiquant 系统已启动！${NC}"
echo -e "${GREEN}  Web 界面: http://127.0.0.1:8010${NC}"
echo -e "${GREEN}  API 文档: http://127.0.0.1:8010/docs${NC}"
echo -e "${GREEN}  RD-Agent UI: http://127.0.0.1:19899${NC}"
echo -e "${GREEN}  Celery Worker: PID ${CELERY_PID}${NC}"
echo -e "${GREEN}  Redis: port 6379${NC}"
echo -e "${GREEN}  运行模式: ${RUN_MODE}${NC}"
echo -e "${GREEN}  架构: API网关 + Celery任务队列 + Redis${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""

# 注册退出清理
cleanup() {
    log_info "正在停止服务..."
    if [ -n "${CELERY_PID}" ]; then
        kill "${CELERY_PID}" 2>/dev/null || true
    fi
    if [ -n "${REDIS_PID}" ]; then
        kill "${REDIS_PID}" 2>/dev/null || true
    fi
    log_info "服务已停止"
}
trap cleanup EXIT INT TERM

# 直接使用 conda env 中的 python -m uvicorn 启动
# 不用 uvicorn 二进制：二进制入口在某些 macOS 环境下响应传输异常
# 不用 conda run：会吞日志/堵 pipe
# PYTHON_BIN 已在依赖检查阶段定义
if [ -z "$PYTHON_BIN" ]; then
    log_error "python 未找到。请检查 conda 环境 aiquant"
    exit 1
fi

# --loop asyncio：必须用标准事件循环。main.py 依赖 nest_asyncio 补丁，
# 默认 uvloop 与 nest_asyncio 不兼容，会导致 StaticFiles / 流式代理请求永久挂起
# --host 127.0.0.1：macOS 下 0.0.0.0 可能导致响应传输异常（IPv6/IPv4 混淆）
# --port 8010：8008 端口在 macOS 上可能有残留 TCP 连接问题，换用 8010
nohup "$PYTHON_BIN" -m uvicorn backend.api.main:app \
    --host 127.0.0.1 \
    --port 8010 \
    --loop asyncio \
    --log-level info \
    >> "${PROJECT_ROOT}/logs/api_gateway.log" 2>&1 &
disown

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  所有服务已后台启动！${NC}"
echo -e "${GREEN}  API 网关日志: logs/api_gateway.log${NC}"
echo -e "${GREEN}  Celery 日志: logs/celery_worker.log${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
log_success "API 网关已在后台启动（PID: $!），可关闭终端继续运行"
log_info "查看日志: tail -f logs/api_gateway.log"
# 移除 cleanup trap（后台化后不再需要）
trap - EXIT INT TERM
