#include "ssd_tier_policy.h"

static double score_item(double freq, unsigned long long last, unsigned long long now) {
    unsigned long long age = now > last ? now - last : 0;
    return freq / (1.0 + (double)age * 0.01);
}

int screen_ai_pick_lfru(
    const double *freq,
    const unsigned long long *last_used,
    unsigned long long now,
    const int *resident,
    int resident_count,
    const int *candidates,
    int candidate_count,
    screen_ai_tier_pick *out
) {
    int worst_slot = -1;
    int best_item = -1;
    double worst_score = 0.0;
    double best_score = 0.0;

    if (!freq || !last_used || !resident || !candidates || !out) return 0;
    if (resident_count <= 0 || candidate_count <= 0) return 0;

    for (int i = 0; i < resident_count; i++) {
        int item = resident[i];
        double score = score_item(freq[item], last_used[item], now);
        if (worst_slot < 0 || score < worst_score) {
            worst_slot = i;
            worst_score = score;
        }
    }

    for (int i = 0; i < candidate_count; i++) {
        int item = candidates[i];
        double score = score_item(freq[item], last_used[item], now);
        if (best_item < 0 || score > best_score) {
            best_item = item;
            best_score = score;
        }
    }

    if (best_item < 0 || worst_slot < 0) return 0;
    if (best_score <= worst_score * 1.10) return 0;

    out->slot = worst_slot;
    out->item = best_item;
    out->gain = best_score - worst_score;
    return 1;
}
