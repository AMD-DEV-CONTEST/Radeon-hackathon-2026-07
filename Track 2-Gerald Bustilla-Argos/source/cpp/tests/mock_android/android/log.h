// Mock android/log.h for desktop simulation of Android code.
#ifndef MOCK_ANDROID_LOG_H
#define MOCK_ANDROID_LOG_H

#include <cstdio>
#include <cstdarg>

#define ANDROID_LOG_INFO  1
#define ANDROID_LOG_ERROR 2

static inline int __android_log_print(int prio, const char* tag, const char* fmt, ...) {
    (void)prio;
    (void)tag;
    va_list ap;
    va_start(ap, fmt);
    vprintf(fmt, ap);
    printf("\n");
    va_end(ap);
    return 0;
}

#endif // MOCK_ANDROID_LOG_H
