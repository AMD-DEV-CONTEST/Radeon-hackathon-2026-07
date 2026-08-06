@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
cl.exe /std:c++17 /EHsc /O2 /W3 /Fe:screencontext.exe /Iscreen_context screen_context\screen_context.cpp screen_context\main_screen.cpp /link user32.lib psapi.lib gdi32.lib ole32.lib oleaut32.lib
