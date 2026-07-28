/*******************************************************************************
 *
 * MIT License
 *
 * Copyright (C) 2021-2025 Advanced Micro Devices, Inc. All rights reserved.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 *
 *******************************************************************************/

//! @file
//! @brief rocwmma-version.hpp provides the configured version and settings
//!
//! Manually generated (not CMake-configured) when vendoring this header-only
//! library into VTE: values match the rocm-7.1.0 tag's CMakeLists.txt
//! (VERSION_STRING "2.0.0"), the same version this project's HIP SDK install
//! ships. See VTE/third_party/rocwmma/VENDORING.md.

#ifndef ROCWMMA_API_VERSION_HPP
#define ROCWMMA_API_VERSION_HPP

// clang-format off
#define ROCWMMA_VERSION_MAJOR       2
#define ROCWMMA_VERSION_MINOR       0
#define ROCWMMA_VERSION_PATCH       0
// clang-format on

inline std::string rocwmma_get_version()
{
    return std::to_string(ROCWMMA_VERSION_MAJOR) + "." + std::to_string(ROCWMMA_VERSION_MINOR) + "."
           + std::to_string(ROCWMMA_VERSION_PATCH);
}

#endif // ROCWMMA_API_VERSION_HPP
