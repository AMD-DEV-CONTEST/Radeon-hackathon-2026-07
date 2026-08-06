// Image fingerprinting with base64 encoding
#include "fingerprint.h"

ImageFingerprint Fingerprinter::fingerprint(const std::vector<uint8_t>& data) {
    ImageFingerprint fp;
    fp.content_hash = hasher_.compute_hash(data);
    fp.base64_hash = base64_encode(data.data(), std::min(data.size(), size_t(48)));
    fp.perceptual_hash = compute_perceptual_hash(data);
    fp.format = detect_format(data);
    fp.dimensions = detect_dimensions(data, fp.format);
    return fp;
}
