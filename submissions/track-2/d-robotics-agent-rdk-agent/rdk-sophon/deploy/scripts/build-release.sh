#!/usr/bin/env bash
# 编译 release 二进制到 aarch64（板端目标平台）。
# 本脚本在开发机（Mac）上运行，交叉编译产出可在 RDK 板端直接运行的静态/动态二进制。
# 产物：target/aarch64-unknown-linux-gnu/release/{probe-daemon,sophonctl,probe-http-gateway,probe-ws-outbound}
# 用法：./deploy/scripts/build-release.sh [--skip-checks]
set -euo pipefail

# 切到仓库根
cd "$(dirname "$0")/../.." || exit 2

# 探测 cargo 环境：非交互 shell 可能没 source ~/.cargo/env。
if ! command -v cargo >/dev/null 2>&1; then
  if [ -f "$HOME/.cargo/env" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.cargo/env"
  elif [ -d "$HOME/.cargo/bin" ]; then
    export PATH="$HOME/.cargo/bin:$PATH"
  fi
fi
if ! command -v cargo >/dev/null 2>&1; then
  echo "错误：找不到 cargo。请先装 Rust（https://rustup.rs）。" >&2
  exit 1
fi

TARGET="aarch64-unknown-linux-gnu"
BINS=("probe-daemon" "sophonctl" "probe-http-gateway" "probe-ws-outbound")
SKIP_CHECKS=0

# 解析参数
for arg in "$@"; do
  case "$arg" in
    --skip-checks) SKIP_CHECKS=1 ;;
    -h|--help)
      echo "用法: $0 [--skip-checks]"
      echo "  --skip-checks  跳过全量测试与 clippy（用于快速出包，不建议常规用）"
      exit 0
      ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

# 颜色
if [ -t 1 ]; then
  G='\033[0;32m'; R='\033[0;31m'; B='\033[0;34m'; N='\033[0m'
else G=''; R=''; B=''; N=''; fi

echo -e "${B}========== [1/4] 安装 aarch64 target ==========${N}"
# rustup 默认装到当前 toolchain，幂等。
rustup target add "$TARGET"
echo

echo -e "${B}========== [2/4] 全量测试 + clippy（确保出包前全绿） ==========${N}"
if [ "$SKIP_CHECKS" -eq 1 ]; then
  echo -e "${R}--skip-checks 跳过测试，直接编译（产物质量自负）${N}"
else
  # 跑全量测试脚本（check+clippy+test+release build），非零退出。
  ./scripts/full_test.sh
fi
echo

echo -e "${B}========== [3/4] 交叉编译 release（$TARGET） ==========${N}"
# 需要一个 aarch64-linux-gnu 的 linker。Mac 上推荐用 zigbuild（自带链接器）。
if command -v cargo-zigbuild >/dev/null 2>&1; then
  echo "检测到 cargo-zigbuild，用它交叉编译（Mac 上免配交叉链接器）。"
  for bin in "${BINS[@]}"; do
    echo -e "${B}  编译 $bin${N}"
    cargo zigbuild --release --target "$TARGET" --bin "$bin"
  done
else
  echo "未检测到 cargo-zigbuild，尝试直接 cargo build（需系统有 aarch64-linux-gnu 链接器）。"
  echo "若失败，Mac 上装 zigbuild：cargo install cargo-zigbuild && brew install zig"
  for bin in "${BINS[@]}"; do
    echo -e "${B}  编译 $bin${N}"
    cargo build --release --target "$TARGET" --bin "$bin"
  done
fi
echo

echo -e "${B}========== [4/4] 产物清单 ==========${N}"
OUT_DIR="target/$TARGET/release"
for bin in "${BINS[@]}"; do
  if [ -f "$OUT_DIR/$bin" ]; then
    SIZE=$(du -h "$OUT_DIR/$bin" | cut -f1)
    echo -e "${G}✓ $bin  ($SIZE)  → $OUT_DIR/$bin${N}"
  else
    echo -e "${R}✗ $bin 缺失${N}"
    exit 1
  fi
done
echo
echo -e "${G}编译完成。下一步：./deploy/scripts/deploy-to-board.sh <board-host>${N}"
