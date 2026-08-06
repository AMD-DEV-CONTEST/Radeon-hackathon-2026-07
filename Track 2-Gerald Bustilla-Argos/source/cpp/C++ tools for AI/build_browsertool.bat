@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
cl.exe /std:c++17 /EHsc /O2 /W3 /Fe:browsertool.exe browser_tool\main_browser.cpp browser_tool\browser_tool.cpp
