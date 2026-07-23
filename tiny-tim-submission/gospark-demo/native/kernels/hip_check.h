#ifndef HIP_CHECK_H
#define HIP_CHECK_H

#include <hip/hip_runtime.h>
#include <cstdio>

// Real HIP runtime-failure detection, replacing the "please work"
// pattern every kernel used until now (every hipMalloc/hipMemcpy call
// ignoring its return value, hence the many nodiscard warnings seen
// all night). This checks the real hipError_t every HIP API call
// actually returns, prints a clear diagnostic (file, line, the exact
// HIP error string) to stderr, and returns false so the caller can
// propagate a real failure back to Go instead of silently continuing
// with garbage or uninitialized memory.
//
// This is what moves the compute layer from "GPU works" (correctness
// proven under normal conditions) to "GPU backend behaves like an
// actual production runtime" (correctness proven AND real failures
// like device-lost/out-of-memory/driver errors are actually detected
// and reported, not silently ignored).
inline bool hipCheck(hipError_t err, const char* file, int line, const char* expr) {
    if (err != hipSuccess) {
        fprintf(stderr, "HIP failure at %s:%d (%s): %s\n",
                file, line, expr, hipGetErrorString(err));
        return false;
    }
    return true;
}

// HIP_CHECK(x): wraps a HIP call, checks its real return code, and
// returns 1 (failure) from the enclosing function immediately if the
// call failed. Every kernel host function's signature changes from
// `void` to `int` (0 = success, 1 = failure) to make this possible —
// callers on the Go side now get a real, honest signal instead of
// assuming every GPU call always succeeds.
#define HIP_CHECK(x) do { if (!hipCheck((x), __FILE__, __LINE__, #x)) return 1; } while (0)

#endif
