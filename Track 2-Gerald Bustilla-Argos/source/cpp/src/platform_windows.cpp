// Windows platform implementation for voice/audio functions.
// Implements the argos:: platform functions declared in platform.h
// using Win32 WaveIn API for audio recording and SAPI for TTS.

#include "../../src_cross/platform.h"
#include <windows.h>
#include <mmsystem.h>
#include <sapi.h>
#include <cstdio>
#include <cstring>
#include <vector>
#include <chrono>
#include <thread>

#pragma comment(lib, "winmm.lib")
#pragma comment(lib, "ole32.lib")

namespace argos {

static ISpVoice* s_spVoice = nullptr;

std::string recordAudioJava(int durationSeconds) {
    const int sampleRate = 16000;
    const int channels = 1;
    const int bitsPerSample = 16;
    int totalSamples = durationSeconds * sampleRate;
    int bufferSize = totalSamples * (bitsPerSample / 8) * channels;

    HWAVEIN hWaveIn;
    WAVEFORMATEX wfx = {};
    wfx.wFormatTag = WAVE_FORMAT_PCM;
    wfx.nChannels = channels;
    wfx.nSamplesPerSec = sampleRate;
    wfx.nAvgBytesPerSec = sampleRate * channels * (bitsPerSample / 8);
    wfx.nBlockAlign = channels * (bitsPerSample / 8);
    wfx.wBitsPerSample = bitsPerSample;
    wfx.cbSize = 0;

    if (waveInOpen(&hWaveIn, WAVE_MAPPER, &wfx, 0, 0, CALLBACK_NULL) != MMSYSERR_NOERROR) {
        return "";
    }

    std::vector<int16_t> pcm16(totalSamples, 0);
    WAVEHDR whdr = {};
    whdr.lpData = (LPSTR)pcm16.data();
    whdr.dwBufferLength = bufferSize;
    whdr.dwFlags = 0;

    waveInPrepareHeader(hWaveIn, &whdr, sizeof(WAVEHDR));
    waveInAddBuffer(hWaveIn, &whdr, sizeof(WAVEHDR));
    waveInStart(hWaveIn);

    // Wait for recording to complete
    while ((whdr.dwFlags & WHDR_DONE) == 0) {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    waveInStop(hWaveIn);
    waveInUnprepareHeader(hWaveIn, &whdr, sizeof(WAVEHDR));
    waveInClose(hWaveIn);

    // Return raw PCM bytes as string
    return std::string((const char*)pcm16.data(), totalSamples * 2);
}

std::string ttsSpeakJava(const std::string& text) {
    // Initialize COM if needed
    HRESULT hrCo = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(hrCo) && hrCo != RPC_E_CHANGED_MODE) {
        return "{\"error\":\"COM init failed\"}";
    }

    // Initialize SAPI if needed
    if (!s_spVoice) {
        HRESULT hr = CoCreateInstance(CLSID_SpVoice, nullptr, CLSCTX_ALL, IID_ISpVoice, (void**)&s_spVoice);
        if (FAILED(hr) || !s_spVoice) {
            return "{\"error\":\"SAPI TTS not available\"}";
        }
    }

    // Convert string to wide string for SAPI
    int wlen = MultiByteToWideChar(CP_UTF8, 0, text.c_str(), (int)text.size(), nullptr, 0);
    if (wlen <= 0) {
        return "{\"error\":\"Text conversion failed\"}";
    }
    std::wstring wtext(wlen, 0);
    MultiByteToWideChar(CP_UTF8, 0, text.c_str(), (int)text.size(), &wtext[0], wlen);

    HRESULT hr = s_spVoice->Speak(wtext.c_str(), SPF_ASYNC, nullptr);
    if (SUCCEEDED(hr)) {
        return "{\"status\":\"speaking\",\"text\":\"" + text + "\"}";
    }
    return "{\"error\":\"TTS speak failed\"}";
}

std::string ttsStopJava() {
    if (s_spVoice) {
        s_spVoice->Speak(L"", SPF_PURGEBEFORESPEAK, nullptr);
    }
    return "{\"status\":\"stopped\"}";
}

std::string ttsIsSpeakingJava() {
    if (s_spVoice) {
        SPVOICESTATUS status;
        s_spVoice->GetStatus(&status, nullptr);
        if (status.dwRunningState == SPRS_IS_SPEAKING) {
            return "{\"speaking\":true}";
        }
    }
    return "{\"speaking\":false}";
}

} // namespace argos
