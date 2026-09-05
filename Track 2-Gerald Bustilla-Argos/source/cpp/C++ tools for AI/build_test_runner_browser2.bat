@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
cl.exe /std:c++17 /EHsc /O2 /W3 /I browser_tool /Fe:test_runner_browser2.exe tests\test_runner_browser2.cpp browser_tool\browser_tool.cpp
