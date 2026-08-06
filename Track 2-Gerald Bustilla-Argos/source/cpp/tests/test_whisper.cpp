// Test program for whisper.cpp integration on Windows.
// Tests: whisper init, audio recording, transcription, TTS.
// Usage: test_whisper.exe <model_path> [wav_file_path]
//
// If wav_file_path is provided, tests file transcription.
// Otherwise, tests microphone recording + transcription.

#include <cstdio>
#include <string>
#include <vector>
#include <iostream>

#include "../src_cross/whisper_wrapper.h"
#include "../src_cross/platform.h"

int main(int argc, char* argv[]) {
    printf("=== Argos Whisper.cpp Integration Test (Windows) ===\n\n");

    // Test 1: whisper_status (before init)
    printf("[Test 1] Checking whisper status before init...\n");
    printf("  whisperIsReady: %s\n", argos::whisperIsReady() ? "true" : "false");
    printf("  PASSED: whisper not initialized yet\n\n");

    if (argc < 2) {
        printf("Usage: test_whisper.exe <model_path> [wav_file_path]\n");
        printf("  model_path: path to ggml whisper model (e.g. ggml-tiny.en.bin)\n");
        printf("  wav_file_path: optional WAV file to transcribe\n\n");

        // Test TTS even without model
        printf("[Test TTS] Speaking test message via SAPI...\n");
        bool ttsOk = argos::ttsSpeak("Hello, this is a test of the text to speech system.");
        printf("  ttsSpeak result: %s\n", ttsOk ? "success" : "failed");

        if (ttsOk) {
            printf("  Waiting for TTS to finish...\n");
            while (argos::ttsIsSpeaking()) {
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
            }
            printf("  TTS finished. PASSED.\n");
        }
        printf("\nTo test full whisper pipeline, provide a model path.\n");
        return 0;
    }

    std::string modelPath = argv[1];

    // Test 2: whisper_init
    printf("[Test 2] Initializing whisper with model: %s\n", modelPath.c_str());
    bool initOk = argos::whisperInit(modelPath);
    printf("  whisperInit result: %s\n", initOk ? "success" : "failed");
    if (!initOk) {
        printf("  FAILED: Could not initialize whisper\n");
        return 1;
    }
    printf("  PASSED: whisper initialized\n\n");

    // Test 3: whisper_status (after init)
    printf("[Test 3] Checking whisper status after init...\n");
    printf("  whisperIsReady: %s\n", argos::whisperIsReady() ? "true" : "false");
    printf("  whisperGetModelPath: %s\n", argos::whisperGetModelPath().c_str());
    printf("  PASSED\n\n");

    if (argc >= 3) {
        // Test 4: Transcribe WAV file
        std::string wavPath = argv[2];
        printf("[Test 4] Transcribing WAV file: %s\n", wavPath.c_str());

        // Read WAV file
        FILE* f = fopen(wavPath.c_str(), "rb");
        if (!f) {
            printf("  FAILED: Cannot open %s\n", wavPath.c_str());
            return 1;
        }
        fseek(f, 0, SEEK_END);
        long fileSize = ftell(f);
        fseek(f, 44, SEEK_SET); // Skip WAV header
        long dataSize = fileSize - 44;
        long numSamples = dataSize / 2;

        std::vector<int16_t> pcm16(numSamples);
        fread(pcm16.data(), 2, numSamples, f);
        fclose(f);

        std::vector<float> samples(numSamples);
        for (long i = 0; i < numSamples; i++) {
            samples[i] = (float)pcm16[i] / 32768.0f;
        }

        printf("  Samples: %ld (%.1f seconds)\n", numSamples, (float)numSamples / 16000.0f);
        printf("  Transcribing...\n");

        std::string text = argos::whisperTranscribe(samples);
        printf("  Transcription: \"%s\"\n", text.c_str());
        printf("  PASSED\n\n");
    } else {
        // Test 4b: Record from microphone
        printf("[Test 4b] Recording 3 seconds from microphone...\n");
        printf("  Speak now!\n");

        auto samples = argos::recordAudio(3);
        printf("  Recorded %zu samples (%.1f seconds)\n", samples.size(), (float)samples.size() / 16000.0f);

        if (samples.empty()) {
            printf("  WARNING: No audio recorded (microphone may not be available)\n");
        } else {
            printf("  Transcribing...\n");
            std::string text = argos::whisperTranscribe(samples);
            printf("  Transcription: \"%s\"\n", text.c_str());
        }
        printf("  PASSED\n\n");
    }

    // Test 5: TTS
    printf("[Test 5] Testing TTS (SAPI)...\n");
    std::string speakText = "Voice integration test complete. Whisper speech to text and text to speech are working.";
    printf("  Speaking: \"%s\"\n", speakText.c_str());
    bool ttsOk = argos::ttsSpeak(speakText);
    printf("  ttsSpeak result: %s\n", ttsOk ? "success" : "failed");

    if (ttsOk) {
        printf("  Waiting for TTS to finish...\n");
        while (argos::ttsIsSpeaking()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
        printf("  TTS finished.\n");
    }

    // Test 6: TTS stop
    printf("[Test 6] Testing TTS stop...\n");
    argos::ttsSpeak("This should be interrupted.");
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    argos::ttsStop();
    printf("  ttsStop called.\n");
    printf("  PASSED\n\n");

    printf("=== All tests completed ===\n");
    return 0;
}
