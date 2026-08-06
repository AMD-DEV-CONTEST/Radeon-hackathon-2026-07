# Development Setup

## Prerequisites
- C++17 compiler (GCC 9+, Clang 10+, MSVC 2019+)
- CMake 3.16+
- Python 3.8+ (for testing)

## Steps
1. Clone: `git clone https://github.com/example/aisearch`
2. Build: `cmake -B build && cmake --build build`
3. Test: `./build/aisearch test_data`
4. Run: `./build/aisearch search ./test_data --query "auth"`
