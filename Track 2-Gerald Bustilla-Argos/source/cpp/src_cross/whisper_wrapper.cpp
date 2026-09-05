#include "whisper_wrapper.h"
#include "platform.h"

#ifdef __ANDROID__
#include <android/log.h>
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "ArgosWhisper", __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, "ArgosWhisper", __VA_ARGS__)
#elif defined(_WIN32)
#include <windows.h>
#include <mmsystem.h>
#include <cstdio>
#define LOGI(...) printf(__VA_ARGS__)
#define LOGE(...) fprintf(stderr, __VA_ARGS__)
#else
#include <cstdio>
#define LOGI(...) printf(__VA_ARGS__)
#define LOGE(...) fprintf(stderr, __VA_ARGS__)
#endif

#include "whisper.h"

#include <cmath>
#include <algorithm>
#include <chrono>
#include <cstring>
#include <thread>

namespace argos {

static struct whisper_context* s_whisperCtx = nullptr;
static std::string s_modelPath;
static std::mutex s_whisperMutex;
static std::atomic<bool> s_recording{false};
static std::function<void(const std::string&)> s_statusCallback;

void setRecordingStatusCallback(std::function<void(const std::string&)> callback) {
    s_statusCallback = callback;
}

bool whisperInit(const std::string& modelPath) {
    std::lock_guard<std::mutex> lock(s_whisperMutex);
    if (s_whisperCtx) {
        whisper_free(s_whisperCtx);
        s_whisperCtx = nullptr;
    }

    LOGI("whisperInit: loading model from %s\n", modelPath.c_str());

    whisper_context_params cparams = whisper_context_default_params();
    s_whisperCtx = whisper_init_from_file_with_params(modelPath.c_str(), cparams);

    if (!s_whisperCtx) {
        LOGE("whisperInit: failed to load model from %s\n", modelPath.c_str());
        return false;
    }

    s_modelPath = modelPath;
    LOGI("whisperInit: model loaded successfully\n");
    return true;
}

bool whisperIsReady() {
    std::lock_guard<std::mutex> lock(s_whisperMutex);
    return s_whisperCtx != nullptr;
}

std::string whisperGetModelPath() {
    return s_modelPath;
}

std::string whisperTranscribe(const std::vector<float>& samples) {
    std::lock_guard<std::mutex> lock(s_whisperMutex);

    if (!s_whisperCtx) {
        return "{\"error\":\"Whisper not initialized. Call whisperInit first.\"}";
    }

    if (samples.empty()) {
        return "{\"error\":\"No audio samples provided\"}";
    }

    LOGI("whisperTranscribe: %zu samples (%.1f seconds)\n", samples.size(), (float)samples.size() / 16000.0f);

    whisper_full_params wparams = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);

    wparams.print_progress = false;
    wparams.print_special = false;
    wparams.print_realtime = false;
    wparams.print_timestamps = false;
    wparams.translate = false;
    wparams.language = "en";
    wparams.n_threads = 2;
    wparams.no_timestamps = true;

    if (s_statusCallback) s_statusCallback("Transcribing audio...");

    int result = whisper_full(s_whisperCtx, wparams, samples.data(), (int)samples.size());

    if (result != 0) {
        LOGE("whisperTranscribe: whisper_full failed with code %d\n", result);
        return "{\"error\":\"Transcription failed\"}";
    }

    std::string text;
    int n_segments = whisper_full_n_segments(s_whisperCtx);
    for (int i = 0; i < n_segments; i++) {
        const char* seg = whisper_full_get_segment_text(s_whisperCtx, i);
        if (seg) {
            text += seg;
        }
    }

    // Trim whitespace
    auto start = text.find_first_not_of(" \t\n\r");
    if (start == std::string::npos) {
        text = "";
    } else {
        auto end = text.find_last_not_of(" \t\n\r");
        text = text.substr(start, end - start + 1);
    }

    LOGI("whisperTranscribe: result = \"%s\"\n", text.c_str());

    if (s_statusCallback) s_statusCallback("Transcription complete");

    return text;
}

void stopRecording() {
    s_recording.store(false);
}

bool isRecording() {
    return s_recording.load();
}

// Convert 16-bit PCM to float32
static std::vector<float> pcm16ToFloat(const std::vector<int16_t>& pcm16) {
    std::vector<float> f32(pcm16.size());
    for (size_t i = 0; i < pcm16.size(); i++) {
        f32[i] = (float)pcm16[i] / 32768.0f;
    }
    return f32;
}

// Resample from given sample rate to 16kHz (simple linear interpolation)
static std::vector<float> resampleTo16k(const std::vector<float>& input, int inputRate) {
    if (inputRate == 16000) return input;

    float ratio = 16000.0f / (float)inputRate;
    size_t outSize = (size_t)(input.size() * ratio);
    std::vector<float> output(outSize);

    for (size_t i = 0; i < outSize; i++) {
        float srcIdx = (float)i / ratio;
        size_t idx0 = (size_t)srcIdx;
        size_t idx1 = (idx0 + 1 < input.size()) ? idx0 + 1 : idx0;
        float frac = srcIdx - (float)idx0;
        output[i] = input[idx0] * (1.0f - frac) + input[idx1] * frac;
    }

    return output;
}

