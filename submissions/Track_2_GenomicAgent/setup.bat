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
echo   1. Run demo:        cargo run --release
echo   2. Run benchmarks:  cargo run --release -- bench
echo.
echo For Radeon GPU optimization:
echo   1. Create Radeon Cloud account: https://radeon-global.anruicloud.com/
echo   2. Set RADEON_API_KEY environment variable
echo   3. Run: cargo run --release
echo.
pause
