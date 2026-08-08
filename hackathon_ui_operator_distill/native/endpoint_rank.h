#ifndef SCREEN_AI_ENDPOINT_RANK_H
#define SCREEN_AI_ENDPOINT_RANK_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct screen_ai_endpoint {
    int x1;
    int y1;
    int x2;
    int y2;
    int cx;
    int cy;
    double text_score;
    double confidence;
    int source_rank;
} screen_ai_endpoint;

double screen_ai_endpoint_score(screen_ai_endpoint endpoint);
int screen_ai_pick_endpoint(const screen_ai_endpoint *items, int count);

#ifdef __cplusplus
}
#endif

#endif
