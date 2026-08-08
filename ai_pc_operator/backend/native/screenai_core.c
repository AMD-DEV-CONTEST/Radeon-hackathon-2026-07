/*
 * screenai_core.c — Implementation of Screen-AI high-performance C core.
 *
 * Design principles:
 *   - Caller-provided output buffers on hot paths
 *   - Pure functions (no I/O, no globals, fully reentrant)
 *   - Cache-friendly access patterns (sequential iteration)
 *   - Branch-free hot paths where possible
 *   - Safe: all functions validate inputs, return error codes
 */

#include "screenai_core.h"
#include <string.h>
#include <math.h>
#include <ctype.h>
#include <stddef.h>
#include <stdlib.h>

/* ═══════════════════════════════════════════════════════════════
 *  Levenshtein Distance — O(min(m,n)) space rolling array
 * ═══════════════════════════════════════════════════════════════ */

static int min3(int a, int b, int c) {
    int m = a < b ? a : b;
    return m < c ? m : c;
}

SCREENAI_API int screenai_levenshtein(const char* a, int a_len,
                                      const char* b, int b_len) {
    if (!a || !b) return a_len > 0 ? a_len : b_len > 0 ? b_len : 0;
    if (a_len <= 0) return b_len;
    if (b_len <= 0) return a_len;
    if (a_len == b_len && memcmp(a, b, a_len) == 0) return 0;

    /* Ensure b is the shorter string for space optimization. */
    if (b_len > a_len) {
        const char* tmp_s = a; a = b; b = tmp_s;
        int tmp_i = a_len; a_len = b_len; b_len = tmp_i;
    }

    /* Rolling array: two rows of b_len+1. */
    int prev[256];
    int curr[256];
    /* For very long strings, use dynamic allocation. */
    int stack_buf[512];
    int* buf = stack_buf;
    int heap_buf = 0;

    if (b_len + 1 > 256) {
        if (b_len + 1 > 256 + 256) {
            size_t bytes = (size_t)(b_len + 1) * sizeof(int) * 2;
            buf = (int*)malloc(bytes);
            if (!buf) return a_len > b_len ? a_len : b_len;
            memset(buf, 0, bytes);
            heap_buf = 1;
        } else {
            memset(stack_buf, 0, sizeof(stack_buf));
        }
    }

    int* p = heap_buf ? buf : prev;
    int* c = heap_buf ? buf + b_len + 1 : curr;

    /* Initialize first row: distance from empty string to b[0..j]. */
    for (int j = 0; j <= b_len; j++) {
        p[j] = j;
    }

    for (int i = 1; i <= a_len; i++) {
        c[0] = i;
        char ac = a[i - 1];
        for (int j = 1; j <= b_len; j++) {
            int cost = (ac == b[j - 1]) ? 0 : 1;
            c[j] = min3(
                p[j] + 1,        /* deletion */
                c[j - 1] + 1,    /* insertion */
                p[j - 1] + cost   /* substitution */
            );
        }
        /* Swap rows. */
        int* tmp = p; p = c; c = tmp;
    }

    int result = p[b_len];
    if (heap_buf) free(buf);
    return result;
}

/* ═══════════════════════════════════════════════════════════════
 *  Case-Insensitive Substring Search
 * ═══════════════════════════════════════════════════════════════ */

SCREENAI_API const char* screenai_strcasestr(const char* haystack, int h_len,
                                             const char* needle, int n_len) {
    if (!haystack || !needle || n_len <= 0) return NULL;
    if (n_len > h_len) return NULL;

    for (int i = 0; i <= h_len - n_len; i++) {
        int match = 1;
        for (int j = 0; j < n_len; j++) {
            if (tolower((unsigned char)haystack[i + j]) !=
                tolower((unsigned char)needle[j])) {
                match = 0;
                break;
            }
        }
        if (match) return haystack + i;
    }
    return NULL;
}

/* ═══════════════════════════════════════════════════════════════
 *  Fuzzy Match Score — weighted Levenshtein + containment
 * ═══════════════════════════════════════════════════════════════ */

static double clamp01(double v) {
    return v < 0.0 ? 0.0 : (v > 1.0 ? 1.0 : v);
}

/*
 * Normalize both strings to lowercase ASCII for comparison.
 * Writes into caller-provided buffers. Returns actual lengths.
 */
static void to_lower_ascii(const char* src, int src_len, char* dst, int* out_len) {
    int len = src_len;
    if (len > 0 && src) {
        for (int i = 0; i < len; i++) {
            dst[i] = (char)tolower((unsigned char)src[i]);
        }
    }
    *out_len = len;
}

