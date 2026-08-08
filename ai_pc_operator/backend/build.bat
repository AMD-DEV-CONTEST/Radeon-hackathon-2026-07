@echo off
REM build.bat — Build the Screen-AI native C core as a DLL.
REM Usage: Run from the ai_pc_operator/backend/ directory.
REM
REM Requirements: gcc (MinGW or MSYS2) on PATH.

setlocal

set SRC=%~dp0native\screenai_core.c
set HEADERS=%~dp0native\screenai_core.h
set OUT_DIR=%~dp0native
set OUT_DLL=%OUT_DIR%\screenai_core.dll
set OUT_DEF=%OUT_DIR%\screenai_core.def
set OUT_LIB=%OUT_DIR%\screenai_core.lib

echo ============================================
echo  Screen-AI Native Core Build
echo ============================================

REM Check for gcc
where gcc >nul 2>&1
if errorlevel 1 (
    echo [ERROR] gcc not found on PATH.
    echo Install MSYS2 or MinGW-w64 and add to PATH.
    echo   MSYS2:  pacman -S mingw-w64-x86_64-gcc
    echo   Or:     scoop install mingw
    exit /b 1
)

echo [1/3] Compiling screenai_core.c ...
gcc -O3 -Wall -Wextra -shared -o "%OUT_DLL%" "%SRC%" -I"%OUT_DIR%" -Wl,--output-def,"%OUT_DEF%"
if errorlevel 1 (
    echo [ERROR] Compilation failed.
    exit /b 1
)
echo        OK: %OUT_DLL%

echo [2/3] Generating import library ...
gcc -O3 -shared -o "%OUT_DLL%" "%SRC%" -I"%OUT_DIR%" -Wl,--out-implib,"%OUT_LIB%"
if errorlevel 1 (
    echo [WARN] Import library generation skipped.
)

echo [3/3] Done.
echo.
echo Native core built successfully.
echo DLL: %OUT_DLL%
endlocal
exit /b 0
