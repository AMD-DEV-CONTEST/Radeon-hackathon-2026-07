#!/usr/bin/env bash
# 将 rdk-agent 复制到用户级应用目录，安装生产依赖，并注册 rdk-agent 命令。
#
# 用法：./deploy/install-rdk-agent.sh [选项]
#   --install-dir <dir>  应用安装目录（默认 ~/.local/share/rdk-agent）
#   --bin-dir <dir>      命令安装目录（默认 ~/.local/bin）
#   --config-dir <dir>   可编辑配置目录（默认 ~/.config/rdk-agent）
#   --refresh-config     备份后覆盖包内同名静态配置（不删除额外文件），保留运行时 servo-control
#   -h, --help           显示帮助
#
# 也可通过 npm 调用：npm run deploy -- [选项]
set -euo pipefail

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
USER_HOME="${HOME:?无法确定用户家目录}"
INSTALL_DIR="$USER_HOME/.local/share/rdk-agent"
BIN_DIR="$USER_HOME/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-$USER_HOME/.config}/rdk-agent"
REFRESH_CONFIG=0

while [ $# -gt 0 ]; do
  case "$1" in
    --install-dir)
      INSTALL_DIR="${2:?--install-dir 需要参数}"
      shift 2
      ;;
    --bin-dir)
      BIN_DIR="${2:?--bin-dir 需要参数}"
      shift 2
      ;;
    --config-dir)
      CONFIG_DIR="${2:?--config-dir 需要参数}"
      shift 2
      ;;
    --refresh-config)
      REFRESH_CONFIG=1
      shift
      ;;
    -h|--help)
      sed -n '2,11p' "$0" | sed 's/^# *//'
      exit 0
      ;;
    *)
      echo "未知参数: $1（用 -h 查看帮助）" >&2
      exit 2
      ;;
  esac
done

while [ "$CONFIG_DIR" != "/" ] && [ "${CONFIG_DIR%/}" != "$CONFIG_DIR" ]; do
  CONFIG_DIR="${CONFIG_DIR%/}"
done

case "$INSTALL_DIR" in
  ""|/|"$USER_HOME")
    echo "错误：不安全的安装目录 '$INSTALL_DIR'" >&2
    exit 2
    ;;
esac
case "$CONFIG_DIR" in
  ""|/|"$USER_HOME")
    echo "错误：不安全的配置目录 '$CONFIG_DIR'" >&2
    exit 2
    ;;
esac

if ! command -v node >/dev/null 2>&1; then
  echo "错误：找不到 Node.js；Pi SDK 要求 Node.js >= 22.19.0。" >&2
  exit 1
fi
if ! node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 19) ? 0 : 1)'; then
  echo "错误：当前 Node.js 为 $(node --version)，Pi SDK 要求 >= 22.19.0。" >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "错误：找不到 npm。" >&2
  exit 1
fi

if [ -t 1 ]; then
  GREEN='\033[0;32m'
  BLUE='\033[0;34m'
  YELLOW='\033[0;33m'
  RESET='\033[0m'
else
  GREEN=''
  BLUE=''
  YELLOW=''
  RESET=''
fi

TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/rdk-agent-deploy.XXXXXX")"
STAGED_APP="$TEMP_DIR/app"
BACKUP_DIR="${INSTALL_DIR}.backup.$$"
DEPLOYED=0
CONFIG_WAS_DEFAULT=0
INSTALL_CHANGE_STARTED=0
CONFIG_REFRESH_BACKUP=""
CONFIG_REFRESH_STARTED=0
CONFIG_AUTO_UPGRADE_BACKUP="$TEMP_DIR/config.before-default-upgrade"
CONFIG_AUTO_UPGRADE_STARTED=0
CONFIG_CREATION_STARTED=0
RETIRED_DEFAULT_ACTIONS_REGISTRY_RELATIVE_PATH="templates/magicbox-servo/examples/plugins/servo/servo_actions/actions.json"
RETIRED_DEFAULT_ACTIONS_REGISTRY="$TEMP_DIR/actions.json.retired-default"
printf '%s\n' \
  '{' \
  '  "version": 1,' \
  '  "actions": {}' \
  '}' > "$RETIRED_DEFAULT_ACTIONS_REGISTRY"

