// Cosine similarity for vector comparison
#include "cosine_similarity.h"

double cosine_similarity(const std::unordered_map<std::string, double>& a,
                         const std::unordered_map<std::string, double>& b) {
    double dot = 0, mag_a = 0, mag_b = 0;
    for (const auto& [term, val] : a) {
        auto it = b.find(term);
        if (it != b.end()) dot += val * it->second;
        mag_a += val * val;
    }
    for (const auto& [term, val] : b) mag_b += val * val;
    if (mag_a == 0 || mag_b == 0) return 0;
    return dot / (std::sqrt(mag_a) * std::sqrt(mag_b));
}
