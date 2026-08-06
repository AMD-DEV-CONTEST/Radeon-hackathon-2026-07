#!/usr/bin/env bash
# 全量自动化测试脚本：编译检查 + clippy + 全量测试（并行、不跳过、非失败即止总退出）。
# 任一阶段失败即以非零退出码退出，保证所有任务完成后必须全量测试全绿。
# 设计要点：
#   - --all-targets：连测试目标、二进制、bench 一起检查，无遗漏。
#   - --no-fail-fast：单个测试失败也继续跑完所有测试，确保“都跑一遍”。
#   - 不加 --quiet、不跳过 #[ignore]（本项目当前无 ignore 标记）。
#   - 默认并行：cargo test 内部按 crate 并行，单 crate 内按线程并行（-j 控制）。
#   - 失败时不立即终止后续阶段：用 RESULT 累积，最后统一判定，便于一次看到所有问题。
set -u  # 未定义变量报错（不用 set -e，因为我们要手动累积退出码）

cd "$(dirname "$0")/.." || exit 2  # 切到 workspace 根

# 优先用 nextest（更细的并行 + 更好的报告），没有则回退 cargo test。
if command -v cargo-nextest >/dev/null 2>&1; then
  USE_NEXTEST=1
else
  USE_NEXTEST=0
fi

# 颜色（非 TTY 时自动关闭）
if [ -t 1 ]; then
  G='\033[0;32m'; R='\033[0;31m'; Y='\033[0;33m'; B='\033[0;34m'; N='\033[0m'
else
  G=''; R=''; Y=''; B=''; N=''
fi

RESULT=0          # 累积退出码：0=全过，非0=有失败
FAIL_STAGES=()    # 记录失败的阶段名，便于最后汇总
PASS_STAGES=()    # 记录通过的阶段
TESTS_TOTAL=0
TESTS_FAILED=0

run_stage() {
  local name="$1"; shift
  echo -e "${B}========== [阶段] $name ==========${N}"
  if "$@"; then
    echo -e "${G}✓ $name 通过${N}"
    PASS_STAGES+=("$name")
  else
    local rc=$?
    echo -e "${R}✗ $name 失败 (exit=$rc)${N}"
    FAIL_STAGES+=("$name")
    RESULT=1
  fi
  echo
}

# 1) 编译检查（all-targets：含测试目标、bench、bin）
run_stage "cargo check (workspace, all-targets)" \
  cargo check --workspace --all-targets

# 2) clippy（all-targets + -D warnings：零警告，含中文注释规范）
run_stage "cargo clippy (workspace, all-targets, -D warnings)" \
  cargo clippy --workspace --all-targets -- -D warnings

# 3) 全量测试：并行 + 不跳过
#    nextest 更细并行（单 crate 内也并行）+ 更好失败报告；
#    cargo test 回退方案：--no-fail-fast 保证失败也跑完所有。
if [ "$USE_NEXTEST" -eq 1 ]; then
  run_stage "cargo nextest run (workspace, --no-fail-fast, 并行)" \
    cargo nextest run --workspace --no-fail-fast
  # nextest 不跑 doc-tests，单独补一个
  run_stage "cargo test --doc (workspace)" \
    cargo test --workspace --doc --no-fail-fast
else
  run_stage "cargo test (workspace, all-targets, --no-fail-fast)" \
    cargo test --workspace --all-targets --no-fail-fast
fi

# 4) release 编译（确认 release profile 也通过；panic=abort 不影响）
run_stage "cargo build --release (workspace bins)" \
  cargo build --release --bins

echo -e "${B}========== [汇总] ==========${N}"
echo -e "通过阶段: ${G}${PASS_STAGES[*]:-无}${N}"
echo -e "失败阶段: ${R}${FAIL_STAGES[*]:-无}${N}"

if [ "$RESULT" -eq 0 ]; then
  echo -e "${G}全量测试通过：所有阶段全绿。${N}"
  exit 0
else
  echo -e "${R}全量测试未通过：见上方失败阶段。任务未完成。${N}"
  exit 1
fi