SCREENAI_API double screenai_fuzzy_score(const char* query, int q_len,
                                         const char* target, int t_len) {
    if (!query || !target || q_len <= 0 || t_len <= 0) return 0.0;

    /* Case-insensitive normalization. */
    char q_buf[256];
    char t_buf[512];
    int q_norm_len, t_norm_len;

    if (q_len > (int)sizeof(q_buf) - 1) q_len = (int)sizeof(q_buf) - 1;
    if (t_len > (int)sizeof(t_buf) - 1) t_len = (int)sizeof(t_buf) - 1;

    to_lower_ascii(query, q_len, q_buf, &q_norm_len);
    to_lower_ascii(target, t_len, t_buf, &t_norm_len);

    /* Exact match → 1.0 */
    if (q_norm_len == t_norm_len && memcmp(q_buf, t_buf, q_norm_len) == 0) {
        return 1.0;
    }

    /* Containment check */
    int query_in_target = (screenai_strcasestr(t_buf, t_norm_len, q_buf, q_norm_len) != NULL);
    int target_in_query = (screenai_strcasestr(q_buf, q_norm_len, t_buf, t_norm_len) != NULL);

    /* Levenshtein-based similarity */
    int dist = screenai_levenshtein(q_buf, q_norm_len, t_buf, t_norm_len);
    int max_len = q_norm_len > t_norm_len ? q_norm_len : t_norm_len;
    double lev_similarity = 1.0 - ((double)dist / (double)max_len);

    /* Prefix bonus: if query is a prefix of target (or vice versa) */
    int prefix_len = q_norm_len < t_norm_len ? q_norm_len : t_norm_len;
    int is_prefix = (memcmp(q_buf, t_buf, prefix_len) == 0);
    double prefix_bonus = is_prefix ? 0.15 : 0.0;

    /* Weighted combination */
    double score = lev_similarity * 0.55
                 + prefix_bonus
                 + (query_in_target ? 0.30 : 0.0)
                 + (target_in_query ? 0.20 : 0.0);

    return clamp01(score);
}

/* ═══════════════════════════════════════════════════════════════
 *  Element Ranking — multi-signal weighted scoring
 * ═══════════════════════════════════════════════════════════════ */

SCREENAI_API int screenai_rank_elements(
    const char* query, int q_len,
    const double* confidences,
    const int* x1, const int* y1, const int* x2, const int* y2,
    const int* source_ranks,
    int count,
    screenai_element_score* out
) {
    if (!query || q_len <= 0 || !out || count <= 0) return -1;

    int best_idx = -1;
    double best_score = -1.0;

    /* For each element, we need its text. Since we don't store text in C,
     * we approximate: caller should precompute text_match scores in
     * confidences array OR use this with a text_match override.
     *
     * Here we use confidences as a combined text_match+confidence signal
     * for pure-C ranking. The Python bridge layers the full fuzzy_score
     * on top for the final call.
     */
    for (int i = 0; i < count; i++) {
        double confidence = (confidences && i < count) ? confidences[i] : 0.5;

        /* Size bonus: area-based, normalized to 50000px^2 */
        double width  = (double)(x2[i] - x1[i]);
        double height = (double)(y2[i] - y1[i]);
        double area = (width > 0 && height > 0) ? width * height : 0.0;
        double size_score = clamp01(area / 50000.0);

        /* Source bonus: UIA (0) gets +0.12, vision (1) gets 0, merged (2) gets +0.04 */
        int sr = (source_ranks && i < count) ? source_ranks[i] : 1;
        double source_bonus = (sr == 0) ? 0.12 : (sr == 2 ? 0.04 : 0.0);

        double score = confidence * 0.62
                     + confidence * 0.22  /* same as confidence for simplicity */
                     + size_score * 0.04
                     + source_bonus;

        out[i].index = i;
        out[i].score = score;

        if (score > best_score) {
            best_score = score;
            best_idx = i;
        }
    }

    return best_idx;
}

/* ═══════════════════════════════════════════════════════════════
 *  Keyword Prefilter — O(n*m) but with early termination
 * ═══════════════════════════════════════════════════════════════ */

SCREENAI_API int screenai_keyword_prefilter(
    const char* text, int text_len,
    const char* keywords,
    const int* keyword_offsets,
    const int* keyword_lengths,
    const int* keyword_to_intent,
    int keyword_count,
    screenai_keyword_match* out,
    int max_matches
) {
    if (!text || text_len <= 0 || !out || max_matches <= 0) return 0;

    int found = 0;

    for (int k = 0; k < keyword_count && found < max_matches; k++) {
        int kw_len = keyword_lengths[k];
        if (kw_len <= 0 || kw_len > text_len) continue;

        const char* kw = keywords + keyword_offsets[k];

        /* Scan text for keyword (case-insensitive) */
        for (int i = 0; i <= text_len - kw_len && found < max_matches; i++) {
            int match = 1;
            for (int j = 0; j < kw_len; j++) {
                if (tolower((unsigned char)text[i + j]) !=
                    tolower((unsigned char)kw[j])) {
                    match = 0;
                    break;
                }
            }
            if (match) {
                out[found].intent_id = keyword_to_intent[k];
                out[found].keyword_id = k;
                out[found].position = i;
                found++;
                break;  /* One match per keyword is enough */
            }
        }
    }

    return found;
}

/* ═══════════════════════════════════════════════════════════════
 *  xxHash64 — Fast non-cryptographic hash
 *  Based on xxHash reference (public domain).
 * ═══════════════════════════════════════════════════════════════ */

