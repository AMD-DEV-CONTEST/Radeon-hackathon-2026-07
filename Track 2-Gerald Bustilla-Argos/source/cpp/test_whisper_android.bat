@echo off
REM Build and run Android simulation test for whisper.cpp integration.
REM This simulates the Android voice pipeline on Windows desktop.
REM Usage: test_whisper_android.bat [model_path] [wav_file_path]

setlocal enabledelayedexpansion

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

set OUT_DIR=build\test_android
if not exist %OUT_DIR% mkdir %OUT_DIR%

set CXXFLAGS=/std:c++17 /EHsc /W3 /D_CRT_SECURE_NO_WARNINGS /I"src" /I"src\tools" /I"src_cross" /I"tests\mock_android" /I"..\third_party\whisper.cpp\include" /I"..\third_party\whisper.cpp\ggml\include" /I"..\third_party\whisper.cpp\ggml\src" /Od /Zi /MDd
set CFLAGS=/std:c11 /EHsc /W3 /D_CRT_SECURE_NO_WARNINGS /I"..\third_party\whisper.cpp\include" /I"..\third_party\whisper.cpp\ggml\include" /I"..\third_party\whisper.cpp\ggml\src" /Od /Zi /MDd
set LIBS=ole32.lib winmm.lib advapi32.lib

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

echo Compiling whisper_wrapper.cpp (Android path via mock)...
cl %CXXFLAGS% /D__ANDROID__ /c src_cross\whisper_wrapper.cpp /Fo%OUT_DIR%\whisper_wrapper.obj
if errorlevel 1 ( echo whisper_wrapper.cpp FAILED & exit /b 1 )

echo Compiling mock_platform_android.cpp...
cl %CXXFLAGS% /c tests\mock_platform_android.cpp /Fo%OUT_DIR%\mock_platform_android.obj
if errorlevel 1 ( echo mock_platform_android.cpp FAILED & exit /b 1 )

echo Compiling test_whisper_android_sim.cpp...
cl %CXXFLAGS% /c tests\test_whisper_android_sim.cpp /Fo%OUT_DIR%\test_android_sim.obj
if errorlevel 1 ( echo test_whisper_android_sim.cpp FAILED & exit /b 1 )

echo Linking test_whisper_android_sim.exe...
cl %CXXFLAGS% %OUT_DIR%\test_android_sim.obj %OUT_DIR%\whisper_wrapper.obj %OUT_DIR%\mock_platform_android.obj %OUT_DIR%\ggml.obj %OUT_DIR%\ggml-alloc.obj %OUT_DIR%\ggml-quants.obj %OUT_DIR%\ggml-aarch64.obj %OUT_DIR%\ggml-backend.obj %OUT_DIR%\whisper.obj /Fe:%OUT_DIR%\test_whisper_android_sim.exe /link /SUBSYSTEM:CONSOLE %LIBS%

if errorlevel 1 (
    echo LINK FAILED
    exit /b 1
)

echo.
echo BUILD SUCCEEDED: %OUT_DIR%\test_whisper_android_sim.exe
echo.

if "%1"=="" (
    echo Running Android simulation test (no model - dispatch tests only)...
    %OUT_DIR%\test_whisper_android_sim.exe
) else (
    echo Running Android simulation test with model: %1
    %OUT_DIR%\test_whisper_android_sim.exe %1 %2
)
