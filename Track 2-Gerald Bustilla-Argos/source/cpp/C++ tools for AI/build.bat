@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
cl.exe /std:c++17 /EHsc /O2 /W3 /Fe:aisearch.exe src\main.cpp src\text_utils.cpp src\image_hasher.cpp src\file_mapper.cpp src\vector_store.cpp src\content_indexer.cpp src\search_engine.cpp src\json_writer.cpp /I src
