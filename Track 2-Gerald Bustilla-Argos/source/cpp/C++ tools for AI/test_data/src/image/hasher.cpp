// Image hashing for content identification
#include "hasher.h"

uint64_t ImageHasher::compute_hash(const std::vector<uint8_t>& data) {
    uint64_t hash = 0xcbf29ce484222325ULL;
    for (auto byte : data) {
        hash ^= byte;
        hash *= 0x100000001b3ULL;
    }
    return hash;
}
