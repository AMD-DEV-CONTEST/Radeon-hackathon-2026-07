@echo off
REM Build and run whisper integration test for Windows.
REM Usage: test_whisper.bat <model_path> [wav_file_path]

setlocal enabledelayedexpansion

REM ── Find Visual Studio ──────────────────────────────────────────────
set VSWHERE="C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq tokens=*" %%i in (`%VSWHERE% -latest -products * -property installationPath`) do set VS_PATH=%%i
if "%VS_PATH%"=="" (
    echo ERROR: Visual Studio 2022 not found.
    exit /b 1
)

call "%VS_PATH%\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Failed to initialize MSVC environment.
    exit /b 1
)

set OUT_DIR=build\test
if not exist %OUT_DIR% mkdir %OUT_DIR%

set CXXFLAGS=/std:c++17 /EHsc /W3 /D_CRT_SECURE_NO_WARNINGS /I"src" /I"src\tools" /I"src_cross" /I"..\third_party\whisper.cpp\include" /I"..\third_party\whisper.cpp\ggml\include" /I"..\third_party\whisper.cpp\ggml\src" /Od /Zi /MDd
set CFLAGS=/std:c11 /EHsc /W3 /D_CRT_SECURE_NO_WARNINGS /I"..\third_party\whisper.cpp\include" /I"..\third_party\whisper.cpp\ggml\include" /I"..\third_party\whisper.cpp\ggml\src" /Od /Zi /MDd
set LIBS=ole32.lib winmm.lib sapi.lib advapi32.lib

set WHISPER_DIR=..\third_party\whisper.cpp
set GGML_SRC=%WHISPER_DIR%\ggml\src
set WHISPER_SRC=%WHISPER_DIR%\src

echo Compiling ggml sources...
cl %CFLAGS% /c %GGML_SRC%\ggml.c /Fo%OUT_DIR%\ggml.obj
if errorlevel 1 ( echo ggml.c FAILED & exit /b 1 )
cl %CFLAGS% /c %GGML_SRC%\ggml-alloc.c /Fo%OUT_DIR%\ggml-alloc.obj
if errorlevel 1 ( echo ggml-alloc.c FAILED & exit /b 1 )
cl %CFLAGS% /c %GGML_SRC%\ggml-quants.c /Fo%OUT_DIR%\ggml-quants.obj
if errorlevel 1 ( echo ggml-quants.c FAILED & exit /b 1 )
cl %CFLAGS% /c %GGML_SRC%\ggml-aarch64.c /Fo%OUT_DIR%\ggml-aarch64.obj
if errorlevel 1 ( echo ggml-aarch64.c FAILED & exit /b 1 )
cl %CXXFLAGS% /c %GGML_SRC%\ggml-backend.cpp /Fo%OUT_DIR%\ggml-backend.obj
if errorlevel 1 ( echo ggml-backend.cpp FAILED & exit /b 1 )

echo Compiling whisper.cpp...
cl %CXXFLAGS% /c %WHISPER_SRC%\whisper.cpp /Fo%OUT_DIR%\whisper.obj
if errorlevel 1 ( echo whisper.cpp FAILED & exit /b 1 )

echo Compiling whisper_wrapper.cpp...
cl %CXXFLAGS% /c src_cross\whisper_wrapper.cpp /Fo%OUT_DIR%\whisper_wrapper.obj
if errorlevel 1 ( echo whisper_wrapper.cpp FAILED & exit /b 1 )

echo Compiling platform_windows.cpp...
cl %CXXFLAGS% /c src\platform_windows.cpp /Fo%OUT_DIR%\platform_windows.obj
if errorlevel 1 ( echo platform_windows.cpp FAILED & exit /b 1 )

echo Compiling test_whisper.cpp...
cl %CXXFLAGS% /c tests\test_whisper.cpp /Fo%OUT_DIR%\test_whisper.obj
if errorlevel 1 ( echo test_whisper.cpp FAILED & exit /b 1 )

echo Linking test_whisper.exe...
cl %CXXFLAGS% %OUT_DIR%\test_whisper.obj %OUT_DIR%\whisper_wrapper.obj %OUT_DIR%\platform_windows.obj %OUT_DIR%\ggml.obj %OUT_DIR%\ggml-alloc.obj %OUT_DIR%\ggml-quants.obj %OUT_DIR%\ggml-aarch64.obj %OUT_DIR%\ggml-backend.obj %OUT_DIR%\whisper.obj /Fe:%OUT_DIR%\test_whisper.exe /link /SUBSYSTEM:CONSOLE %LIBS%

if errorlevel 1 (
    echo LINK FAILED
    exit /b 1
)

echo.
echo BUILD SUCCEEDED: %OUT_DIR%\test_whisper.exe
echo.

if "%1"=="" (
    echo Running test without model (TTS-only test)...
    %OUT_DIR%\test_whisper.exe
) else (
    echo Running test with model: %1
    %OUT_DIR%\test_whisper.exe %1 %2
)
