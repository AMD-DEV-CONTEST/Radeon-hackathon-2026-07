@echo off
REM Quick verification for judges/reviewers -- runs the three checks that
REM back this submission's core claims, in order, stopping at the first
REM failure. Default build only: no API keys, no network, no GPU toolchain
REM beyond a Vulkan driver, no model download.
REM
REM   1. builds clean (release profile)
REM   2. 42 property-based tests pass
REM   3. the 6-query demo runs fully offline (GPU BM25 routing, no LLM)
REM
REM Usage:  verify.bat

setlocal
cd /d "%~dp0"

echo ------------------------------------------------------------
echo genomic-agent quick verification
echo (default build -- no API keys, no network, no model download)
echo ------------------------------------------------------------

echo [1/3] Building (cargo build --release)...
cargo build --release
if errorlevel 1 goto :failed
echo     OK: build succeeded
echo.

echo [2/3] Running tests (cargo test --release)...
cargo test --release
if errorlevel 1 goto :failed
echo     OK: tests passed
echo.

echo [3/3] Running the offline demo (cargo run --release -- fast)...
echo       6 queries, routed by the GPU BM25 kernel, no LLM/network.
cargo run --release -- fast
if errorlevel 1 goto :failed
echo     OK: demo completed
echo.

echo ------------------------------------------------------------
echo All three checks passed.
echo See README_PROFESSIONAL.md sections 4-5 for gpu-bench and
echo the optional local-inference feature.
echo ------------------------------------------------------------
exit /b 0

:failed
echo.
echo VERIFICATION FAILED at the step above. See README_PROFESSIONAL.md
echo section 9 (Troubleshooting).
exit /b 1
