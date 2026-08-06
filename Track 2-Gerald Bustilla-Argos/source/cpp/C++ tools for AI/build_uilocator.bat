@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
cl.exe /std:c++17 /EHsc /O2 /W3 /Fe:uilocator.exe /Iui_locator ui_locator\ui_locator.cpp ui_locator\main_ui.cpp /link user32.lib psapi.lib
