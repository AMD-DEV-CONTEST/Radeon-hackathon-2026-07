/*
 * screenai_core.h — High-performance C core for Screen-AI hot paths.
 *
 * Provides zero-allocation algorithms for:
 *   - Fuzzy text matching (Levenshtein + weighted Jaccard)
 *   - UI element scoring and ranking
 *   - Fast regex prefilter for intent classification
 *   - XXHash-based screen dedup
 *   - Batch element filtering
 *
 * Build: gcc -O3 -shared -o screenai_core.dll screenai_core.c (Windows)
 *        gcc -O3 -shared -fPIC -o screenai_core.so screenai_core.c (Linux)
 *
 * Safety: All functions are pure: caller-provided outputs, no I/O, no global state.
 */

#ifndef SCREENAI_CORE_H
#define SCREENAI_CORE_H

#ifdef _WIN32
    #define SCREENAI_API __declspec(dllexport)
#else
    #define SCREENAI_API __attribute__((visibility("default")))
#endif

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ─── Fuzzy Text Matching ─────────────────────────────────────── */

/*
 * Compute Levenshtein edit distance between two ASCII strings.
 * O(m*n) time, O(min(m,n)) space via rolling array.
 * Returns 0 for identical strings.
 */
SCREENAI_API int screenai_levenshtein(const char* a, int a_len,
                                      const char* b, int b_len);

/*
 * Weighted fuzzy match score [0.0, 1.0].
 * Combines normalized Levenshtein similarity with a containment bonus.
 *   - exact match:       1.0
 *   - one contains other: 0.85+
 *   - edit distance <= 2: 0.7+
 *   - long query prefix:  0.6+
 */
SCREENAI_API double screenai_fuzzy_score(const char* query, int q_len,
                                         const char* target, int t_len);

/*
 * Case-insensitive substring search. Returns pointer to first occurrence
 * or NULL. O(n*m) in the worst case but fast for short UI strings.
 */
SCREENAI_API const char* screenai_strcasestr(const char* haystack, int h_len,
                                             const char* needle, int n_len);

/* ─── Element Scoring ─────────────────────────────────────────── */

typedef struct screenai_element_score {
    int index;
    double score;
} screenai_element_score;

/*
 * Score a batch of UI elements against a query string.
 *
 * For each element, score = text_match * 0.62 + confidence * 0.22
 *                         + size_bonus * 0.04 + source_bonus * 0.12
 *
 * text_match:  fuzzy_score(query, element_text)
 * confidence:  element confidence [0, 1]
 * bounds:      {x1,y1,x2,y2} — size_bonus = clamp(area / 50000, 0, 1)
 * source_rank: 0 = UIA (best), 1 = vision, 2 = merged
 *
 * Writes results into `out` (must have room for `count` elements).
 * Returns the index of the best element, or -1 if none found.
 */
SCREENAI_API int screenai_rank_elements(
    const char* query, int q_len,
    const double* confidences,
    const int* x1, const int* y1, const int* x2, const int* y2,
    const int* source_ranks,
    int count,
    screenai_element_score* out
);

/* ─── Intent Prefilter ────────────────────────────────────────── */

typedef struct screenai_keyword_match {
    int intent_id;
    int keyword_id;
    int position;
} screenai_keyword_match;

/*
 * Fast keyword prefilter for intent classification.
 *
 * `keywords` is a flat array of lowercase keyword strings.
 * `keyword_offsets[i]` gives the start index of keyword i in `keywords`.
 * `keyword_lengths[i]` gives the length of keyword i.
 * `keyword_to_intent[i]` maps keyword index → intent_id.
 *
 * Scans `text` (length `text_len`) for any keyword occurrence.
 * Writes up to `max_matches` matches into `out`.
 * Returns the number of matches found.
 */
SCREENAI_API int screenai_keyword_prefilter(
    const char* text, int text_len,
    const char* keywords,
    const int* keyword_offsets,
    const int* keyword_lengths,
    const int* keyword_to_intent,
    int keyword_count,
    screenai_keyword_match* out,
    int max_matches
);

/* ─── Hash / Dedup ────────────────────────────────────────────── */

/*
 * xxHash-inspired fast non-crypto hash. Good for screen dedup keys.
 * ~5 GB/s throughput on modern CPUs.
 */
SCREENAI_API uint64_t screenai_xxhash64(const void* data, size_t len, uint64_t seed);

/*
 * Simple rolling hash for incremental screen change detection.
 * Feed chunks; compare final hashes to detect drift.
 */
SCREENAI_API uint64_t screenai_rolling_hash(const uint8_t* data, size_t len);

/* ─── Batch Bounds Validation ─────────────────────────────────── */

/*
 * Validate element bounds against screen dimensions.
 * Filters out: off-screen, too small (<4px), fullscreen (unless pane/window).
 * Returns count of valid elements; writes valid indices into `out`.
 */
SCREENAI_API int screenai_validate_bounds(
    const int* x1, const int* y1, const int* x2, const int* y2,
    const int* is_pane,  /* 1 if element is pane/window (allows fullscreen) */
    int count,
    int screen_w, int screen_h,
    int* out
);

#ifdef __cplusplus
}
#endif

#endif /* SCREENAI_CORE_H */
