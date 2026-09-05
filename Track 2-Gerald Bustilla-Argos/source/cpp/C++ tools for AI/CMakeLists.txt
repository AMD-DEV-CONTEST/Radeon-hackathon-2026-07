cmake_minimum_required(VERSION 3.14)
project(AISearchTool VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

if(MSVC)
    add_compile_options(/W3 /O2)
else()
    add_compile_options(-Wall -Wextra -O2)
endif()

set(SOURCES
    src/main.cpp
    src/text_utils.cpp
    src/image_hasher.cpp
    src/file_mapper.cpp
    src/vector_store.cpp
    src/content_indexer.cpp
    src/search_engine.cpp
    src/json_writer.cpp
)

set(HEADERS
    src/text_utils.h
    src/image_hasher.h
    src/file_mapper.h
    src/vector_store.h
    src/content_indexer.h
    src/search_engine.h
    src/json_writer.h
)

add_executable(aisearch ${SOURCES} ${HEADERS})

target_include_directories(aisearch PRIVATE src)

install(TARGETS aisearch DESTINATION bin)
