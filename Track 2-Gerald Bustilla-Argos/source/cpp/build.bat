@echo off
REM Build script for Argos C++ desktop companion.
REM Uses MSVC (Visual Studio 2022 Build Tools) directly — no CMake needed.
REM
REM Usage: build.bat        (debug build)
REM        build.bat release (release build)

setlocal enabledelayedexpansion

REM ── Find Visual Studio ──────────────────────────────────────────────
set VSWHERE="C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq tokens=*" %%i in (`%VSWHERE% -latest -products * -property installationPath`) do set VS_PATH=%%i
if "%VS_PATH%"=="" (
    echo ERROR: Visual Studio 2022 not found.
    exit /b 1
)

REM ── Set up build environment ─────────────────────────────────────────
call "%VS_PATH%\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Failed to initialize MSVC environment.
    exit /b 1
)

REM ── Configuration ────────────────────────────────────────────────────
set CONFIG=Debug
if /i "%1%"=="release" set CONFIG=Release

set OUT_DIR=build\%CONFIG%
if not exist %OUT_DIR% mkdir %OUT_DIR%

REM ── Compiler flags ───────────────────────────────────────────────────
REM Main app uses UNICODE, whisper/ggml does not
set CXXFLAGS=/std:c++17 /EHsc /W3 /DUNICODE /D_UNICODE /D_CRT_SECURE_NO_WARNINGS /I"src" /I"src\tools" /I"src_cross" /I"..\third_party\whisper.cpp\include" /I"..\third_party\whisper.cpp\ggml\include" /I"..\third_party\whisper.cpp\ggml\src"
set CFLAGS=/std:c11 /EHsc /W3 /D_CRT_SECURE_NO_WARNINGS /I"..\third_party\whisper.cpp\include" /I"..\third_party\whisper.cpp\ggml\include" /I"..\third_party\whisper.cpp\ggml\src"
REM Whisper/ggml C++ flags (no UNICODE to avoid RegQueryValueEx issues)
set WHISPER_CXXFLAGS=/std:c++17 /EHsc /W3 /D_CRT_SECURE_NO_WARNINGS /I"..\third_party\whisper.cpp\include" /I"..\third_party\whisper.cpp\ggml\include" /I"..\third_party\whisper.cpp\ggml\src"

if /i "%CONFIG%"=="Release" (
    set CXXFLAGS=%CXXFLAGS% /O2 /DNDEBUG /MD
    set CFLAGS=%CFLAGS% /O2 /DNDEBUG /MD
    set WHISPER_CXXFLAGS=%WHISPER_CXXFLAGS% /O2 /DNDEBUG /MD
) else (
    set CXXFLAGS=%CXXFLAGS% /Od /Zi /MDd
    set CFLAGS=%CFLAGS% /Od /Zi /MDd
    set WHISPER_CXXFLAGS=%WHISPER_CXXFLAGS% /Od /Zi /MDd
)

REM ── Linker flags ────────────────────────────────────────────────────
set LDFLAGS=/SUBSYSTEM:WINDOWS
set LIBS=d2d1.lib dwmapi.lib winhttp.lib shell32.lib user32.lib gdi32.lib ole32.lib oleaut32.lib uiautomationcore.lib winmm.lib sapi.lib advapi32.lib

REM ── whisper.cpp / ggml sources ──────────────────────────────────────
set WHISPER_DIR=..\third_party\whisper.cpp
set GGML_SRC=%WHISPER_DIR%\ggml\src
set WHISPER_SRC=%WHISPER_DIR%\src

echo Compiling ggml (core)...
cl %CFLAGS% /c %GGML_SRC%\ggml.c /Fo%OUT_DIR%\ggml.obj
if errorlevel 1 ( echo ggml.c FAILED & exit /b 1 )

echo Compiling ggml-alloc...
cl %CFLAGS% /c %GGML_SRC%\ggml-alloc.c /Fo%OUT_DIR%\ggml-alloc.obj
if errorlevel 1 ( echo ggml-alloc.c FAILED & exit /b 1 )

echo Compiling ggml-quants...
cl %CFLAGS% /c %GGML_SRC%\ggml-quants.c /Fo%OUT_DIR%\ggml-quants.obj
if errorlevel 1 ( echo ggml-quants.c FAILED & exit /b 1 )

echo Compiling ggml-aarch64...
cl %CFLAGS% /c %GGML_SRC%\ggml-aarch64.c /Fo%OUT_DIR%\ggml-aarch64.obj
if errorlevel 1 ( echo ggml-aarch64.c FAILED & exit /b 1 )

echo Compiling ggml-backend...
cl %WHISPER_CXXFLAGS% /c %GGML_SRC%\ggml-backend.cpp /Fo%OUT_DIR%\ggml-backend.obj
if errorlevel 1 ( echo ggml-backend.cpp FAILED & exit /b 1 )

echo Compiling whisper.cpp...
cl %WHISPER_CXXFLAGS% /c %WHISPER_SRC%\whisper.cpp /Fo%OUT_DIR%\whisper.obj
if errorlevel 1 ( echo whisper.cpp FAILED & exit /b 1 )

REM ── Source files ────────────────────────────────────────────────────
set SOURCES=src\main.cpp src\window_manager.cpp src\robot_renderer.cpp src\tray_icon.cpp src\agent_client.cpp src\argos_tools.cpp src\platform_windows.cpp
set TOOL_SOURCES=src\tools\text_utils.cpp src\tools\file_mapper.cpp src\tools\vector_store.cpp src\tools\image_hasher.cpp src\tools\content_indexer.cpp src\tools\search_engine.cpp src\tools\json_writer.cpp src\tools\browser_tool.cpp src\tools\screen_context.cpp src\tools\ui_locator.cpp src\tools\computer_use_tool.cpp
set CROSS_SOURCES=src_cross\whisper_wrapper.cpp

REM ── Compile and link ────────────────────────────────────────────────
echo Building Argos (%CONFIG%)...
cl %CXXFLAGS% %SOURCES% %TOOL_SOURCES% %CROSS_SOURCES% %OUT_DIR%\ggml.obj %OUT_DIR%\ggml-alloc.obj %OUT_DIR%\ggml-quants.obj %OUT_DIR%\ggml-aarch64.obj %OUT_DIR%\ggml-backend.obj %OUT_DIR%\whisper.obj /Fe:%OUT_DIR%\argos.exe /Fo%OUT_DIR%\ /link %LDFLAGS% %LIBS%

if errorlevel 1 (
    echo.
    echo BUILD FAILED
    exit /b 1
)

echo.
echo BUILD SUCCEEDED: %OUT_DIR%\argos.exe
echo Run it: %OUT_DIR%\argos.exe