static const uint64_t XXH_PRIME1 = 0x9E3779B185EBCA87ULL;
static const uint64_t XXH_PRIME2 = 0x14DEF9DEA2F79CD6ULL;
static const uint64_t XXH_PRIME3 = 0x165667B19E3779F9ULL;
static const uint64_t XXH_PRIME4 = 0x85EBCA77C2B2ED6BULL;
static const uint64_t XXH_PRIME5 = 0x27D4EB2F165667C5ULL;

static uint64_t xxh_read64(const void* ptr) {
    uint64_t val;
    memcpy(&val, ptr, sizeof(val));
    return val;
}

static uint32_t xxh_read32(const void* ptr) {
    uint32_t val;
    memcpy(&val, ptr, sizeof(val));
    return val;
}

static uint64_t xxh_round(uint64_t acc, uint64_t input) {
    acc += input * XXH_PRIME2;
    acc  = (acc << 31) | (acc >> 33);
    acc *= XXH_PRIME1;
    return acc;
}

SCREENAI_API uint64_t screenai_xxhash64(const void* data, size_t len, uint64_t seed) {
    if (!data || len == 0) return seed;

    const uint8_t* p = (const uint8_t*)data;
    uint64_t h64;

    if (len >= 32) {
        const uint8_t* end = p + len - 32;
        uint64_t v1 = seed + XXH_PRIME1 + XXH_PRIME2;
        uint64_t v2 = seed + XXH_PRIME2;
        uint64_t v3 = seed + 0;
        uint64_t v4 = seed - XXH_PRIME1;

        do {
            v1 = xxh_round(v1, xxh_read64(p));  p += 8;
            v2 = xxh_round(v2, xxh_read64(p));  p += 8;
            v3 = xxh_round(v3, xxh_read64(p));  p += 8;
            v4 = xxh_round(v4, xxh_read64(p));  p += 8;
        } while (p <= end);

        h64 = ((v1 << 1) | (v1 >> 63))
            + ((v2 << 7) | (v2 >> 57))
            + ((v3 << 12) | (v3 >> 52))
            + ((v4 << 18) | (v4 >> 46));
    } else {
        h64 = seed + XXH_PRIME5;
    }

    h64 += (uint64_t)len;

    while (len >= 8) {
        h64 ^= xxh_round(0, xxh_read64(p));
        h64  = ((h64 << 27) | (h64 >> 37)) * XXH_PRIME1 + XXH_PRIME4;
        p += 8;
        len -= 8;
    }

    while (len >= 4) {
        h64 ^= (uint64_t)(xxh_read32(p)) * XXH_PRIME1;
        h64  = ((h64 << 23) | (h64 >> 41)) * XXH_PRIME2 + XXH_PRIME3;
        p += 4;
        len -= 4;
    }

    while (len > 0) {
        h64 ^= (uint64_t)(*p) * XXH_PRIME5;
        h64  = ((h64 << 11) | (h64 >> 53)) * XXH_PRIME1;
        p++;
        len--;
    }

    /* Avalanche */
    h64 ^= h64 >> 33;
    h64 *= XXH_PRIME2;
    h64 ^= h64 >> 29;
    h64 *= XXH_PRIME3;
    h64 ^= h64 >> 32;

    return h64;
}

/* ═══════════════════════════════════════════════════════════════
 *  Rolling Hash — for incremental screen change detection
 * ═══════════════════════════════════════════════════════════════ */

SCREENAI_API uint64_t screenai_rolling_hash(const uint8_t* data, size_t len) {
    if (!data || len == 0) return 0;

    const uint64_t BASE = 1315423911;  /* Large prime for low collision */
    const uint64_t MOD  = (1ULL << 61) - 1;  /* Mersenne prime */
    uint64_t h = 0;

    for (size_t i = 0; i < len; i++) {
        h = ((h * BASE) ^ data[i]) % MOD;
    }

    return h;
}

/* ═══════════════════════════════════════════════════════════════
 *  Batch Bounds Validation
 * ═══════════════════════════════════════════════════════════════ */

SCREENAI_API int screenai_validate_bounds(
    const int* x1, const int* y1, const int* x2, const int* y2,
    const int* is_pane,
    int count,
    int screen_w, int screen_h,
    int* out
) {
    if (!out || count <= 0) return 0;

    int valid_count = 0;
    int min_size = 4;  /* Minimum element size in pixels */
    int area_total = screen_w * screen_h;

    for (int i = 0; i < count; i++) {
        int bx1 = x1[i], by1 = y1[i], bx2 = x2[i], by2 = y2[i];
        int w = bx2 - bx1;
        int h = by2 - by1;

        /* Must have positive dimensions */
        if (w < min_size || h < min_size) continue;

        /* Must be on-screen (at least partially) */
        if (bx2 < 0 || by2 < 0 || bx1 > screen_w || by1 > screen_h) continue;

        /* Reject fullscreen unless it's a pane/window */
        int elem_area = w * h;
        int pane = (is_pane && i < count) ? is_pane[i] : 0;
        if (!pane && elem_area > (int)(area_total * 0.98)) continue;

        out[valid_count++] = i;
    }

    return valid_count;
}
