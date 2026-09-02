@echo off
REM Setup script for Genomic Research Agent (Windows)

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║   Genomic Research Agent - Setup Script (Windows)          ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

REM Check for Rust
where rustc >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Rust is not installed. Install from: https://rustup.rs/
    pause
    exit /b 1
)

echo ✓ Rust detected
rustc --version
echo.

REM Check for Cargo
where cargo >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Cargo is not found. Please reinstall Rust.
    pause
    exit /b 1
)

echo ✓ Cargo detected
cargo --version
echo.

echo ────────────────────────────────────────────────────────────
echo Building project...
echo ────────────────────────────────────────────────────────────
echo.

cargo build --release

if %ERRORLEVEL% NEQ 0 (
    echo ❌ Build failed
    pause
    exit /b 1
)

echo.
echo ✓ Build complete!
echo.
echo ────────────────────────────────────────────────────────────
echo Setup complete! Ready to run.
echo ────────────────────────────────────────────────────────────
echo.
echo Quick start commands:
echo   1. Run demo (synthetic data):        cargo run --release
echo   2. Run demo (real 1000 Genomes data): set GENOMIC_AGENT_REAL_DATA=1 ^&^& cargo run --release
echo   3. Run benchmarks:                    cargo run --release -- bench
echo   4. Run GPU benchmark + cross-check:   cargo run --release -- gpu-bench
echo.
echo This build has real GPU acceleration (wgpu/Vulkan, explicitly AMD-
echo adapter-targeted) for LD, PCA, and tool-planning compute -- not the
echo literal ROCm/HIP API, and not RADEON_API_KEY, which is not read
echo anywhere in src/. See README_PROFESSIONAL.md section 5 for exactly
echo what that means and doesn't mean.
echo.
pause
