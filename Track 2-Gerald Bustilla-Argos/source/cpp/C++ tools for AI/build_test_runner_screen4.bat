@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64

echo Building X (Twitter) tests...
cl.exe /std:c++17 /EHsc /O2 /W3 /Fe:test_runner_screen4_x.exe /Iscreen_context tests\test_runner_screen4_x.cpp screen_context\screen_context.cpp /link user32.lib psapi.lib gdi32.lib ole32.lib oleaut32.lib
if %errorlevel% neq 0 goto :error

echo Building Instagram tests...
cl.exe /std:c++17 /EHsc /O2 /W3 /Fe:test_runner_screen4_ig.exe /Iscreen_context tests\test_runner_screen4_ig.cpp screen_context\screen_context.cpp /link user32.lib psapi.lib gdi32.lib ole32.lib oleaut32.lib
if %errorlevel% neq 0 goto :error

echo Building Threads tests...
cl.exe /std:c++17 /EHsc /O2 /W3 /Fe:test_runner_screen4_th.exe /Iscreen_context tests\test_runner_screen4_th.cpp screen_context\screen_context.cpp /link user32.lib psapi.lib gdi32.lib ole32.lib oleaut32.lib
if %errorlevel% neq 0 goto :error

echo Building YouTube tests...
cl.exe /std:c++17 /EHsc /O2 /W3 /Fe:test_runner_screen4_yt.exe /Iscreen_context tests\test_runner_screen4_yt.cpp screen_context\screen_context.cpp /link user32.lib psapi.lib gdi32.lib ole32.lib oleaut32.lib
if %errorlevel% neq 0 goto :error

echo Building TikTok tests...
cl.exe /std:c++17 /EHsc /O2 /W3 /Fe:test_runner_screen4_tt.exe /Iscreen_context tests\test_runner_screen4_tt.cpp screen_context\screen_context.cpp /link user32.lib psapi.lib gdi32.lib ole32.lib oleaut32.lib
if %errorlevel% neq 0 goto :error

echo Building Reddit tests...
cl.exe /std:c++17 /EHsc /O2 /W3 /Fe:test_runner_screen4_rd.exe /Iscreen_context tests\test_runner_screen4_rd.cpp screen_context\screen_context.cpp /link user32.lib psapi.lib gdi32.lib ole32.lib oleaut32.lib
if %errorlevel% neq 0 goto :error

echo Building LinkedIn tests...
cl.exe /std:c++17 /EHsc /O2 /W3 /Fe:test_runner_screen4_li.exe /Iscreen_context tests\test_runner_screen4_li.cpp screen_context\screen_context.cpp /link user32.lib psapi.lib gdi32.lib ole32.lib oleaut32.lib
if %errorlevel% neq 0 goto :error

echo Building Snapchat tests...
cl.exe /std:c++17 /EHsc /O2 /W3 /Fe:test_runner_screen4_sc.exe /Iscreen_context tests\test_runner_screen4_sc.cpp screen_context\screen_context.cpp /link user32.lib psapi.lib gdi32.lib ole32.lib oleaut32.lib
if %errorlevel% neq 0 goto :error

echo Building master runner...
cl.exe /std:c++17 /EHsc /O2 /W3 /Fe:test_runner_screen4.exe tests\test_runner_screen4.cpp
if %errorlevel% neq 0 goto :error

echo.
echo All builds succeeded!
goto :eof

:error
echo.
echo BUILD FAILED!
exit /b 1