std::vector<float> recordAudio(int durationSeconds) {
    s_recording.store(true);

    if (s_statusCallback) s_statusCallback("Recording audio...");

#ifdef __ANDROID__
    // On Android, we call Java AudioRecord via JNI
    // The Java side records audio and returns PCM data
    int targetSamples = durationSeconds * 16000;
    std::vector<int16_t> pcm16(targetSamples, 0);

    // Call Java to record audio
    // We'll use a platform function that calls AudioRecordJava
    std::string audioData = argos::recordAudioJava(durationSeconds);

    if (audioData.empty()) {
        s_recording.store(false);
        return {};
    }

    // The Java side returns base64 or raw bytes encoded as a string
    // For simplicity, we'll parse the raw 16-bit PCM from the byte string
    const char* data = audioData.data();
    size_t dataLen = audioData.size();
    size_t numSamples = dataLen / 2; // 16-bit = 2 bytes per sample

    pcm16.resize(numSamples);
    memcpy(pcm16.data(), data, numSamples * 2);

    s_recording.store(false);

    auto f32 = pcm16ToFloat(pcm16);
    return f32;

#else
    // Windows: use WaveIn API with chunked buffers for push-to-talk support
    #ifdef _WIN32
    const int sampleRate = 16000;
    const int channels = 1;
    const int bitsPerSample = 16;

    HWAVEIN hWaveIn;
    WAVEFORMATEX wfx;
    wfx.wFormatTag = WAVE_FORMAT_PCM;
    wfx.nChannels = channels;
    wfx.nSamplesPerSec = sampleRate;
    wfx.nAvgBytesPerSec = sampleRate * channels * (bitsPerSample / 8);
    wfx.nBlockAlign = channels * (bitsPerSample / 8);
    wfx.wBitsPerSample = bitsPerSample;
    wfx.cbSize = 0;

    if (waveInOpen(&hWaveIn, WAVE_MAPPER, &wfx, 0, 0, CALLBACK_NULL) != MMSYSERR_NOERROR) {
        s_recording.store(false);
        return {};
    }

    // Use small chunked buffers (0.5 seconds each) so stopRecording() captures partial audio
    const int chunkSamples = sampleRate / 2;  // 0.5 second = 8000 samples
    const int chunkBytes = chunkSamples * (bitsPerSample / 8) * channels;
    const int maxChunks = durationSeconds * 2;  // total chunks for max duration

    std::vector<int16_t> allPcm16;
    allPcm16.reserve(durationSeconds * sampleRate);

    for (int chunkIdx = 0; chunkIdx < maxChunks && s_recording.load(); chunkIdx++) {
        std::vector<int16_t> chunkBuf(chunkSamples, 0);
        WAVEHDR whdr;
        whdr.lpData = (LPSTR)chunkBuf.data();
        whdr.dwBufferLength = chunkBytes;
        whdr.dwBytesRecorded = 0;
        whdr.dwUser = 0;
        whdr.dwFlags = 0;
        whdr.dwLoops = 0;
        whdr.lpNext = nullptr;
        whdr.reserved = 0;

        if (waveInPrepareHeader(hWaveIn, &whdr, sizeof(WAVEHDR)) != MMSYSERR_NOERROR) break;
        if (waveInAddBuffer(hWaveIn, &whdr, sizeof(WAVEHDR)) != MMSYSERR_NOERROR) {
            waveInUnprepareHeader(hWaveIn, &whdr, sizeof(WAVEHDR));
            break;
        }

        if (chunkIdx == 0) waveInStart(hWaveIn);

        // Wait for this chunk to complete or recording to stop
        while (s_recording.load() && (whdr.dwFlags & WHDR_DONE) == 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(30));
        }

        // Stop the device if recording is done
        if (!s_recording.load()) {
            waveInStop(hWaveIn);
            // Give a brief moment for the buffer to be marked done
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }

        int recordedBytes = whdr.dwBytesRecorded;
        if (recordedBytes == 0 && (whdr.dwFlags & WHDR_DONE)) {
            recordedBytes = chunkBytes;
        }
        if (recordedBytes == 0 && chunkIdx == 0) {
            // First chunk with no data — device might need a moment
            recordedBytes = chunkBytes;
        }

        waveInUnprepareHeader(hWaveIn, &whdr, sizeof(WAVEHDR));

        if (recordedBytes > 0) {
            int recordedSamples = recordedBytes / (bitsPerSample / 8) / channels;
            allPcm16.insert(allPcm16.end(), chunkBuf.data(), chunkBuf.data() + recordedSamples);
        }
    }

    waveInReset(hWaveIn);
    waveInClose(hWaveIn);

    s_recording.store(false);

    if (allPcm16.empty()) {
        LOGE("recordAudio: no audio captured\n");
        return {};
    }

    LOGI("recordAudio: captured %zu samples (%.1f seconds)\n",
         allPcm16.size(), (float)allPcm16.size() / 16000.0f);

    return pcm16ToFloat(allPcm16);
    #else
    // Other platforms: not supported
    s_recording.store(false);
    return {};
    #endif
#endif
}

std::vector<float> recordAudioWithVAD(int maxDuration, float silenceThreshold) {
    // For simplicity, just record for the full duration
    // VAD can be improved later with chunked recording
    return recordAudio(maxDuration);
}

// TTS - platform native
bool ttsSpeak(const std::string& text) {
    std::string result = argos::ttsSpeakJava(text);
    return result.find("\"error\"") == std::string::npos;
}

bool ttsStop() {
    argos::ttsStopJava();
    return true;
}

bool ttsIsSpeaking() {
    std::string result = argos::ttsIsSpeakingJava();
    return result.find("true") != std::string::npos;
}

} // namespace argos
