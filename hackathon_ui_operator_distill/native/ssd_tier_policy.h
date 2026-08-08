#ifndef SCREEN_AI_SSD_TIER_POLICY_H
#define SCREEN_AI_SSD_TIER_POLICY_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct screen_ai_tier_pick {
    int slot;
    int item;
    double gain;
} screen_ai_tier_pick;

int screen_ai_pick_lfru(
    const double *freq,
    const unsigned long long *last_used,
    unsigned long long now,
    const int *resident,
    int resident_count,
    const int *candidates,
    int candidate_count,
    screen_ai_tier_pick *out
);

#ifdef __cplusplus
}
#endif

#endif
