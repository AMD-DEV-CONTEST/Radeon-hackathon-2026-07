// Perceptual hashing for similar image detection
#include "perceptual.h"

uint64_t PerceptualHasher::compute(const std::vector<uint8_t>& data) {
    if (data.size() < 64) return fnv1a(data);
    
    size_t step = (data.size() - 64) / 64;
    uint8_t samples[64];
    for (int i = 0; i < 64; i++) {
        samples[i] = data[64 + i * step];
    }
    
    uint32_t sum = 0;
    for (int i = 0; i < 64; i++) sum += samples[i];
    uint8_t avg = sum / 64;
    
    uint64_t hash = 0;
    for (int i = 0; i < 64; i++) {
        if (samples[i] > avg) hash |= (1ULL << i);
    }
    return hash;
}
