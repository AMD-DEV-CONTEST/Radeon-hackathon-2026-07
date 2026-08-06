#!/usr/bin/env bash
# =============================================================================
# E-Sentinel Full Test Runner
# Runs unit tests, integration tests, TypeScript check, and lint in sequence.
# Usage: bash scripts/run-all-tests.sh [options]
#
# Options:
#   --unit          Run unit tests only
#   --integration   Run integration tests only
#   --coverage      Run all tests with coverage report
#   --ci            CI mode — fails fast, generates coverage JSON
#   --watch         Run tests in watch mode (unit only)
#   --no-lint       Skip ESLint
#   --no-tsc        Skip TypeScript type check
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

UNIT_ONLY=false
INTEGRATION_ONLY=false
COVERAGE=false
CI_MODE=false
WATCH_MODE=false
SKIP_LINT=false
SKIP_TSC=false

for arg in "$@"; do
  case $arg in
    --unit) UNIT_ONLY=true ;;
    --integration) INTEGRATION_ONLY=true ;;
    --coverage) COVERAGE=true ;;
    --ci) CI_MODE=true ;;
    --watch) WATCH_MODE=true ;;
    --no-lint) SKIP_LINT=true ;;
    --no-tsc) SKIP_TSC=true ;;
    --help)
      echo "Usage: bash scripts/run-all-tests.sh [options]"
      echo ""
      echo "Options:"
      echo "  --unit           Run unit tests only"
      echo "  --integration    Run integration tests only"
      echo "  --coverage       Run all tests with coverage report"
      echo "  --ci             CI mode (fails fast, coverage JSON)"
      echo "  --watch          Watch mode (unit tests only)"
      echo "  --no-lint        Skip ESLint"
      echo "  --no-tsc         Skip TypeScript type check"
      exit 0
      ;;
  esac
done

PASSED=0
FAILED=0

report_step() {
  local step="$1"
  local status="$2"
  if [ "$status" -eq 0 ]; then
    echo -e "${GREEN}[PASS]${NC} $step"
    PASSED=$((PASSED + 1))
  else
    echo -e "${RED}[FAIL]${NC} $step"
    FAILED=$((FAILED + 1))
  fi
}

echo "============================================"
echo "  E-Sentinel Test Suite"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"
echo ""

# ---- TypeScript Type Check ----
if [ "$SKIP_TSC" = false ]; then
  echo -e "${YELLOW}[1/4] TypeScript type check...${NC}"
  if npx tsc --noEmit 2>&1; then
    report_step "tsc --noEmit" 0
  else
    report_step "tsc --noEmit" 1
    if [ "$CI_MODE" = true ]; then
      echo -e "${RED}TypeScript errors found. Aborting CI run.${NC}"
      exit 1
    fi
  fi
  echo ""
fi

# ---- Lint ----
if [ "$SKIP_LINT" = false ] && [ "$INTEGRATION_ONLY" = false ] && [ "$UNIT_ONLY" = false ]; then
  echo -e "${YELLOW}[2/4] ESLint...${NC}"
  if npx eslint src/ --quiet 2>&1; then
    report_step "eslint" 0
  else
    report_step "eslint" 1
  fi
  echo ""
fi

# ---- Unit Tests ----
if [ "$WATCH_MODE" = true ]; then
  echo -e "${YELLOW}[Tests] Running unit tests in watch mode...${NC}"
  npx jest --testPathPatterns='src/lib/__tests__/' --watch
  exit 0
fi

if [ "$INTEGRATION_ONLY" = false ]; then
  echo -e "${YELLOW}[3/4] Unit tests...${NC}"
  if npx jest --testPathPatterns='src/lib/__tests__/' --no-coverage 2>&1; then
    report_step "unit tests" 0
  else
    report_step "unit tests" 1
    if [ "$CI_MODE" = true ]; then
      echo -e "${RED}Unit tests failed. Aborting CI run.${NC}"
      exit 1
    fi
  fi
  echo ""
fi

# ---- Integration Tests ----
if [ "$UNIT_ONLY" = false ]; then
  echo -e "${YELLOW}[4/4] Integration tests...${NC}"
  if npx jest --testPathPatterns='src/app/api/__tests__/' --no-coverage 2>&1; then
    report_step "integration tests" 0
  else
    report_step "integration tests" 1
  fi
  echo ""
fi

# ---- Coverage (optional) ----
if [ "$COVERAGE" = true ] || [ "$CI_MODE" = true ]; then
  echo -e "${YELLOW}[Coverage] Generating coverage report...${NC}"
  COV_ARGS="--coverage"
  if [ "$CI_MODE" = true ]; then
    COV_ARGS="$COV_ARGS --ci --maxWorkers=2 --coverageReporters=json --coverageReporters=text"
  fi
  npx jest $COV_ARGS 2>&1
  echo ""
fi

# ---- Summary ----
echo "============================================"
TOTAL=$((PASSED + FAILED))
echo "  Results: $PASSED passed, $FAILED failed ($TOTAL total)"
if [ "$FAILED" -gt 0 ]; then
  echo -e "  Status:  ${RED}FAILED${NC}"
  exit 1
else
  echo -e "  Status:  ${GREEN}ALL PASSED${NC}"
fi
echo "============================================"
