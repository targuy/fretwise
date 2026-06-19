#!/usr/bin/env bash
# validate_p0.sh — P0 fix validation suite
# Usage: bash scripts/validate_p0.sh [--fast]
#
# Compatible with git-bash on Windows and bash on Linux/macOS.
# Runs lint, type checks, and targeted pytest suites for the P0 notation fixes.

set -euo pipefail

FAST=0
for arg in "$@"; do
  [[ "$arg" == "--fast" ]] && FAST=1
done

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
GREEN="\033[0;32m"
RED="\033[0;31m"
YELLOW="\033[0;33m"
RESET="\033[0m"
BOLD="\033[1m"

pass() { echo -e "  ${GREEN}[PASS]${RESET} $*"; }
fail() { echo -e "  ${RED}[FAIL]${RESET} $*"; }
info() { echo -e "  ${YELLOW}[INFO]${RESET} $*"; }
header() { echo -e "\n${BOLD}=== $* ===${RESET}"; }

# ---------------------------------------------------------------------------
# Detect Python executable (Windows git-bash vs Linux)
# ---------------------------------------------------------------------------
if [[ -f ".venv/Scripts/python.exe" ]]; then
  PYTHON=".venv/Scripts/python.exe"
elif [[ -f ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
else
  echo -e "${RED}ERROR: Virtual environment not found.${RESET}"
  echo "  Expected: .venv/Scripts/python.exe (Windows) or .venv/bin/python (Linux)"
  echo "  Run: python -m venv .venv && pip install -e '.[dev]'"
  exit 1
fi

header "FretWise P0 Validation Suite"
echo "  Python : $PYTHON"
echo "  Branch : $(git branch --show-current 2>/dev/null || echo '(unknown)')"
echo "  Date   : $(date '+%Y-%m-%d %H:%M:%S')"

OVERALL=0   # 0 = all good; 1 = at least one failure

# ---------------------------------------------------------------------------
# P0 source files
# ---------------------------------------------------------------------------
P0_LINT_FILES=(
  "src/fretwise/core/layout/rules.py"
  "src/fretwise/core/canonical/mappers.py"
  "src/fretwise/core/ingest/models.py"
)
P0_MYPY_FILES=(
  "src/fretwise/core/layout/rules.py"
  "src/fretwise/core/canonical/mappers.py"
)

# Filter to files that actually exist (worktrees may be partial)
EXISTING_LINT_FILES=()
for f in "${P0_LINT_FILES[@]}"; do
  [[ -f "$f" ]] && EXISTING_LINT_FILES+=("$f")
done

EXISTING_MYPY_FILES=()
for f in "${P0_MYPY_FILES[@]}"; do
  [[ -f "$f" ]] && EXISTING_MYPY_FILES+=("$f")
done

# ---------------------------------------------------------------------------
# 1. Ruff lint — P0 files
# ---------------------------------------------------------------------------
header "1/5  Ruff lint (P0 files)"
if [[ ${#EXISTING_LINT_FILES[@]} -eq 0 ]]; then
  info "No P0 source files present yet — skipping lint"
else
  echo "  Files: ${EXISTING_LINT_FILES[*]}"
  if "$PYTHON" -m ruff check "${EXISTING_LINT_FILES[@]}" --select E,W,F 2>&1; then
    pass "ruff — clean"
  else
    fail "ruff — lint errors found"
    OVERALL=1
  fi
fi

# ---------------------------------------------------------------------------
# 2. mypy — P0 files
# ---------------------------------------------------------------------------
header "2/5  mypy type check (P0 files)"
if [[ ${#EXISTING_MYPY_FILES[@]} -eq 0 ]]; then
  info "No P0 source files present yet — skipping mypy"
else
  echo "  Files: ${EXISTING_MYPY_FILES[*]}"
  if "$PYTHON" -m mypy "${EXISTING_MYPY_FILES[@]}" --ignore-missing-imports 2>&1; then
    pass "mypy — no type errors"
  else
    fail "mypy — type errors found"
    OVERALL=1
  fi
fi

# ---------------------------------------------------------------------------
# 3. P0-specific test suites (may not exist yet)
# ---------------------------------------------------------------------------
header "3/5  P0 targeted tests (P0-B & P0-C)"
P0_TEST_CMD=(
  "$PYTHON" -m pytest
  tests/test_p0b_pitch_to_staff.py
  tests/test_p0c_per_measure_timesig.py
  -v --tb=short
)
# Redirect stderr to suppress "file not found" noise when tests don't exist yet
if "$PYTHON" -m pytest \
     tests/test_p0b_pitch_to_staff.py \
     tests/test_p0c_per_measure_timesig.py \
     -v --tb=short 2>/dev/null; then
  pass "P0-B/P0-C tests — all GREEN"
else
  EXIT_CODE=$?
  if [[ $EXIT_CODE -eq 4 ]]; then
    # pytest exit 4 = no tests collected (files missing)
    info "P0 tests not yet present — OK (will fail after dev delivers)"
  else
    fail "P0-B/P0-C tests — failures detected (exit $EXIT_CODE)"
    OVERALL=1
  fi
fi

# ---------------------------------------------------------------------------
# 4. Existing core test suites (run only if files exist)
# ---------------------------------------------------------------------------
header "4/5  Core regression tests"
CORE_TEST_FILES=(
  "tests/test_core_canonical.py"
  "tests/test_core_layout.py"
  "tests/test_core_layout_rules.py"
)
EXISTING_CORE_TESTS=()
for f in "${CORE_TEST_FILES[@]}"; do
  [[ -f "$f" ]] && EXISTING_CORE_TESTS+=("$f")
done

if [[ ${#EXISTING_CORE_TESTS[@]} -eq 0 ]]; then
  info "No core test files found — skipping"
else
  echo "  Running: ${EXISTING_CORE_TESTS[*]}"
  FAST_FLAG=""
  [[ $FAST -eq 1 ]] && FAST_FLAG="--no-header -q"
  if "$PYTHON" -m pytest "${EXISTING_CORE_TESTS[@]}" -v --tb=short $FAST_FLAG 2>&1; then
    pass "Core tests — all GREEN"
  else
    fail "Core tests — regressions detected"
    OVERALL=1
  fi
fi

# ---------------------------------------------------------------------------
# 5. Full suite smoke check (skipped in --fast mode)
# ---------------------------------------------------------------------------
header "5/5  Full suite smoke check"
if [[ $FAST -eq 1 ]]; then
  info "--fast mode: skipping full suite"
else
  if "$PYTHON" -m pytest --tb=no -q 2>&1 | tail -3; then
    LAST_LINE=$("$PYTHON" -m pytest --tb=no -q 2>&1 | tail -1)
    if echo "$LAST_LINE" | grep -qE "^[0-9]+ passed|passed"; then
      pass "Full suite — no new failures"
    else
      fail "Full suite — failures present (check output above)"
      OVERALL=1
    fi
  else
    fail "Full suite — pytest exited non-zero"
    OVERALL=1
  fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}========================================${RESET}"
if [[ $OVERALL -eq 0 ]]; then
  echo -e "${GREEN}${BOLD}  ALL CHECKS PASSED${RESET}"
else
  echo -e "${RED}${BOLD}  SOME CHECKS FAILED — see output above${RESET}"
fi
echo -e "${BOLD}========================================${RESET}"
echo ""

exit $OVERALL