# 早期版本曾把空 actions.json 作为模板静态文件发布。后续动作包以各自的
# registry.json 为准，因此只迁移与历史默认文件逐字节一致的残留；任何内容
# 或格式变化都视为用户定制，不能忽略或删除。
remove_retired_default_actions_registry() {
  local directory="$1"
  local candidate="$directory/$RETIRED_DEFAULT_ACTIONS_REGISTRY_RELATIVE_PATH"

  if [ -f "$candidate" ] && cmp -s "$candidate" "$RETIRED_DEFAULT_ACTIONS_REGISTRY"; then
    rm -f "$candidate"
    return 0
  fi
  return 1
}

# 返回可用于默认配置比较的 agents.yaml。这里只消除安装器自身做过的
# 精确历史迁移，不能归一化提示词、工具或其他字段，否则可能覆盖用户定制。
normalize_agent_config() {
  awk '
    /^[[:space:]]+validation:[[:space:]]*$/ {
      pending_validation = $0
      next
    }
    pending_validation != "" {
      if ($0 ~ /^[[:space:]]+kind:[[:space:]]+servo-python-test[[:space:]]*$/) {
        pending_validation = ""
        next
      }
      print pending_validation
      pending_validation = ""
    }
    { print }
    END {
      if (pending_validation != "") print pending_validation
    }
  ' "$1" > "$2"
}

# 从配置副本中移除明确的运行时产物，剩余内容都视为用户可定制的静态配置。
prepare_static_config_compare() {
  local directory="$1"
  local normalized_agents="$directory/agents.yaml.normalized"

  rm -f \
    "$directory/agents.yaml.v2.example" \
    "$directory/agents.yaml.before-servo-python-test-migration"
  rm -rf "$directory/skills/servo-control"
  if [ -d "$directory/skills" ]; then
    find "$directory/skills" -mindepth 1 -maxdepth 1 -type d -name '.servo-control*.bak' -exec rm -rf -- {} +
  fi
  find "$directory" -type d -name '__pycache__' -exec rm -rf -- {} +
  find "$directory" -type f -name '*.pyc' -delete
  remove_retired_default_actions_registry "$directory" || true

  if [ -f "$directory/agents.yaml" ]; then
    normalize_agent_config "$directory/agents.yaml" "$normalized_agents"
    mv "$normalized_agents" "$directory/agents.yaml"
  fi
}

install_bundled_config_preserving_runtime() {
  local runtime_servo_control="$CONFIG_DIR/skills/servo-control"
  local runtime_servo_control_backup="$TEMP_DIR/servo-control.runtime"
  local runtime_servo_control_present=0

  if [ -d "$runtime_servo_control" ]; then
    cp -R "$runtime_servo_control" "$runtime_servo_control_backup"
    runtime_servo_control_present=1
  fi
  cp -R "$INSTALL_DIR/config/." "$CONFIG_DIR/"
  if [ "$runtime_servo_control_present" -eq 1 ]; then
    rm -rf "$runtime_servo_control"
    mkdir -p "$CONFIG_DIR/skills"
    cp -R "$runtime_servo_control_backup" "$runtime_servo_control"
    echo -e "${GREEN}✓ 已保留运行时 servo-control Skill${RESET}"
  fi
  if remove_retired_default_actions_registry "$CONFIG_DIR"; then
    echo -e "${GREEN}✓ 已移除旧版默认空 actions.json${RESET}"
  fi
}

cleanup() {
  local exit_code=$?
  trap - EXIT

  if [ "$DEPLOYED" -ne 1 ] && [ "$CONFIG_REFRESH_STARTED" -eq 1 ] && [ -d "$CONFIG_REFRESH_BACKUP" ]; then
    if rm -rf "$CONFIG_DIR" && cp -R "$CONFIG_REFRESH_BACKUP" "$CONFIG_DIR"; then
      echo "部署失败：已从 $CONFIG_REFRESH_BACKUP 自动恢复配置；完整备份仍保留。" >&2
    else
      echo "错误：自动恢复配置失败；完整备份仍位于 $CONFIG_REFRESH_BACKUP，请手动恢复。" >&2
    fi
  elif [ "$DEPLOYED" -ne 1 ] && [ "$CONFIG_AUTO_UPGRADE_STARTED" -eq 1 ] && [ -d "$CONFIG_AUTO_UPGRADE_BACKUP" ]; then
    if rm -rf "$CONFIG_DIR" && cp -R "$CONFIG_AUTO_UPGRADE_BACKUP" "$CONFIG_DIR"; then
      echo "部署失败：已自动恢复升级前的默认配置。" >&2
    else
      echo "错误：自动恢复升级前的默认配置失败。" >&2
    fi
  elif [ "$DEPLOYED" -ne 1 ] && [ "$CONFIG_CREATION_STARTED" -eq 1 ]; then
    rm -rf "$CONFIG_DIR"
  fi

  if [ "$DEPLOYED" -ne 1 ] && [ -e "$BACKUP_DIR" ]; then
    if ! rm -rf "$INSTALL_DIR" || ! mv "$BACKUP_DIR" "$INSTALL_DIR"; then
      echo "错误：自动恢复应用目录失败；旧应用仍位于 $BACKUP_DIR。" >&2
    fi
  elif [ "$DEPLOYED" -ne 1 ] && [ "$INSTALL_CHANGE_STARTED" -eq 1 ]; then
    rm -rf "$INSTALL_DIR"
  fi
  rm -rf "$TEMP_DIR"
  exit "$exit_code"
}
trap cleanup EXIT

