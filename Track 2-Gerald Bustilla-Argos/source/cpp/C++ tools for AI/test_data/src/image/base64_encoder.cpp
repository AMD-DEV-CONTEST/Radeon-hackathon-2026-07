// Base64 encoding utility for image data
#include "base64_encoder.h"

static const char chars[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

std::string Base64Encoder::encode(const uint8_t* data, size_t len) {
    std::string result;
    for (size_t i = 0; i < len; i += 3) {
        uint32_t triple = 0;
        int pad = 0;
        triple |= (uint32_t)data[i] << 16;
        if (i + 1 < len) triple |= (uint32_t)data[i+1] << 8; else pad++;
        if (i + 2 < len) triple |= (uint32_t)data[i+2]; else pad++;
        result += chars[(triple >> 18) & 0x3F];
        result += chars[(triple >> 12) & 0x3F];
        result += (pad < 2) ? chars[(triple >> 6) & 0x3F] : '=';
        result += (pad < 1) ? chars[triple & 0x3F] : '=';
    }
    return result;
}
