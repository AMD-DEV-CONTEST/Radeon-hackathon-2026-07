#include "endpoint_rank.h"

static double clamp01(double value) {
    if (value < 0.0) return 0.0;
    if (value > 1.0) return 1.0;
    return value;
}

double screen_ai_endpoint_score(screen_ai_endpoint endpoint) {
    int width = endpoint.x2 - endpoint.x1;
    int height = endpoint.y2 - endpoint.y1;
    double area = (width > 0 && height > 0) ? (double)(width * height) : 0.0;
    double size_score = area > 0.0 ? clamp01(area / 50000.0) : 0.0;
    double source_bonus = endpoint.source_rank == 0 ? 0.12 : 0.0;
    return clamp01(
        endpoint.text_score * 0.62 +
        endpoint.confidence * 0.22 +
        size_score * 0.04 +
        source_bonus
    );
}

int screen_ai_pick_endpoint(const screen_ai_endpoint *items, int count) {
    int best = -1;
    double best_score = -1.0;
    if (!items || count <= 0) return -1;
    for (int i = 0; i < count; i++) {
        double score = screen_ai_endpoint_score(items[i]);
        if (score > best_score) {
            best_score = score;
            best = i;
        }
    }
    return best;
}
