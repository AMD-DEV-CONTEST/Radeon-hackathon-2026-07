#pragma once

#include <string>
#include <vector>
#include <functional>
#include <atomic>
#include <mutex>

namespace argos {

// Initialize whisper.cpp with a model file
// modelPath: path to ggml whisper model (e.g. ggml-base.en.bin or ggml-tiny.en.bin)
// Returns true on success
bool whisperInit(const std::string& modelPath);

// Check if whisper is initialized
bool whisperIsReady();

// Get the model path currently loaded
std::string whisperGetModelPath();

// Transcribe audio samples (16kHz mono float32 PCM) to text
// samples: raw audio data in float32 format, 16kHz mono
// Returns transcribed text
std::string whisperTranscribe(const std::vector<float>& samples);

// Record audio from microphone for a given duration (seconds)
// Returns float32 PCM samples at 16kHz mono
// On Android: uses AudioRecord via JNI
// On Windows: uses WaveIn API
std::vector<float> recordAudio(int durationSeconds);

// Record audio with early stop (silence detection or manual stop)
// maxDuration: maximum recording time in seconds
// silenceThreshold: if audio level drops below this for >2s, stop early
// Returns float32 PCM samples at 16kHz mono
std::vector<float> recordAudioWithVAD(int maxDuration, float silenceThreshold = 0.01f);

// Stop any ongoing recording
void stopRecording();

// Check if currently recording
bool isRecording();

// Text-to-Speech (platform native, no GPL dependencies)
// Android: uses android.speech.tts.TextToSpeech
// Windows: uses SAPI SpVoice
bool ttsSpeak(const std::string& text);
bool ttsStop();
bool ttsIsSpeaking();

// Set callback for recording status updates
void setRecordingStatusCallback(std::function<void(const std::string&)> callback);

} // namespace argos
