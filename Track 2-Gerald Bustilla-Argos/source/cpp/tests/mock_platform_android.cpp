// Mock platform implementation for Android simulation test on desktop.
// Provides mock implementations of the JNI bridge functions that would
// normally be implemented in platform_android.cpp on a real device.

#include "../../src_cross/platform.h"
#include <cstdio>
#include <cmath>
#include <vector>

namespace argos {

std::string recordAudioJava(int durationSeconds) {
    printf("[MOCK-ANDROID] recordAudioJava(%d) - generating synthetic audio\n", durationSeconds);
    int sampleRate = 16000;
    int totalSamples = durationSeconds * sampleRate;
    std::vector<int16_t> pcm(totalSamples);
    for (int i = 0; i < totalSamples; i++) {
        float t = (float)i / sampleRate;
        pcm[i] = (int16_t)(8000.0f * sinf(2.0f * 3.14159f * 440.0f * t));
    }
    return std::string((const char*)pcm.data(), totalSamples * 2);
}

std::string ttsSpeakJava(const std::string& text) {
    printf("[MOCK-ANDROID] ttsSpeakJava(\"%s\")\n", text.c_str());
    return "{\"status\":\"speaking\",\"text\":\"" + text + "\"}";
}

std::string ttsStopJava() {
    printf("[MOCK-ANDROID] ttsStopJava()\n");
    return "{\"status\":\"stopped\"}";
}

std::string ttsIsSpeakingJava() {
    printf("[MOCK-ANDROID] ttsIsSpeakingJava()\n");
    return "{\"speaking\":false}";
}

} // namespace argos
