cmake_minimum_required(VERSION 3.24)
project(xenix_knowledge_ocr LANGUAGES CXX)

# Paddle's pinned Windows inference SDK and its bundled static dependencies use
# the static MSVC runtime. CMake's modern MSVC runtime policy otherwise injects
# /MD after the upstream /MT flags and produces an ABI-incompatible worker.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

if(NOT WIN32 OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
  message(FATAL_ERROR "Xenix Knowledge OCR currently supports Windows x64 only")
endif()
if(NOT XENIX_PADDLEOCR_SOURCE)
  message(FATAL_ERROR "Set XENIX_PADDLEOCR_SOURCE to the pinned PaddleOCR checkout")
endif()
if(NOT XENIX_BUILD_WORKSPACE)
  message(FATAL_ERROR "Set XENIX_BUILD_WORKSPACE to the disposable native build root")
endif()

set(_cpp_infer "${XENIX_PADDLEOCR_SOURCE}/deploy/cpp_infer")
if(NOT EXISTS "${_cpp_infer}/CMakeLists.txt")
  message(FATAL_ERROR "The PaddleOCR C++ inference source was not found")
endif()

# PaddleOCR and SDK headers use __FILE__ in diagnostics. Map the entire disposable
# build root to a stable virtual label so the worker never discloses local or CI
# source, SDK, or CMake paths.
if(MSVC)
  file(TO_NATIVE_PATH "${XENIX_BUILD_WORKSPACE}" _workspace_native)
  add_compile_options(
    "/experimental:deterministic"
    "/pathmap:${_workspace_native}=X:\\xenix\\native-build"
  )
endif()

# The build operates on a disposable, hash-pinned checkout. Keep the upstream
# source list and link topology, replacing only its demo entry point.
configure_file("${CMAKE_CURRENT_LIST_DIR}/src/main.cpp" "${_cpp_infer}/cli.cc" COPYONLY)
include_directories("${_cpp_infer}")
add_subdirectory("${_cpp_infer}" paddleocr-cpp)
set_target_properties(ppocr PROPERTIES OUTPUT_NAME "xenix-ocr")