echo -e "${BLUE}========== [1/4] 校验 rdk-agent ==========${RESET}"
node --experimental-strip-types --check "$PROJECT_DIR/src/api/tui/main.ts"
echo -e "${GREEN}✓ Node.js $(node --version)，入口语法检查通过${RESET}"

echo -e "${BLUE}========== [2/4] 准备生产包 ==========${RESET}"
mkdir -p "$STAGED_APP/bin"
cp "$PROJECT_DIR/package.json" "$PROJECT_DIR/package-lock.json" "$STAGED_APP/"
cp -R "$PROJECT_DIR/src" "$PROJECT_DIR/config" "$STAGED_APP/"
# TUI 的 Skill 原子部署会在源码配置旁保留回滚备份；Python 运行也可能
# 生成字节码缓存。这些运行时产物不能进入用户安装包。
find "$STAGED_APP/config/skills" -mindepth 1 -maxdepth 1 -type d -name '.servo-control*.bak' -exec rm -rf -- {} +
find "$STAGED_APP/config" -type d -name '__pycache__' -exec rm -rf -- {} +
find "$STAGED_APP/config" -type f -name '*.pyc' -delete
cp "$PROJECT_DIR/README.md" "$STAGED_APP/"
install -m 0755 "$PROJECT_DIR/deploy/rdk-agent" "$STAGED_APP/bin/rdk-agent"
printf '%s\n' "$CONFIG_DIR" > "$STAGED_APP/config-path"
(
  cd "$STAGED_APP"
  npm ci --omit=dev --ignore-scripts
)
echo -e "${GREEN}✓ 生产依赖安装完成${RESET}"

echo -e "${BLUE}========== [3/4] 安装应用 ==========${RESET}"
if [ -d "$CONFIG_DIR" ] && [ -d "$INSTALL_DIR/config" ]; then
  ACTIVE_CONFIG_COMPARE="$TEMP_DIR/config.active.compare"
  INSTALLED_CONFIG_COMPARE="$TEMP_DIR/config.installed.compare"
  cp -R "$CONFIG_DIR" "$ACTIVE_CONFIG_COMPARE"
  cp -R "$INSTALL_DIR/config" "$INSTALLED_CONFIG_COMPARE"
  prepare_static_config_compare "$ACTIVE_CONFIG_COMPARE"
  prepare_static_config_compare "$INSTALLED_CONFIG_COMPARE"
  if diff -qr "$ACTIVE_CONFIG_COMPARE" "$INSTALLED_CONFIG_COMPARE" >/dev/null 2>&1; then
    CONFIG_WAS_DEFAULT=1
  fi
fi

if [ "$REFRESH_CONFIG" -eq 1 ] && [ -e "$CONFIG_DIR" ]; then
  if [ ! -d "$CONFIG_DIR" ]; then
    echo "错误：配置路径不是目录，无法安全刷新：$CONFIG_DIR" >&2
    exit 2
  fi
  CONFIG_BACKUP_TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
  CONFIG_REFRESH_BACKUP="${CONFIG_DIR}.backup.${CONFIG_BACKUP_TIMESTAMP}"
  CONFIG_BACKUP_SUFFIX=0
  while [ -e "$CONFIG_REFRESH_BACKUP" ]; do
    CONFIG_BACKUP_SUFFIX=$((CONFIG_BACKUP_SUFFIX + 1))
    CONFIG_REFRESH_BACKUP="${CONFIG_DIR}.backup.${CONFIG_BACKUP_TIMESTAMP}.${CONFIG_BACKUP_SUFFIX}"
  done
  cp -R "$CONFIG_DIR" "$CONFIG_REFRESH_BACKUP"
  echo -e "${GREEN}✓ 刷新前配置已完整备份到 $CONFIG_REFRESH_BACKUP${RESET}"
fi

mkdir -p "$(dirname -- "$INSTALL_DIR")"
if [ -e "$INSTALL_DIR" ]; then
  mv "$INSTALL_DIR" "$BACKUP_DIR"
fi
INSTALL_CHANGE_STARTED=1
mv "$STAGED_APP" "$INSTALL_DIR"
echo -e "${GREEN}✓ 应用已安装到 $INSTALL_DIR${RESET}"
if [ ! -e "$CONFIG_DIR" ]; then
  mkdir -p "$(dirname -- "$CONFIG_DIR")"
  CONFIG_CREATION_STARTED=1
  cp -R "$INSTALL_DIR/config" "$CONFIG_DIR"
  echo -e "${GREEN}✓ 可编辑配置已初始化到 $CONFIG_DIR${RESET}"
elif [ "$REFRESH_CONFIG" -eq 1 ]; then
  CONFIG_REFRESH_STARTED=1
  install_bundled_config_preserving_runtime
  echo -e "${GREEN}✓ 已覆盖包内同名静态配置（未删除额外文件）；完整旧配置可从 $CONFIG_REFRESH_BACKUP 恢复${RESET}"
elif [ "$CONFIG_WAS_DEFAULT" -eq 1 ]; then
  cp -R "$CONFIG_DIR" "$CONFIG_AUTO_UPGRADE_BACKUP"
  CONFIG_AUTO_UPGRADE_STARTED=1
  install_bundled_config_preserving_runtime
  echo -e "${GREEN}✓ 未修改的默认配置已升级到最新版本${RESET}"
else
  echo -e "${YELLOW}保留已有配置：$CONFIG_DIR${RESET}"
  cp "$INSTALL_DIR/config/agents.yaml" "$CONFIG_DIR/agents.yaml.v2.example"
  echo -e "${YELLOW}新的双模式配置已写入 $CONFIG_DIR/agents.yaml.v2.example，请手动合并自定义内容${RESET}"
fi

# 早期 v2 默认配置曾在 python-test 下写入一个从未成为运行时合同的
# servo-python-test validation。只删除这个精确的两行历史块，保留用户对
# 提示词、工具、Skill 和其他 validation 的全部定制。
ACTIVE_AGENT_CONFIG="$CONFIG_DIR/agents.yaml"
MIGRATED_AGENT_CONFIG="$TEMP_DIR/agents.yaml.migrated"
if [ -f "$ACTIVE_AGENT_CONFIG" ]; then
  normalize_agent_config "$ACTIVE_AGENT_CONFIG" "$MIGRATED_AGENT_CONFIG"
  if ! cmp -s "$ACTIVE_AGENT_CONFIG" "$MIGRATED_AGENT_CONFIG"; then
    cp "$ACTIVE_AGENT_CONFIG" "$CONFIG_DIR/agents.yaml.before-servo-python-test-migration"
    mv "$MIGRATED_AGENT_CONFIG" "$ACTIVE_AGENT_CONFIG"
    echo -e "${GREEN}✓ 已迁移旧版 servo-python-test 配置；原文件已备份${RESET}"
  fi
fi

echo -e "${BLUE}========== [4/4] 注册命令 ==========${RESET}"
mkdir -p "$BIN_DIR"
if [ ! -w "$BIN_DIR" ]; then
  echo "错误：$BIN_DIR 不可写；请通过 --bin-dir 指定用户可写目录。" >&2
  exit 1
fi
ln -sfn "$INSTALL_DIR/bin/rdk-agent" "$BIN_DIR/rdk-agent"
rm -rf "$BACKUP_DIR"
DEPLOYED=1
echo -e "${GREEN}✓ 命令已安装到 $BIN_DIR/rdk-agent${RESET}"

if ! case ":$PATH:" in *":$BIN_DIR:"*) true ;; *) false ;; esac; then
  echo -e "${YELLOW}提示：$BIN_DIR 尚未加入 PATH。请将下面一行写入 shell 配置：${RESET}"
  echo "  export PATH=\"$BIN_DIR:\$PATH\""
fi

echo
echo -e "${GREEN}部署完成。${RESET}"
echo "运行: rdk-agent"
echo "仓库贡献者模式: rdk-agent --workspace /path/to/rdk-sophon"
echo "配置: $CONFIG_DIR/agents.yaml"
