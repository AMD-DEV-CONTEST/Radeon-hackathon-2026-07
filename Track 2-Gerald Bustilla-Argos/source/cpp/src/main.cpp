// Argos — Agentic AI Desktop Companion (C++ native Win32 + Direct2D)
// Named after Argos, the faithful dog of Odysseus.

#include "window_manager.h"
#include "tray_icon.h"
#include "robot_renderer.h"
#include "agent_client.h"
#include "argos_tools.h"
#include "../src_cross/whisper_wrapper.h"
#include "resource.h"

#include <windows.h>
#include <windowsx.h>
#include <shellapi.h>
#include <commctrl.h>
#include <string>
#include <vector>
#include <thread>
#include <atomic>
#include <mutex>
#include <richedit.h>
#include <random>
#include <chrono>
#include <ctime>

#pragma comment(lib, "comctl32.lib")

static HMODULE g_richEditDll = nullptr;

// Control IDs (needed early by voice functions)
#define IDC_BUBBLE_EDIT   3001
#define IDC_BUBBLE_SEND   3002
#define IDC_BUBBLE_VOICE  3003

// Custom messages (needed early by voice functions)
#define WM_CHAT_RESPONSE (WM_USER + 100)
#define WM_CHAT_ERROR    (WM_USER + 101)
#define WM_PROACTIVE_RESPONSE (WM_USER + 102)
#define WM_CHAT_STREAM   (WM_USER + 103)
#define WM_VOICE_RESULT  (WM_USER + 105)
#define WM_VOICE_ERROR   (WM_USER + 106)
#define WM_CAPSLOCK_PUSHTOTALK (WM_USER + 107)

// Forward declarations (globals defined later)
static WindowManager* g_windowMgr = nullptr;
static HWND g_bubbleHwnd = nullptr;
static void ShowMangaBubble(HINSTANCE hInstance, HWND parent);

// True when the speech bubble is below the robot (robot at top of screen)
// In this case, the tail should point UP toward the robot instead of down
static bool g_bubbleBelowRobot = false;

// ── Voice / Whisper state ──
static bool g_whisperAutoInitTried = false;
static bool g_voiceRecording = false;
static std::vector<float> g_voiceSamples;
static std::mutex g_voiceMutex;
static std::wstring g_voiceTranscribedText;
static std::wstring g_voiceErrorMsg;
static HWND g_voiceBubbleHwnd = nullptr;  // bubble hwnd to send result to

// ── Caps Lock push-to-talk ──
static HHOOK g_kbHook = nullptr;
static bool g_capsLockPressed = false;
static std::chrono::steady_clock::time_point g_capsLockPressTime;
static std::atomic<bool> g_capsLockRecording(false);
static bool g_autoTTS = true;  // Auto-read AI responses aloud

// Try to auto-init whisper from common model paths
static bool TryAutoInitWhisper() {
    if (argos::whisperIsReady()) return true;
    if (g_whisperAutoInitTried) return false;
    g_whisperAutoInitTried = true;

    // Common locations to look for the model
    const char* paths[] = {
        "ggml-tiny.en.bin",
        "models/ggml-tiny.en.bin",
        "../ggml-tiny.en.bin",
        "build/ggml-tiny.en.bin",
        "build/Release/ggml-tiny.en.bin",
        "build/Debug/ggml-tiny.en.bin",
    };
    for (const char* p : paths) {
        FILE* f = nullptr;
        if (fopen_s(&f, p, "rb") == 0 && f) {
            fclose(f);
            if (argos::whisperInit(p)) return true;
        }
    }
    return false;
}

// Start voice recording + transcription in background, then send to AI
// maxDuration: max recording time (for push-to-talk, stopRecording() stops early)
static void StartVoiceRecording(HWND bubbleHwnd, int maxDuration = 5) {
    if (g_voiceRecording) return;

    // Try auto-init whisper
    if (!TryAutoInitWhisper()) {
        MessageBoxW(bubbleHwnd,
            L"Whisper model not found.\n\n"
            L"Download ggml-tiny.en.bin (~75MB) from:\n"
            L"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin\n\n"
            L"Place it in the same folder as argos.exe or use:\n"
            L"[TOOL:whisper_init <path_to_model>]",
            L"Argos — Voice Setup Needed", MB_OK | MB_ICONINFORMATION);
        return;
    }

    g_voiceBubbleHwnd = bubbleHwnd;
    g_voiceRecording = true;

    // Show recording indicator in the bubble
    if (bubbleHwnd) {
        HWND hEdit = GetDlgItem(bubbleHwnd, IDC_BUBBLE_EDIT);
        if (hEdit) SetWindowTextW(hEdit, L"\U0001F3A4 Listening... (release to send)");
    }

    // Record + transcribe in background thread
    std::thread([bubbleHwnd, maxDuration]() {
        // Record audio (stopRecording() can break the loop early)
        std::vector<float> samples = argos::recordAudio(maxDuration);

        std::string text = argos::whisperTranscribe(samples);

        {
            std::lock_guard<std::mutex> lk(g_voiceMutex);
            // Convert UTF-8 to wide
            if (!text.empty()) {
                int wlen = MultiByteToWideChar(CP_UTF8, 0, text.c_str(), (int)text.size(), nullptr, 0);
                g_voiceTranscribedText.resize(wlen);
                MultiByteToWideChar(CP_UTF8, 0, text.c_str(), (int)text.size(), &g_voiceTranscribedText[0], wlen);
            } else {
                g_voiceTranscribedText = L"";
            }
        }

        g_voiceRecording = false;
        PostMessageW(bubbleHwnd, WM_VOICE_RESULT, 0, 0);
    }).detach();
}

// Low-level keyboard hook for Caps Lock push-to-talk
static LRESULT CALLBACK LowLevelKbProc(int nCode, WPARAM wParam, LPARAM lParam) {
    if (nCode == HC_ACTION) {
        KBDLLHOOKSTRUCT* kb = (KBDLLHOOKSTRUCT*)lParam;
        if (kb->vkCode == VK_CAPITAL) {
            if (wParam == WM_KEYDOWN || wParam == WM_SYSKEYDOWN) {
                if (!g_capsLockPressed) {
                    g_capsLockPressed = true;
                    g_capsLockPressTime = std::chrono::steady_clock::now();
                    // Start push-to-talk recording immediately
                    g_capsLockRecording.store(true);
                    if (g_windowMgr && g_windowMgr->GetHwnd()) {
                        PostMessageW(g_windowMgr->GetHwnd(), WM_CAPSLOCK_PUSHTOTALK, 0, 0);
                    }
                }
                // Swallow Caps Lock to prevent toggling
                return 1;
            } else if (wParam == WM_KEYUP || wParam == WM_SYSKEYUP) {
                if (g_capsLockPressed) {
                    g_capsLockPressed = false;
                    auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                        std::chrono::steady_clock::now() - g_capsLockPressTime).count();

                    if (elapsed > 200) {
                        // Long press = push-to-talk: stop recording, transcribe+send
                        g_capsLockRecording.store(false);
                        argos::stopRecording();
                    } else {
                        // Short press (<200ms) = cancel recording (too brief)
                        g_capsLockRecording.store(false);
                        argos::stopRecording();
                    }
                }
                return 1;
            }
        }
    }
    return CallNextHookEx(g_kbHook, nCode, wParam, lParam);
}

// ── Proactive Argos system — makes Argos alive ──
#define IDT_PROACTIVE 1003
#define IDT_PROACTIVE_BUBBLE_TIMEOUT 1004
#define IDT_VOICE_DELAYED 1005
static bool g_proactiveActive = true;
static bool g_proactiveBusy = false;
static HWND g_proactiveBubble = nullptr;
static std::wstring g_proactiveMsg;
static std::wstring g_proactiveContext;

// Proactive interval: every 10 seconds — Argos checks in like a friend
static int GetRandomProactiveInterval() {
    return 10000; // 10 seconds
}

// Random variety pick for proactive personality — conversational friend/advisor modes
static const wchar_t* GetRandomPersonalityHint() {
    static const wchar_t* hints[] = {
        // Ask what they're doing — curious friend
        L"Ask them what they're working on right now. Be genuinely curious, like a friend peeking over their shoulder.",
        // Observe and react — like a friend who sees your screen
        L"Notice what app they're using and react to it. Like 'Ooh, looks like you're deep in code!' or 'Nice, you're watching YouTube? Don't tell your boss!'",
        // Suggest something helpful — advisor mode
        L"Suggest something helpful based on what they're doing. Like a smart friend who knows a better shortcut or tool.",
        // Chit-chat — casual friend
        L"Just chit-chat casually. Talk about something random — the weather, coffee, how their day is going. Keep it light and fun.",
        // Praise and encourage — supportive friend
        L"Notice their work and praise it. Say something like 'You're crushing it today!' or 'That looks like serious work, respect!'",
        // Tease playfully — close friend
        L"Playfully tease them about what they're doing. Like a close friend who jokes around. Keep it friendly, never mean.",
        // Share a thought — thoughtful friend
        L"Share a brief random thought or fun fact. Something interesting that makes them go 'huh, nice!'",
        // Offer help — loyal companion
        L"Offer to help with whatever they're doing. Like 'Need me to search anything for you?' or 'Want me to look something up?'",
        // Check on their wellbeing — caring friend
        L"Check on how they're feeling. Ask if they need a break, suggest stretching or getting water. Be caring but not preachy.",
        // Make a witty observation — funny friend
        L"Make a witty or sarcastic observation about their screen activity. Like a friend who sees you procrastinating and calls you out lovingly.",
        // React to specific app — engaged friend
        L"If you can tell what app or website they're on, make a specific comment about it. Like you actually know what that app is.",
        // Share energy — hype friend
        L"Hype them up! Bring some energy. Like 'Let's gooo, time to get things done!' or 'You got this!'",
    };
    static std::mt19937 rng(std::random_device{}());
    std::uniform_int_distribution<int> dist(0, 11);
    return hints[dist(rng)];
}

// Filter out sensitive information from screen context before sending to AI
static std::string FilterSensitiveInfo(const std::string& text) {
    std::string result = text;
    // List of sensitive keywords to redact
    const char* sensitiveWords[] = {
        "password", "passwd", "pwd", "secret", "api_key", "apikey",
        "api-key", "token", "access_key", "private_key", "credential",
        "ssn", "social security", "credit card", "card number",
        "cvv", "pin code", "passcode", "otp", "2fa"
    };
    for (const char* word : sensitiveWords) {
        std::string wordStr(word);
        size_t pos = 0;
        while ((pos = result.find(wordStr, pos)) != std::string::npos) {
            // Replace the value after the keyword (up to end of line or 50 chars)
            size_t valueStart = pos + wordStr.size();
            // Find end of value (newline, comma, quote, or 50 chars)
            size_t valueEnd = result.find_first_of("\n,\"]}", valueStart);
            if (valueEnd == std::string::npos) valueEnd = (std::min)(valueStart + 50, result.size());
            // Replace the keyword + value with redacted text
            result.replace(pos, valueEnd - pos, "[" + wordStr + ": REDACTED]");
            pos += wordStr.size() + 12; // skip past the redacted marker
        }
    }
    return result;
}

// Gather screen context using direct Win32 API calls (fast, reliable, no dependencies)
// Includes privacy filtering: redacts sensitive information from window titles
static std::wstring GatherScreenContext() {
    std::wstring context;

    // ── Privacy filter: redact sensitive keywords from text ──
    auto filterSensitive = [](std::wstring text) -> std::wstring {
        // List of sensitive keywords to redact (case-insensitive)
        const wchar_t* sensitiveWords[] = {
            L"password", L"passwd", L"api_key", L"apikey", L"token",
            L"secret", L"credential", L"private_key", L"access_key",
            L"credit card", L"card number", L"ssn", L"social security",
            L"bank account", L"routing number", L"pin number"
        };
        for (const auto& word : sensitiveWords) {
            size_t pos = 0;
            while ((pos = text.find(word, pos)) != std::wstring::npos) {
                // Find the extent of the sensitive data (until space, =, or end)
                size_t end = pos + wcslen(word);
                // If followed by = or :, redact the value too
                if (end < text.size() && (text[end] == L'=' || text[end] == L':')) {
                    end++;
                    while (end < text.size() && text[end] != L' ' && text[end] != L'\n' && text[end] != L'\r')
                        end++;
                }
                text.replace(pos, end - pos, L"[REDACTED]");
                pos += wcslen(L"[REDACTED]");
            }
        }
        // Also redact patterns like "1234-5678-9012-3456" (card-like numbers)
        // Simple heuristic: long digit sequences with dashes
        size_t pos = 0;
        while ((pos = text.find_first_of(L"0123456789", pos)) != std::wstring::npos) {
            size_t end = pos;
            int dashCount = 0;
            int digitCount = 0;
            while (end < text.size() && (iswdigit(text[end]) || text[end] == L'-')) {
                if (iswdigit(text[end])) digitCount++;
                if (text[end] == L'-') dashCount++;
                end++;
            }
            if (digitCount >= 12 && dashCount >= 2) {
                text.replace(pos, end - pos, L"[REDACTED-CARD]");
                pos += wcslen(L"[REDACTED-CARD]");
            } else {
                pos = end;
            }
        }
        return text;
    };

    // Get foreground window title
    HWND fg = GetForegroundWindow();
    if (fg) {
        wchar_t title[256] = {};
        GetWindowTextW(fg, title, 256);
        if (title[0]) {
            std::wstring filteredTitle = filterSensitive(title);
            context += L"Active window: \"";
            context += filteredTitle;
            context += L"\"\n";
        }

        // Get process name
        DWORD pid = 0;
        GetWindowThreadProcessId(fg, &pid);
        if (pid) {
            HANDLE hProc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
            if (hProc) {
                wchar_t procName[MAX_PATH] = {};
                DWORD size = MAX_PATH;
                if (QueryFullProcessImageNameW(hProc, 0, procName, &size)) {
                    // Extract just the filename
                    std::wstring path(procName);
                    size_t slash = path.find_last_of(L"\\/");
                    if (slash != std::string::npos)
                        context += L"Active process: " + path.substr(slash + 1) + L"\n";
                    else
                        context += L"Active process: " + path + L"\n";
                }
                CloseHandle(hProc);
            }
        }
    }

    // List visible windows (top 10)
    struct EnumData {
        std::vector<std::wstring>* windows;
        int count;
    };
    std::vector<std::wstring> visibleWindows;
    EnumData data{&visibleWindows, 0};
    EnumWindows([](HWND hwnd, LPARAM lParam) -> BOOL {
        EnumData* d = reinterpret_cast<EnumData*>(lParam);
        if (!IsWindowVisible(hwnd)) return TRUE;
        if (IsIconic(hwnd)) return TRUE;
        wchar_t title[256] = {};
        GetWindowTextW(hwnd, title, 256);
        if (title[0] && d->count < 10) {
            d->windows->push_back(std::wstring(title));
            d->count++;
        }
        return TRUE;
    }, reinterpret_cast<LPARAM>(&data));

    if (!visibleWindows.empty()) {
        context += L"Open windows: ";
        for (size_t i = 0; i < visibleWindows.size(); i++) {
            if (i > 0) context += L", ";
            context += L"\"" + filterSensitive(visibleWindows[i]) + L"\"";
        }
        context += L"\n";
    }

    if (context.empty()) {
        context = L"User is at their desktop. No active window detected.";
    }

    return context;
}

// ── Color palette (used by RefreshConversation and BubbleWndProc) ──
// Neon blue palette (matches Argos's eye color)
#define NEON_BLUE      RGB(0, 207, 255)
#define NEON_BLUE_DIM  RGB(120, 220, 255)
#define NEON_BLUE_GLOW RGB(200, 245, 255)
#define NEON_BLUE_BAR  RGB(0, 180, 235)
#define TEXT_DARK      RGB(20, 20, 20)
#define TEXT_BLACK     RGB(0, 0, 0)
#define TEXT_NEON      RGB(0, 160, 220)

// Modern dark theme colors
#define DARK_BG        RGB(24, 24, 28)
#define DARK_BG_HEADER RGB(32, 32, 38)
#define DARK_CONV_BG   RGB(28, 28, 34)
#define DARK_INPUT_BG  RGB(38, 38, 44)
#define DARK_BTN_BG    RGB(44, 44, 52)
#define DARK_BTN_HOVER RGB(58, 58, 68)
#define DARK_SEND_BG   RGB(0, 120, 215)
#define DARK_EXIT_BG   RGB(80, 30, 30)
#define TEXT_LIGHT     RGB(230, 230, 235)
#define TEXT_DIM       RGB(140, 140, 150)
#define BUBBLE_USER    RGB(0, 120, 215)
#define BUBBLE_ARGOS   RGB(45, 45, 52)
#define TEXT_USER      RGB(255, 255, 255)
#define TEXT_ARGOS     RGB(225, 225, 230)
#define DRAG_HANDLE    RGB(60, 60, 70)

// Forward declaration
static std::wstring StripThinkTags(const std::wstring& text);

// Chat history entry: user message + assistant response
struct ChatEntry {
    std::wstring userMsg;
    std::wstring assistantMsg;
    bool isVoice = false;
};
static std::vector<ChatEntry> g_chatHistory;
static std::atomic<bool> g_chatInProgress(false);
static std::wstring g_lastUserMsg;
static std::wstring g_pendingResponse;
static std::wstring g_streamingPartial;  // Accumulated streaming text
static std::mutex g_streamingMutex;      // Protects g_streamingPartial (written on bg thread, read on UI thread)

// Control ID for conversation display (needed by RefreshConversation)
#define IDC_BUBBLE_CONVO 3015

// Loading animation timer
#define IDT_LOADING 1002
static int g_loadingDots = 0;
static int g_loadingTickCount = 0; // Watchdog: counts loading timer ticks (300ms each)
// Track where the thinking indicator starts in the Rich Edit (for in-place updates)
static LRESULT g_thinkingStartPos = -1;

// Check if user is scrolled to the bottom of the Rich Edit
static bool IsScrolledToBottom(HWND hConvo) {
    SCROLLINFO si = {};
    si.cbSize = sizeof(si);
    si.fMask = SIF_ALL;
    GetScrollInfo(hConvo, SB_VERT, &si);
    // Allow 20px tolerance
    return (si.nPos + (int)si.nPage >= si.nMax - 20);
}

// Refresh the conversation Rich Edit control with modern Messenger-style
// message bubbles: user messages with blue background + white text on right,
// Argos messages with light gray background + black text on left.
// Only auto-scrolls if user was already at the bottom.
static void RefreshConversation(HWND hwnd) {
    HWND hConvo = GetDlgItem(hwnd, IDC_BUBBLE_CONVO);
    if (!hConvo) return;

    // Check if user is at the bottom BEFORE we rebuild
    bool wasAtBottom = IsScrolledToBottom(hConvo);

    // Clear all text
    SetWindowTextW(hConvo, L"");

    // Paragraph format for spacing and alignment
    PARAFORMAT2 pf = {};
    pf.cbSize = sizeof(pf);

    // ── User message bubble format: blue bg, white text, right-aligned ──
    CHARFORMAT2W cfUser = {};
    cfUser.cbSize = sizeof(cfUser);
    cfUser.dwMask = CFM_COLOR | CFM_BACKCOLOR | CFM_BOLD;
    cfUser.dwEffects = CFE_BOLD;
    cfUser.crTextColor = TEXT_USER;                // white text
    cfUser.crBackColor = BUBBLE_USER;              // blue bubble
    cfUser.bPitchAndFamily = DEFAULT_PITCH | FF_SWISS;

    // ── User sender label format: small, light blue, right-aligned ──
    CHARFORMAT2W cfUserLabel = {};
    cfUserLabel.cbSize = sizeof(cfUserLabel);
    cfUserLabel.dwMask = CFM_COLOR | CFM_BACKCOLOR | CFM_SIZE | CFM_BOLD;
    cfUserLabel.dwEffects = CFE_BOLD;
    cfUserLabel.crTextColor = RGB(180, 210, 240);
    cfUserLabel.crBackColor = BUBBLE_USER;
    cfUser.yHeight = 180; // 9pt

    // ── Argos message bubble format: dark gray bg, light text, left-aligned ──
    CHARFORMAT2W cfArgos = {};
    cfArgos.cbSize = sizeof(cfArgos);
    cfArgos.dwMask = CFM_COLOR | CFM_BACKCOLOR;
    cfArgos.crTextColor = TEXT_ARGOS;              // light text
    cfArgos.crBackColor = BUBBLE_ARGOS;            // dark gray bubble

    // ── Argos sender label format: neon blue bold ──
    CHARFORMAT2W cfArgosLabel = {};
    cfArgosLabel.cbSize = sizeof(cfArgosLabel);
    cfArgosLabel.dwMask = CFM_COLOR | CFM_BACKCOLOR | CFM_BOLD;
    cfArgosLabel.dwEffects = CFE_BOLD;
    cfArgosLabel.crTextColor = NEON_BLUE;          // neon blue
    cfArgosLabel.crBackColor = BUBBLE_ARGOS;       // dark gray
    cfArgosLabel.yHeight = 200; // 10pt

    // ── Thinking format: dim italic ──
    CHARFORMAT2W cfThink = {};
    cfThink.cbSize = sizeof(cfThink);
    cfThink.dwMask = CFM_COLOR | CFM_BACKCOLOR | CFM_ITALIC;
    cfThink.dwEffects = CFE_ITALIC;
    cfThink.crTextColor = TEXT_DIM;
    cfThink.crBackColor = BUBBLE_ARGOS;

    // ── Spacing format (blank line between messages) ──
    CHARFORMAT2W cfSpacer = {};
    cfSpacer.cbSize = sizeof(cfSpacer);
    cfSpacer.dwMask = CFM_COLOR | CFM_BACKCOLOR;
    cfSpacer.crTextColor = DARK_CONV_BG;
    cfSpacer.crBackColor = DARK_CONV_BG;

    for (const auto& entry : g_chatHistory) {
        // ── User message bubble (right-aligned, blue) ──
        pf.dwMask = PFM_ALIGNMENT | PFM_SPACEBEFORE | PFM_SPACEAFTER | PFM_OFFSET;
        pf.wAlignment = PFA_RIGHT;
        pf.dySpaceBefore = 120;  // 6px gap above
        pf.dySpaceAfter = 0;
        pf.dxOffset = 0;
        pf.dxStartIndent = 0;
        SendMessageW(hConvo, EM_SETPARAFORMAT, 0, (LPARAM)&pf);

        // User sender label
        SendMessageW(hConvo, EM_SETCHARFORMAT, SCF_SELECTION, (LPARAM)&cfUserLabel);
        SendMessageW(hConvo, EM_REPLACESEL, FALSE, (LPARAM)L"You\r\n");

        // User message body
        SendMessageW(hConvo, EM_SETCHARFORMAT, SCF_SELECTION, (LPARAM)&cfUser);
        std::wstring userLine = entry.userMsg + L"\r\n";
        SendMessageW(hConvo, EM_REPLACESEL, FALSE, (LPARAM)userLine.c_str());

        // ── Argos response bubble (left-aligned, gray) ──
        if (!entry.assistantMsg.empty()) {
            pf.wAlignment = PFA_LEFT;
            pf.dySpaceBefore = 120;  // 6px gap
            pf.dySpaceAfter = 0;
            SendMessageW(hConvo, EM_SETPARAFORMAT, 0, (LPARAM)&pf);

            // Argos sender label
            SendMessageW(hConvo, EM_SETCHARFORMAT, SCF_SELECTION, (LPARAM)&cfArgosLabel);
            SendMessageW(hConvo, EM_REPLACESEL, FALSE, (LPARAM)L"Argos\r\n");

            // Argos message body
            SendMessageW(hConvo, EM_SETCHARFORMAT, SCF_SELECTION, (LPARAM)&cfArgos);
            std::wstring argosLine = entry.assistantMsg + L"\r\n";
            SendMessageW(hConvo, EM_REPLACESEL, FALSE, (LPARAM)argosLine.c_str());
        }
    }

    // ── Thinking indicator bubble (left-aligned, gray, animated) ──
    if (g_chatInProgress.load()) {
        // Record position where thinking indicator starts — BEFORE adding it
        g_thinkingStartPos = SendMessageW(hConvo, WM_GETTEXTLENGTH, 0, 0);

        pf.wAlignment = PFA_LEFT;
        pf.dySpaceBefore = 120;
        pf.dySpaceAfter = 0;
        SendMessageW(hConvo, EM_SETPARAFORMAT, 0, (LPARAM)&pf);

        // "Argos" label
        SendMessageW(hConvo, EM_SETCHARFORMAT, SCF_SELECTION, (LPARAM)&cfArgosLabel);
        SendMessageW(hConvo, EM_REPLACESEL, FALSE, (LPARAM)L"Argos\r\n");

        // Animated thinking text
        SendMessageW(hConvo, EM_SETCHARFORMAT, SCF_SELECTION, (LPARAM)&cfThink);
        const wchar_t* dots[] = { L".  .  .", L"*  .  .", L".  *  .", L".  .  *" };
        std::wstring thinking = L"Thinking " + std::wstring(dots[g_loadingDots % 4]) + L"\r\n";
        SendMessageW(hConvo, EM_REPLACESEL, FALSE, (LPARAM)thinking.c_str());
    }

    // Only auto-scroll if user was already at the bottom
    if (wasAtBottom) {
        LRESULT textLen = SendMessageW(hConvo, WM_GETTEXTLENGTH, 0, 0);
        SendMessageW(hConvo, EM_SETSEL, textLen, textLen);
        SendMessageW(hConvo, EM_SCROLLCARET, 0, 0);
    }
}

// Update only the thinking dots without rebuilding the entire conversation.
// This preserves scroll position when the user is reading history.
static void UpdateThinkingDots(HWND hwnd) {
    HWND hConvo = GetDlgItem(hwnd, IDC_BUBBLE_CONVO);
    if (!hConvo) return;
    if (!g_chatInProgress.load()) return;
    if (g_thinkingStartPos < 0) return; // not initialized yet

    // Check if user is at the bottom
    bool wasAtBottom = IsScrolledToBottom(hConvo);

    LRESULT textLen = SendMessageW(hConvo, WM_GETTEXTLENGTH, 0, 0);

    // Select from thinking start to end and delete it
    SendMessageW(hConvo, EM_SETSEL, g_thinkingStartPos, textLen);
    SendMessageW(hConvo, EM_REPLACESEL, FALSE, (LPARAM)L"");

    // Now insert new thinking indicator at the same position
    // Set cursor to thinking start
    SendMessageW(hConvo, EM_SETSEL, g_thinkingStartPos, g_thinkingStartPos);

    // Paragraph format
    PARAFORMAT2 pf = {};
    pf.cbSize = sizeof(pf);
    pf.dwMask = PFM_ALIGNMENT | PFM_SPACEBEFORE | PFM_SPACEAFTER;
    pf.wAlignment = PFA_LEFT;
    pf.dySpaceBefore = 120;
    pf.dySpaceAfter = 0;
    SendMessageW(hConvo, EM_SETPARAFORMAT, 0, (LPARAM)&pf);

    // "Argos" label: neon blue bold on dark gray
    CHARFORMAT2W cfLabel = {};
    cfLabel.cbSize = sizeof(cfLabel);
    cfLabel.dwMask = CFM_COLOR | CFM_BACKCOLOR | CFM_BOLD;
    cfLabel.dwEffects = CFE_BOLD;
    cfLabel.crTextColor = NEON_BLUE;
    cfLabel.crBackColor = BUBBLE_ARGOS;
    SendMessageW(hConvo, EM_SETCHARFORMAT, SCF_SELECTION, (LPARAM)&cfLabel);
    SendMessageW(hConvo, EM_REPLACESEL, FALSE, (LPARAM)L"Argos\r\n");

    // Thinking text: dim italic on dark gray
    CHARFORMAT2W cfThink = {};
    cfThink.cbSize = sizeof(cfThink);
    cfThink.dwMask = CFM_COLOR | CFM_BACKCOLOR | CFM_ITALIC;
    cfThink.dwEffects = CFE_ITALIC;
    cfThink.crTextColor = TEXT_DIM;
    cfThink.crBackColor = BUBBLE_ARGOS;
    SendMessageW(hConvo, EM_SETCHARFORMAT, SCF_SELECTION, (LPARAM)&cfThink);

    const wchar_t* dots[] = { L".  .  .", L"*  .  .", L".  *  .", L".  .  *" };
    std::wstring thinkText = L"Thinking " + std::wstring(dots[g_loadingDots % 4]) + L"\r\n";
    SendMessageW(hConvo, EM_REPLACESEL, FALSE, (LPARAM)thinkText.c_str());

    // Auto-scroll only if user was at bottom
    if (wasAtBottom) {
        LRESULT endLen = SendMessageW(hConvo, WM_GETTEXTLENGTH, 0, 0);
        SendMessageW(hConvo, EM_SETSEL, endLen, endLen);
        SendMessageW(hConvo, EM_SCROLLCARET, 0, 0);
    }
}

// ── Config file loading/saving ──
// Reads from: argos_config.txt next to exe, or %APPDATA%/Argos/argos_config.txt
// Environment variables override: ARGOS_API_KEY, ARGOS_SERVER_URL, ARGOS_MODEL
static std::wstring GetConfigPath() {
    // Try next to exe first
    wchar_t exePath[MAX_PATH] = {0};
    GetModuleFileNameW(nullptr, exePath, MAX_PATH);
    std::wstring exeDir(exePath);
    size_t lastSlash = exeDir.find_last_of(L'\\');
    if (lastSlash != std::wstring::npos) exeDir = exeDir.substr(0, lastSlash + 1);
    std::wstring configPath = exeDir + L"argos_config.txt";

    // If not found next to exe, try %APPDATA%/Argos/
    if (GetFileAttributesW(configPath.c_str()) == INVALID_FILE_ATTRIBUTES) {
        wchar_t appData[MAX_PATH] = {0};
        if (GetEnvironmentVariableW(L"APPDATA", appData, MAX_PATH)) {
            std::wstring appDataPath = std::wstring(appData) + L"\\Argos\\argos_config.txt";
            if (GetFileAttributesW(appDataPath.c_str()) != INVALID_FILE_ATTRIBUTES) {
                return appDataPath;
            }
        }
    }
    return configPath; // Default: next to exe (may not exist yet)
}

struct ArgosConfig {
    std::wstring serverUrl;
    std::wstring apiKey;
    std::wstring model;
    std::wstring fallbackModel;
    std::wstring visionModel;
};

static ArgosConfig LoadConfig() {
    ArgosConfig cfg;
    // Defaults — AMD Radeon Developer API (OpenAI-compatible)
    cfg.serverUrl = L"https://developer.amd.com.cn/radeon/api/v1";
    cfg.apiKey = L"";  // No hardcoded key — user must provide
    cfg.model = L"DeepSeek-V4-Flash";
    cfg.fallbackModel = L"MiniCPM5-1B";
    cfg.visionModel = L"Qwen3.6-35B-A3B";

    // Load from config file
    std::wstring configPath = GetConfigPath();
    FILE* f = nullptr;
    _wfopen_s(&f, configPath.c_str(), L"r");
    if (f) {
        wchar_t line[1024];
        while (fgetws(line, 1024, f)) {
            std::wstring l(line);
            // Trim newline
            if (!l.empty() && l.back() == L'\n') l.pop_back();
            if (!l.empty() && l.back() == L'\r') l.pop_back();
            // Parse key=value
            size_t eq = l.find(L'=');
            if (eq == std::wstring::npos) continue;
            std::wstring key = l.substr(0, eq);
            std::wstring val = l.substr(eq + 1);
            // Trim whitespace
            while (!key.empty() && (key.back() == L' ' || key.back() == L'\t')) key.pop_back();
            while (!val.empty() && (val.front() == L' ' || val.front() == L'\t')) val.erase(0, 1);
            while (!val.empty() && (val.back() == L' ' || val.back() == L'\t' || val.back() == L'\r' || val.back() == L'\n')) val.pop_back();

            if (key == L"server_url" && !val.empty()) cfg.serverUrl = val;
            else if (key == L"api_key" && !val.empty()) cfg.apiKey = val;
            else if (key == L"model" && !val.empty()) cfg.model = val;
            else if (key == L"fallback_model" && !val.empty()) cfg.fallbackModel = val;
            else if (key == L"vision_model" && !val.empty()) cfg.visionModel = val;
        }
        fclose(f);
    }

    // Environment variables override config file
    wchar_t envVal[512];
    if (GetEnvironmentVariableW(L"ARGOS_SERVER_URL", envVal, 512)) cfg.serverUrl = envVal;
    if (GetEnvironmentVariableW(L"ARGOS_API_KEY", envVal, 512)) cfg.apiKey = envVal;
    if (GetEnvironmentVariableW(L"ARGOS_MODEL", envVal, 512)) cfg.model = envVal;

    return cfg;
}

static void SaveConfig(const std::wstring& serverUrl, const std::wstring& apiKey,
                       const std::wstring& model) {
    std::wstring configPath = GetConfigPath();
    FILE* f = nullptr;
    _wfopen_s(&f, configPath.c_str(), L"w");
    if (!f) return;
    fwprintf(f, L"server_url=%s\n", serverUrl.c_str());
    fwprintf(f, L"api_key=%s\n", apiKey.c_str());
    fwprintf(f, L"model=%s\n", model.c_str());
    fclose(f);
}

// Global handles
static RobotRenderer* g_renderer = nullptr;
static AgentClient* g_agent = nullptr;
static TrayIcon* g_tray = nullptr;

#define IDT_ANIMATE 1001
#define ANIMATE_INTERVAL_MS 16

// Manga bubble control IDs
#define IDC_BUBBLE_CANCEL 3004
#define IDC_BUBBLE_TITLE  3005
#define IDC_BUBBLE_SETTINGS 3006
#define IDC_BUBBLE_URL_LABEL 3007
#define IDC_BUBBLE_URL       3008
#define IDC_BUBBLE_KEY_LABEL 3009
#define IDC_BUBBLE_KEY       3010
#define IDC_BUBBLE_MODEL_LABEL 3011
#define IDC_BUBBLE_MODEL      3012
#define IDC_BUBBLE_HISTORY    3013
#define IDC_BUBBLE_HISTORY_LIST 3014
#define IDC_BUBBLE_EXPAND     3016
#define IDC_BUBBLE_SHRINK     3017

// RAG manual sync controls
#define IDC_RAG_LABEL      3018
#define IDC_RAG_DESKTOP    3019
#define IDC_RAG_DOCUMENTS  3020
#define IDC_RAG_DOWNLOADS  3021
#define IDC_RAG_MUSIC      3022
#define IDC_RAG_VIDEOS     3023
#define IDC_RAG_SYNC_BTN   3024
#define IDC_RAG_STATUS     3025

// Custom message posted from the background sync thread to update RAG UI
#define WM_RAG_SYNC_PROGRESS (WM_USER + 104)

static std::mutex g_ragUiMutex;
static std::wstring g_ragStatusText = L"RAG: not synced (select folders below)";
static bool g_ragSyncDone = true;

// ── Modern manga speech bubble — neon blue + white ─────────────────────
// Design: clean webtoon-style rounded rectangle, white background, neon
// blue (#00CFFF) outline with a soft glow halo, neon blue accent header
// bar, black text for readability.  Tail points down at the robot.
// Color-key transparency (magenta = transparent) makes only the bubble
// visible — no window frame, just the bubble shape.

static HFONT g_bubbleFont = nullptr;
static HFONT g_bubbleTitleFont = nullptr;
static HBRUSH g_bubbleBgBrush = nullptr;
static HBRUSH g_bubbleEditBgBrush = nullptr;
static bool g_settingsVisible = false;
static bool g_expanded = false;
static HFONT g_bubbleSmallFont = nullptr;

// Owner-draw button data for neon-styled buttons
struct NeonButton {
    const wchar_t* label;
    COLORREF textColor;
    COLORREF borderColor;
    COLORREF bgColor;
};

static NeonButton g_btnData[] = {
    { L"Send",     RGB(255,255,255), NEON_BLUE,      DARK_SEND_BG   },
    { L"Voice",    TEXT_LIGHT,       NEON_BLUE_DIM,  DARK_BTN_BG    },
    { L"Set",      TEXT_LIGHT,       NEON_BLUE_DIM,  DARK_BTN_BG    },
    { L"History",  TEXT_LIGHT,       NEON_BLUE_DIM,  DARK_BTN_BG    },
    { L"Expand",   TEXT_LIGHT,       NEON_BLUE_DIM,  DARK_BTN_BG    },
    { L"Exit",     RGB(255,180,180), RGB(120,60,60), DARK_EXIT_BG   },
};

static LRESULT CALLBACK BubbleWndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam);

// Forward declarations for proactive system
static void StartProactiveTimer(HWND hwnd);
static void StopProactiveTimer(HWND hwnd);
static void CloseProactiveBubble();

// Subclass proc for input edit control — Enter key sends message
static WNDPROC g_origEditProc = nullptr;
static LRESULT CALLBACK InputEditProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    if (msg == WM_KEYDOWN && wParam == VK_RETURN) {
        // Enter sends the message (don't insert newline)
        HWND hParent = GetParent(hwnd);
        if (hParent) {
            SendMessageW(hParent, WM_COMMAND, MAKEWPARAM(IDC_BUBBLE_SEND, BN_CLICKED), 0);
        }
        return 0;
    }
    if (msg == WM_KEYDOWN && wParam == VK_RETURN && (GetKeyState(VK_SHIFT) & 0x8000)) {
        // Shift+Enter = newline (pass through)
    }
    return CallWindowProcW(g_origEditProc, hwnd, msg, wParam, lParam);
}

static LRESULT CALLBACK BubbleWndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
        case WM_CREATE: {
            g_bubbleFont = CreateFontW(16, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
                DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_SWISS, L"Segoe UI Semibold");
            g_bubbleTitleFont = CreateFontW(19, 0, 0, 0, FW_EXTRABOLD, FALSE, FALSE, FALSE,
                DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_SWISS, L"Segoe UI Black");
            g_bubbleSmallFont = CreateFontW(13, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE,
                DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_SWISS, L"Segoe UI Semibold");
            g_bubbleBgBrush = CreateSolidBrush(DARK_BG);
            g_bubbleEditBgBrush = CreateSolidBrush(DARK_INPUT_BG);

            // Title label — neon blue text
            HWND hTitle = CreateWindowExW(0, L"STATIC", L"Ask Argos",
                WS_CHILD | WS_VISIBLE | SS_CENTER,
                28, 12, 284, 22, hwnd, (HMENU)IDC_BUBBLE_TITLE, nullptr, nullptr);
            SendMessageW(hTitle, WM_SETFONT, (WPARAM)g_bubbleTitleFont, TRUE);

            // Conversation display — Rich Edit for modern Messenger-style bubbles
            // Load rich edit library if not already loaded
            if (!g_richEditDll) g_richEditDll = LoadLibraryW(L"msftedit.dll");
            HWND hConvo = CreateWindowExW(WS_EX_TRANSPARENT, L"RICHEDIT50W", L"",
                WS_CHILD | WS_VISIBLE | ES_MULTILINE | ES_READONLY | WS_VSCROLL | ES_AUTOVSCROLL,
                28, 38, 284, 120, hwnd, (HMENU)IDC_BUBBLE_CONVO, nullptr, nullptr);
            SendMessageW(hConvo, WM_SETFONT, (WPARAM)g_bubbleFont, TRUE);
            // Dark background for conversation area
            SendMessageW(hConvo, EM_SETBKGNDCOLOR, 0, (LPARAM)DARK_CONV_BG);
            // Disable auto-url detection to prevent blue links cluttering
            SendMessageW(hConvo, EM_AUTOURLDETECT, FALSE, 0);
            // Set default format: light text on dark
            CHARFORMAT2W cf = {};
            cf.cbSize = sizeof(cf);
            cf.dwMask = CFM_COLOR | CFM_BACKCOLOR;
            cf.crTextColor = TEXT_LIGHT;
            cf.crBackColor = DARK_CONV_BG;
            SendMessageW(hConvo, EM_SETCHARFORMAT, SCF_DEFAULT, (LPARAM)&cf);
            // Set event mask to include EN_CHANGE so we can track scrolling
            SendMessageW(hConvo, EM_SETEVENTMASK, 0, ENM_SCROLL | ENM_CHANGE);

            // Input box — small, flat modern style, for typing new messages
            HWND hEdit = CreateWindowExW(0, L"EDIT", L"",
                WS_CHILD | WS_VISIBLE | ES_MULTILINE | ES_AUTOVSCROLL | ES_WANTRETURN,
                28, 166, 284, 32, hwnd, (HMENU)IDC_BUBBLE_EDIT, nullptr, nullptr);
            SendMessageW(hEdit, WM_SETFONT, (WPARAM)g_bubbleFont, TRUE);
            // Subclass to intercept Enter key for sending
            g_origEditProc = (WNDPROC)SetWindowLongPtrW(hEdit, GWLP_WNDPROC, (LONG_PTR)InputEditProc);

            // Owner-draw buttons — Send, Voice, Set, History, Expand, Exit
            HWND hSend = CreateWindowExW(0, L"BUTTON", L"Send",
                WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
                28, 206, 44, 24, hwnd, (HMENU)IDC_BUBBLE_SEND, nullptr, nullptr);
            SendMessageW(hSend, WM_SETFONT, (WPARAM)g_bubbleFont, TRUE);

            HWND hVoice = CreateWindowExW(0, L"BUTTON", L"Voice",
                WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
                76, 206, 44, 24, hwnd, (HMENU)IDC_BUBBLE_VOICE, nullptr, nullptr);
            SendMessageW(hVoice, WM_SETFONT, (WPARAM)g_bubbleFont, TRUE);

            HWND hSettings = CreateWindowExW(0, L"BUTTON", L"Set",
                WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
                124, 206, 36, 24, hwnd, (HMENU)IDC_BUBBLE_SETTINGS, nullptr, nullptr);
            SendMessageW(hSettings, WM_SETFONT, (WPARAM)g_bubbleFont, TRUE);

            HWND hHistory = CreateWindowExW(0, L"BUTTON", L"History",
                WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
                164, 206, 50, 24, hwnd, (HMENU)IDC_BUBBLE_HISTORY, nullptr, nullptr);
            SendMessageW(hHistory, WM_SETFONT, (WPARAM)g_bubbleFont, TRUE);

            HWND hExpand = CreateWindowExW(0, L"BUTTON", L"Expand",
                WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
                218, 206, 50, 24, hwnd, (HMENU)IDC_BUBBLE_EXPAND, nullptr, nullptr);
            SendMessageW(hExpand, WM_SETFONT, (WPARAM)g_bubbleFont, TRUE);

            HWND hCancel = CreateWindowExW(0, L"BUTTON", L"Exit",
                WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
                272, 206, 40, 24, hwnd, (HMENU)IDC_BUBBLE_CANCEL, nullptr, nullptr);
            SendMessageW(hCancel, WM_SETFONT, (WPARAM)g_bubbleFont, TRUE);

            // Settings panel (hidden by default) — URL, API Key, Model
            HWND hUrlLabel = CreateWindowExW(0, L"STATIC", L"Base URL",
                WS_CHILD | SS_LEFT, 28, 244, 80, 16, hwnd, (HMENU)IDC_BUBBLE_URL_LABEL, nullptr, nullptr);
            SendMessageW(hUrlLabel, WM_SETFONT, (WPARAM)g_bubbleSmallFont, TRUE);

            HWND hKeyLabel = CreateWindowExW(0, L"STATIC", L"API Key",
                WS_CHILD | SS_LEFT, 28, 274, 80, 16, hwnd, (HMENU)IDC_BUBBLE_KEY_LABEL, nullptr, nullptr);
            SendMessageW(hKeyLabel, WM_SETFONT, (WPARAM)g_bubbleSmallFont, TRUE);

            HWND hModelLabel = CreateWindowExW(0, L"STATIC", L"Model",
                WS_CHILD | SS_LEFT, 28, 304, 80, 16, hwnd, (HMENU)IDC_BUBBLE_MODEL_LABEL, nullptr, nullptr);
            SendMessageW(hModelLabel, WM_SETFONT, (WPARAM)g_bubbleSmallFont, TRUE);

            HWND hUrl = CreateWindowExW(0, L"EDIT", L"",
                WS_CHILD | ES_AUTOHSCROLL,
                100, 242, 212, 20, hwnd, (HMENU)IDC_BUBBLE_URL, nullptr, nullptr);
            SendMessageW(hUrl, WM_SETFONT, (WPARAM)g_bubbleSmallFont, TRUE);

            HWND hKey = CreateWindowExW(0, L"EDIT", L"",
                WS_CHILD | ES_AUTOHSCROLL,
                100, 272, 212, 20, hwnd, (HMENU)IDC_BUBBLE_KEY, nullptr, nullptr);
            SendMessageW(hKey, WM_SETFONT, (WPARAM)g_bubbleSmallFont, TRUE);

            HWND hModel = CreateWindowExW(0, L"EDIT", L"",
                WS_CHILD | ES_AUTOHSCROLL,
                100, 302, 212, 20, hwnd, (HMENU)IDC_BUBBLE_MODEL, nullptr, nullptr);
            SendMessageW(hModel, WM_SETFONT, (WPARAM)g_bubbleSmallFont, TRUE);

            // ── RAG manual sync section ──
            // RAG only indexes folders the user explicitly selects and syncs.
            // No automatic indexing — prevents slow/error-prone scanning.
            HWND hRagLabel = CreateWindowExW(0, L"STATIC", L"RAG: Sync Folders (manual)",
                WS_CHILD | SS_LEFT, 28, 330, 280, 16, hwnd, (HMENU)IDC_RAG_LABEL, nullptr, nullptr);
            SendMessageW(hRagLabel, WM_SETFONT, (WPARAM)g_bubbleSmallFont, TRUE);

            HWND hCbDesktop = CreateWindowExW(0, L"BUTTON", L"Desktop",
                WS_CHILD | BS_AUTOCHECKBOX, 28, 348, 130, 18, hwnd, (HMENU)IDC_RAG_DESKTOP, nullptr, nullptr);
            SendMessageW(hCbDesktop, WM_SETFONT, (WPARAM)g_bubbleSmallFont, TRUE);

            HWND hCbDocuments = CreateWindowExW(0, L"BUTTON", L"Documents",
                WS_CHILD | BS_AUTOCHECKBOX, 180, 348, 130, 18, hwnd, (HMENU)IDC_RAG_DOCUMENTS, nullptr, nullptr);
            SendMessageW(hCbDocuments, WM_SETFONT, (WPARAM)g_bubbleSmallFont, TRUE);

            HWND hCbDownloads = CreateWindowExW(0, L"BUTTON", L"Downloads",
                WS_CHILD | BS_AUTOCHECKBOX, 28, 368, 130, 18, hwnd, (HMENU)IDC_RAG_DOWNLOADS, nullptr, nullptr);
            SendMessageW(hCbDownloads, WM_SETFONT, (WPARAM)g_bubbleSmallFont, TRUE);

            HWND hCbMusic = CreateWindowExW(0, L"BUTTON", L"Music",
                WS_CHILD | BS_AUTOCHECKBOX, 180, 368, 130, 18, hwnd, (HMENU)IDC_RAG_MUSIC, nullptr, nullptr);
            SendMessageW(hCbMusic, WM_SETFONT, (WPARAM)g_bubbleSmallFont, TRUE);

            HWND hCbVideos = CreateWindowExW(0, L"BUTTON", L"Videos",
                WS_CHILD | BS_AUTOCHECKBOX, 28, 388, 130, 18, hwnd, (HMENU)IDC_RAG_VIDEOS, nullptr, nullptr);
            SendMessageW(hCbVideos, WM_SETFONT, (WPARAM)g_bubbleSmallFont, TRUE);

            HWND hRagSyncBtn = CreateWindowExW(0, L"BUTTON", L"Sync Now",
                WS_CHILD | BS_PUSHBUTTON, 180, 386, 130, 22, hwnd, (HMENU)IDC_RAG_SYNC_BTN, nullptr, nullptr);
            SendMessageW(hRagSyncBtn, WM_SETFONT, (WPARAM)g_bubbleSmallFont, TRUE);

            HWND hRagStatus = CreateWindowExW(0, L"STATIC", g_ragStatusText.c_str(),
                WS_CHILD | SS_LEFT, 28, 414, 284, 34, hwnd, (HMENU)IDC_RAG_STATUS, nullptr, nullptr);
            SendMessageW(hRagStatus, WM_SETFONT, (WPARAM)g_bubbleSmallFont, TRUE);

            // Pre-fill settings from loaded config
            if (g_agent) {
                ArgosConfig cfg = LoadConfig();
                SetWindowTextW(hUrl, cfg.serverUrl.c_str());
                SetWindowTextW(hKey, cfg.apiKey.c_str());
                SetWindowTextW(hModel, cfg.model.c_str());
            }

            // Show existing conversation if any
            RefreshConversation(hwnd);

            SetFocus(hEdit);
            return 0;
        }
        case WM_ERASEBKGND:
            return 1;
        case WM_NCHITTEST: {
            // Allow dragging the window by clicking on the title/header area
            POINT pt = { GET_X_LPARAM(lParam), GET_Y_LPARAM(lParam) };
            RECT rc;
            GetWindowRect(hwnd, &rc);
            int relX = pt.x - rc.left;
            int relY = pt.y - rc.top;
            // Title bar drag area: top 40px of the bubble (inside the rounded border)
            if (relY >= 10 && relY <= 40 && relX >= 10 && relX <= rc.right - rc.left - 10) {
                return HTCAPTION;
            }
            return HTCLIENT;
        }
        case WM_PAINT: {
            PAINTSTRUCT ps;
            HDC hdc = BeginPaint(hwnd, &ps);
            RECT rc;
            GetClientRect(hwnd, &rc);
            int w = rc.right, h = rc.bottom;

            // Double-buffer to avoid flicker
            HDC memDC = CreateCompatibleDC(hdc);
            HBITMAP memBmp = CreateCompatibleBitmap(hdc, w, h);
            HBITMAP oldBmp = (HBITMAP)SelectObject(memDC, memBmp);

            // Fill with magenta (transparent via color key)
            HBRUSH magBrush = CreateSolidBrush(RGB(255, 0, 255));
            FillRect(memDC, &rc, magBrush);
            DeleteObject(magBrush);

            // Bubble geometry — body extends to include buttons
            int bL = 10, bT = 10, bR = w - 10, bB = h - 42;
            int radius = 22;
            int tailX = w / 2;
            int tailW = 16, tailH = 28;

            HPEN nullPen = (HPEN)GetStockObject(NULL_PEN);
            HBRUSH darkBrush = CreateSolidBrush(DARK_BG);
            HBRUSH glowBrush = CreateSolidBrush(NEON_BLUE_GLOW);
            HBRUSH dimGlowBrush = CreateSolidBrush(NEON_BLUE_DIM);

            // ── 1. Glow halo: concentric rounded rects ──
            SelectObject(memDC, nullPen);
            SelectObject(memDC, glowBrush);
            RoundRect(memDC, bL - 6, bT - 6, bR + 6, bB + 6, (radius + 6) * 2, (radius + 6) * 2);
            SelectObject(memDC, dimGlowBrush);
            RoundRect(memDC, bL - 3, bT - 3, bR + 3, bB + 3, (radius + 3) * 2, (radius + 3) * 2);

            // ── 2. Tail fill (dark, behind bubble) ──
            SelectObject(memDC, nullPen);
            SelectObject(memDC, darkBrush);
            if (g_bubbleBelowRobot) {
                // Tail points UP toward robot above
                POINT tailUp[] = {
                    {tailX - tailW, bT + 2},
                    {tailX + tailW, bT + 2},
                    {tailX, bT - tailH}
                };
                Polygon(memDC, tailUp, 3);
            } else {
                // Tail points DOWN toward robot below
                POINT tail[] = {
                    {tailX - tailW, bB - 2},
                    {tailX + tailW, bB - 2},
                    {tailX, bB + tailH}
                };
                Polygon(memDC, tail, 3);
            }

            // ── 3. Dark bubble body ──
            RoundRect(memDC, bL, bT, bR, bB, radius * 2, radius * 2);

            // ── 4. Neon accent header bar (top inside bubble) ──
            HBRUSH barBrush = CreateSolidBrush(NEON_BLUE_BAR);
            SelectObject(memDC, nullPen);
            SelectObject(memDC, barBrush);
            RoundRect(memDC, bL + 1, bT + 1, bR - 1, bT + 8, radius * 2, radius * 2);
            DeleteObject(barBrush);

            // ── 5. Drag handle indicator (three dots in header area) ──
            HBRUSH handleBrush = CreateSolidBrush(DRAG_HANDLE);
            SelectObject(memDC, nullPen);
            SelectObject(memDC, handleBrush);
            int handleY = bT + 4;
            int handleSpacing = 6;
            int handleStartX = w / 2 - handleSpacing;
            for (int i = 0; i < 3; i++) {
                Ellipse(memDC, handleStartX + i * handleSpacing - 1, handleY - 1,
                        handleStartX + i * handleSpacing + 2, handleY + 2);
            }
            DeleteObject(handleBrush);

            // ── 6. Neon blue outline (2px) ──
            HPEN neonPen = CreatePen(PS_SOLID, 2, NEON_BLUE);
            SelectObject(memDC, neonPen);
            SelectObject(memDC, GetStockObject(NULL_BRUSH));
            RoundRect(memDC, bL, bT, bR, bB, radius * 2, radius * 2);

            // ── 7. Erase outline where tail connects ──
            SelectObject(memDC, nullPen);
            SelectObject(memDC, darkBrush);
            if (g_bubbleBelowRobot) {
                RECT eraseRect = {tailX - tailW, bT - 2, tailX + tailW, bT + 2};
                FillRect(memDC, &eraseRect, darkBrush);
            } else {
                RECT eraseRect = {tailX - tailW, bB - 2, tailX + tailW, bB + 2};
                FillRect(memDC, &eraseRect, darkBrush);
            }

            // ── 8. Tail outline ──
            SelectObject(memDC, neonPen);
            SelectObject(memDC, GetStockObject(NULL_BRUSH));
            if (g_bubbleBelowRobot) {
                MoveToEx(memDC, tailX - tailW, bT, nullptr);
                LineTo(memDC, tailX, bT - tailH);
                LineTo(memDC, tailX + tailW, bT);
            } else {
                MoveToEx(memDC, tailX - tailW, bB, nullptr);
                LineTo(memDC, tailX, bB + tailH);
                LineTo(memDC, tailX + tailW, bB);
            }

            // ── 9. Tail glow ──
            HPEN glowPen = CreatePen(PS_SOLID, 2, NEON_BLUE_DIM);
            SelectObject(memDC, glowPen);
            if (g_bubbleBelowRobot) {
                MoveToEx(memDC, tailX - tailW - 2, bT, nullptr);
                LineTo(memDC, tailX, bT - tailH - 2);
                LineTo(memDC, tailX + tailW + 2, bT);
            } else {
                MoveToEx(memDC, tailX - tailW - 2, bB, nullptr);
                LineTo(memDC, tailX, bB + tailH + 2);
                LineTo(memDC, tailX + tailW + 2, bB);
            }

            SelectObject(memDC, nullPen);
            DeleteObject(neonPen);
            DeleteObject(glowPen);
            DeleteObject(darkBrush);
            DeleteObject(glowBrush);
            DeleteObject(dimGlowBrush);

            // ── 10. Modern thin borders around edit controls (subtle dark) ──
            HPEN thinPen = CreatePen(PS_SOLID, 1, RGB(55, 55, 65));
            SelectObject(memDC, thinPen);
            SelectObject(memDC, GetStockObject(NULL_BRUSH));
            // Conversation area border (rounded)
            RoundRect(memDC, 26, 36, w - 26, h - 78, 8, 8);
            // Input box border (rounded)
            RoundRect(memDC, 26, h - 74, w - 26, h - 40, 8, 8);
            DeleteObject(thinPen);

            BitBlt(hdc, 0, 0, w, h, memDC, 0, 0, SRCCOPY);
            SelectObject(memDC, oldBmp);
            DeleteObject(memBmp);
            DeleteDC(memDC);

            EndPaint(hwnd, &ps);
            return 0;
        }
        case WM_DRAWITEM: {
            DRAWITEMSTRUCT* dis = (DRAWITEMSTRUCT*)lParam;
            if (!dis) return 0;
            int btnIdx = -1;
            switch (dis->CtlID) {
                case IDC_BUBBLE_SEND:     btnIdx = 0; break;
                case IDC_BUBBLE_VOICE:    btnIdx = 1; break;
                case IDC_BUBBLE_SETTINGS: btnIdx = 2; break;
                case IDC_BUBBLE_HISTORY:  btnIdx = 3; break;
                case IDC_BUBBLE_EXPAND:   btnIdx = 4; break;
                case IDC_BUBBLE_CANCEL:   btnIdx = 5; break;
            }
            if (btnIdx < 0) return 0;
            NeonButton* btn = &g_btnData[btnIdx];

            HDC hdc = dis->hDC;
            RECT rc = dis->rcItem;

            // Modern rounded background (pill-shaped)
            HBRUSH bgBrush = CreateSolidBrush(btn->bgColor);
            HPEN nullPen2 = (HPEN)GetStockObject(NULL_PEN);
            SelectObject(hdc, nullPen2);
            SelectObject(hdc, bgBrush);
            RoundRect(hdc, rc.left, rc.top, rc.right - 1, rc.bottom - 1, 12, 12);
            DeleteObject(bgBrush);

            // Border (neon blue, thicker on press)
            int borderWidth = (dis->itemState & ODS_SELECTED) ? 2 : 1;
            HPEN borderPen = CreatePen(PS_SOLID, borderWidth, btn->borderColor);
            SelectObject(hdc, borderPen);
            SelectObject(hdc, GetStockObject(NULL_BRUSH));
            RoundRect(hdc, rc.left, rc.top, rc.right - 1, rc.bottom - 1, 12, 12);
            DeleteObject(borderPen);

            // Text
            SetBkMode(hdc, TRANSPARENT);
            SetTextColor(hdc, btn->textColor);
            HFONT oldFont = (HFONT)SelectObject(hdc, g_bubbleFont);
            int len = (int)wcslen(btn->label);
            RECT textRect = rc;
            DrawTextW(hdc, btn->label, len, &textRect, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
            SelectObject(hdc, oldFont);

            return TRUE;
        }
        case WM_CTLCOLORSTATIC: {
            HDC hdcCtl = (HDC)wParam;
            // For STATIC labels (title), use transparent with neon text on dark
            SetBkMode(hdcCtl, TRANSPARENT);
            SetTextColor(hdcCtl, TEXT_LIGHT);
            return (LRESULT)g_bubbleBgBrush;
        }
        case WM_CTLCOLOREDIT: {
            HDC hdcCtl = (HDC)wParam;
            // Dark background for input edit, light text
            SetBkColor(hdcCtl, DARK_INPUT_BG);
            SetTextColor(hdcCtl, TEXT_LIGHT);
            static HBRUSH darkEditBrush = CreateSolidBrush(DARK_INPUT_BG);
            return (LRESULT)darkEditBrush;
        }
        case WM_COMMAND: {
            switch (LOWORD(wParam)) {
                case IDC_BUBBLE_SEND: {
                    if (g_chatInProgress.load()) {
                        // Cancel the in-progress chat and start the new one
                        if (g_agent) g_agent->m_abort.store(true);
                        KillTimer(hwnd, IDT_LOADING);
                        g_chatInProgress.store(false);
                        // Remove the incomplete chat entry (empty assistant response)
                        if (!g_chatHistory.empty() && g_chatHistory.back().assistantMsg.empty()) {
                            g_chatHistory.pop_back();
                        }
                        // Small delay to let the aborted thread clean up
                        Sleep(100);
                    }

                    // Apply settings from the settings fields before sending
                    if (g_agent) {
                        wchar_t url[512] = {0}, key[512] = {0}, model[128] = {0};
                        GetWindowTextW(GetDlgItem(hwnd, IDC_BUBBLE_URL), url, 512);
                        GetWindowTextW(GetDlgItem(hwnd, IDC_BUBBLE_KEY), key, 512);
                        GetWindowTextW(GetDlgItem(hwnd, IDC_BUBBLE_MODEL), model, 128);
                        if (wcslen(url) > 0) g_agent->SetServerUrl(url);
                        if (wcslen(key) > 0) g_agent->SetApiKey(key);
                        if (wcslen(model) > 0) g_agent->SetModel(model);
                        // Persist settings to config file
                        SaveConfig(url, key, model);
                    }
                    wchar_t text[1024] = {0};
                    GetWindowTextW(GetDlgItem(hwnd, IDC_BUBBLE_EDIT), text, 1024);
                    if (g_agent && wcslen(text) > 0) {
                        g_lastUserMsg = text;
                        g_chatInProgress.store(true);

                        // Add user message to history immediately (empty response for now)
                        g_chatHistory.push_back({g_lastUserMsg, L"", false});

                        // Clear input box
                        SetWindowTextW(GetDlgItem(hwnd, IDC_BUBBLE_EDIT), L"");
                        EnableWindow(GetDlgItem(hwnd, IDC_BUBBLE_SEND), FALSE);
                        SetTimer(hwnd, IDT_LOADING, 300, nullptr);
                        g_thinkingStartPos = -1; // reset for new thinking indicator
                        g_loadingTickCount = 0; // reset watchdog

                        // Set robot to thinking state
                        if (g_renderer) g_renderer->SetThinking(true);

                        // Update conversation display with user message + loading
                        RefreshConversation(hwnd);

                        // Force scroll to bottom after sending
                        HWND hConvo = GetDlgItem(hwnd, IDC_BUBBLE_CONVO);
                        if (hConvo) {
                            LRESULT textLen = SendMessageW(hConvo, WM_GETTEXTLENGTH, 0, 0);
                            SendMessageW(hConvo, EM_SETSEL, textLen, textLen);
                            SendMessageW(hConvo, EM_SCROLLCARET, 0, 0);
                        }

                        // Launch async chat thread with streaming
                        std::thread([hwnd]() {
                            {
                                std::lock_guard<std::mutex> lock(g_streamingMutex);
                                g_streamingPartial.clear();
                            }
                            std::wstring response;
                            try {
                                response = g_agent->ChatStreaming(g_lastUserMsg,
                                    [hwnd](const std::wstring& delta) -> bool {
                                        {
                                            std::lock_guard<std::mutex> lock(g_streamingMutex);
                                            g_streamingPartial += delta;
                                        }
                                        PostMessageW(hwnd, WM_CHAT_STREAM, 0, 0);
                                        return !g_agent->m_abort.load(); // abort if requested
                                    });
                            } catch (const std::exception& e) {
                                // Log error to file
                                FILE* logFile = nullptr;
                                fopen_s(&logFile, "argos_error.log", "a");
                                if (logFile) {
                                    time_t now = time(nullptr);
                                    struct tm tm_buf;
                                    localtime_s(&tm_buf, &now);
                                    char timeBuf[64];
                                    strftime(timeBuf, sizeof(timeBuf), "%Y-%m-%d %H:%M:%S", &tm_buf);
                                    fprintf(logFile, "[%s] ChatStreaming exception: %s\n", timeBuf, e.what());
                                    fclose(logFile);
                                }
                                response = L"[Error: Chat failed with exception: " +
                                    std::wstring(e.what(), e.what() + strlen(e.what())) + L"]";
                            } catch (...) {
                                response = L"[Error: Chat failed with unknown exception]";
                            }
                            g_pendingResponse = response;
                            if (g_agent->m_abort.load()) {
                                PostMessageW(hwnd, WM_CHAT_ERROR, 0, 0);
                            } else {
                                PostMessageW(hwnd, WM_CHAT_RESPONSE, 0, 0);
                            }
                        }).detach();
                    }
                    return 0;
                }
                case IDC_BUBBLE_HISTORY: {
                    // Scroll conversation to top to review history
                    HWND hConvo = GetDlgItem(hwnd, IDC_BUBBLE_CONVO);
                    if (hConvo) {
                        SendMessageW(hConvo, EM_LINESCROLL, 0, -99999);
                    }
                    return 0;
                }
                case IDC_RAG_SYNC_BTN: {
                    // Gather checked folders
                    std::vector<std::pair<std::string,std::string>> toSync;
                    auto folders = argos_tools::rag_get_available_folders();
                    int cbIds[] = { IDC_RAG_DESKTOP, IDC_RAG_DOCUMENTS, IDC_RAG_DOWNLOADS, IDC_RAG_MUSIC, IDC_RAG_VIDEOS };
                    for (size_t i = 0; i < folders.size() && i < 5; i++) {
                        HWND hCb = GetDlgItem(hwnd, cbIds[i]);
                        if (hCb && SendMessageW(hCb, BM_GETCHECK, 0, 0) == BST_CHECKED) {
                            toSync.push_back({folders[i].label, folders[i].path});
                        }
                    }
                    if (toSync.empty()) {
                        g_ragStatusText = L"Select at least one folder to sync.";
                        HWND hStatus = GetDlgItem(hwnd, IDC_RAG_STATUS);
                        if (hStatus) SetWindowTextW(hStatus, g_ragStatusText.c_str());
                        return 0;
                    }
                    // Disable sync button while working
                    EnableWindow(GetDlgItem(hwnd, IDC_RAG_SYNC_BTN), FALSE);
                    g_ragSyncDone = false;
                    g_ragStatusText = L"Syncing...";
                    HWND hStatus = GetDlgItem(hwnd, IDC_RAG_STATUS);
                    if (hStatus) SetWindowTextW(hStatus, g_ragStatusText.c_str());

                    // Run sync in background thread
                    std::thread([hwnd, toSync]() {
                        // Clear previous sync state
                        argos_tools::rag_clear_sync();
                        int totalFolders = (int)toSync.size();
                        int doneFolders = 0;
                        for (auto& f : toSync) {
                            // Post progress: starting folder
                            {
                                std::lock_guard<std::mutex> lk(g_ragUiMutex);
                                g_ragStatusText = L"Syncing " + std::wstring(f.first.begin(), f.first.end()) + L"...";
                            }
                            PostMessageW(hwnd, WM_RAG_SYNC_PROGRESS, 0, 0);

                            argos_tools::rag_sync_folder(f.first, f.second, [&](int pct) {
                                {
                                    std::lock_guard<std::mutex> lk(g_ragUiMutex);
                                    g_ragStatusText = L"Syncing " + std::wstring(f.first.begin(), f.first.end())
                                        + L": " + std::to_wstring(pct) + L"%";
                                }
                                PostMessageW(hwnd, WM_RAG_SYNC_PROGRESS, 0, 0);
                            });
                            doneFolders++;
                        }
                        {
                            std::lock_guard<std::mutex> lk(g_ragUiMutex);
                            g_ragStatusText = L"RAG sync complete (" + std::to_wstring(totalFolders) + L" folders)";
                            g_ragSyncDone = true;
                        }
                        PostMessageW(hwnd, WM_RAG_SYNC_PROGRESS, 1, 0); // wParam=1 signals completion
                    }).detach();
                    return 0;
                }
                case IDC_BUBBLE_SETTINGS: {
                    g_settingsVisible = !g_settingsVisible;
                    int ids[] = { IDC_BUBBLE_URL_LABEL, IDC_BUBBLE_URL,
                                  IDC_BUBBLE_KEY_LABEL, IDC_BUBBLE_KEY,
                                  IDC_BUBBLE_MODEL_LABEL, IDC_BUBBLE_MODEL,
                                  IDC_RAG_LABEL, IDC_RAG_DESKTOP, IDC_RAG_DOCUMENTS,
                                  IDC_RAG_DOWNLOADS, IDC_RAG_MUSIC, IDC_RAG_VIDEOS,
                                  IDC_RAG_SYNC_BTN, IDC_RAG_STATUS };
                    for (int id : ids) {
                        HWND ctl = GetDlgItem(hwnd, id);
                        if (ctl) ShowWindow(ctl, g_settingsVisible ? SW_SHOW : SW_HIDE);
                    }
                    // Hide history list if open
                    HWND hList = GetDlgItem(hwnd, IDC_BUBBLE_HISTORY_LIST);
                    if (hList) ShowWindow(hList, SW_HIDE);

                    int newH = g_settingsVisible ? 500 : 280;
                    RECT rc; GetWindowRect(hwnd, &rc);
                    int newW = 340;
                    SetWindowPos(hwnd, HWND_TOPMOST, rc.left, rc.top - (newH - (rc.bottom - rc.top)),
                                 newW, newH, SWP_NOACTIVATE | SWP_SHOWWINDOW);
                    InvalidateRect(hwnd, nullptr, TRUE);
                    return 0;
                }
                case IDC_BUBBLE_EXPAND: {
                    g_expanded = !g_expanded;
                    if (g_expanded) {
                        // Center expanded window on screen for best readability
                        int screenW = GetSystemMetrics(SM_CXSCREEN);
                        int screenH = GetSystemMetrics(SM_CYSCREEN);
                        int newW = 580, newH = 500;
                        int newX = (screenW - newW) / 2;
                        int newY = (screenH - newH) / 2;
                        SetWindowPos(hwnd, HWND_TOPMOST, newX, newY, newW, newH, SWP_SHOWWINDOW);
                        g_btnData[4].label = L"Shrink";
                    } else {
                        g_btnData[4].label = L"Expand";
                        int newH = g_settingsVisible ? 500 : 280;
                        RECT rc2; GetWindowRect(hwnd, &rc2);
                        SetWindowPos(hwnd, HWND_TOPMOST, rc2.left, rc2.top, 340, newH, SWP_SHOWWINDOW);
                    }
                    // Resize child controls to fill new window
                    RECT crc; GetClientRect(hwnd, &crc);
                    int cw = crc.right, ch = crc.bottom;
                    int convoH = ch - 110;
                    int inputY = convoH + 8;
                    int btnY = inputY + 36;
                    HWND hConvo2 = GetDlgItem(hwnd, IDC_BUBBLE_CONVO);
                    if (hConvo2) MoveWindow(hConvo2, 28, 38, cw - 56, convoH - 38, TRUE);
                    HWND hEdit2 = GetDlgItem(hwnd, IDC_BUBBLE_EDIT);
                    if (hEdit2) MoveWindow(hEdit2, 28, inputY, cw - 56, 32, TRUE);
                    int btnW2 = 50, btnGap2 = 4;
                    int totalBtnW2 = 6 * btnW2 + 5 * btnGap2;
                    int startX2 = (cw - totalBtnW2) / 2;
                    int ids2[] = { IDC_BUBBLE_SEND, IDC_BUBBLE_VOICE, IDC_BUBBLE_SETTINGS,
                                  IDC_BUBBLE_HISTORY, IDC_BUBBLE_EXPAND, IDC_BUBBLE_CANCEL };
                    for (int i = 0; i < 6; i++) {
                        HWND btn = GetDlgItem(hwnd, ids2[i]);
                        if (btn) MoveWindow(btn, startX2 + i * (btnW2 + btnGap2), btnY, btnW2, 24, TRUE);
                    }
                    InvalidateRect(hwnd, nullptr, TRUE);
                    RefreshConversation(hwnd);
                    return 0;
                }
                case IDC_BUBBLE_CANCEL:
                    DestroyWindow(hwnd);
                    return 0;
                case IDC_BUBBLE_VOICE:
                    StartVoiceRecording(hwnd);
                    return 0;
            }
            break;
        }
        case WM_TIMER: {
            if (wParam == IDT_LOADING) {
                g_loadingDots = (g_loadingDots + 1) % 4;
                g_loadingTickCount++;

                // Watchdog: if thinking for >120 seconds (400 ticks * 300ms), auto-cancel
                if (g_loadingTickCount > 400) {
                    KillTimer(hwnd, IDT_LOADING);
                    g_chatInProgress.store(false);
                    EnableWindow(GetDlgItem(hwnd, IDC_BUBBLE_SEND), TRUE);
                    if (g_agent) g_agent->m_abort.store(true);
                    if (!g_chatHistory.empty()) {
                        g_chatHistory.back().assistantMsg = L"Sorry, the request timed out. Please try again.";
                    }
                    // Log timeout
                    FILE* logFile = nullptr;
                    fopen_s(&logFile, "argos_error.log", "a");
                    if (logFile) {
                        time_t now = time(nullptr);
                        struct tm tm_buf;
                        localtime_s(&tm_buf, &now);
                        char timeBuf[64];
                        strftime(timeBuf, sizeof(timeBuf), "%Y-%m-%d %H:%M:%S", &tm_buf);
                        fprintf(logFile, "[%s] WATCHDOG: Chat timed out after 120 seconds\n", timeBuf);
                        fclose(logFile);
                    }
                    RefreshConversation(hwnd);
                    SetFocus(GetDlgItem(hwnd, IDC_BUBBLE_EDIT));
                    if (g_renderer) g_renderer->SetThinking(false);
                    if (g_renderer) g_renderer->SetExecutingTools(false);
                    return 0;
                }

                // Only update the thinking dots, NOT rebuild the whole conversation
                // This preserves scroll position when user is reading history
                UpdateThinkingDots(hwnd);
                return 0;
            }
            break;
        }
        case WM_CHAT_STREAM: {
            // Safely copy the streaming text under lock to avoid data races
            std::wstring streamedTextCopy;
            {
                std::lock_guard<std::mutex> lock(g_streamingMutex);
                streamedTextCopy = g_streamingPartial;
            }
            // Strip  tags from streaming text — only show direct response
            streamedTextCopy = StripThinkTags(streamedTextCopy);
            // Update the last history entry with streaming partial response
            if (!g_chatHistory.empty()) {
                g_chatHistory.back().assistantMsg = streamedTextCopy;
            }
            // Stop the thinking dots timer — we have real text now
            if (!streamedTextCopy.empty()) {
                KillTimer(hwnd, IDT_LOADING);
                if (g_renderer) g_renderer->SetThinking(false);
                if (g_renderer) g_renderer->SetExecutingTools(false);
            }
            // Refresh conversation to show streaming text
            RefreshConversation(hwnd);
            return 0;
        }
        case WM_CHAT_RESPONSE: {
            KillTimer(hwnd, IDT_LOADING);
            g_chatInProgress.store(false);
            EnableWindow(GetDlgItem(hwnd, IDC_BUBBLE_SEND), TRUE);

            std::wstring response = StripThinkTags(g_pendingResponse);

            // Update the last history entry with the AI response
            if (!g_chatHistory.empty()) {
                g_chatHistory.back().assistantMsg = response;
            }

            // Update conversation display
            RefreshConversation(hwnd);

            // Auto-TTS: read the response aloud
            if (g_autoTTS && !response.empty()) {
                std::string utf8Resp;
                int elen = WideCharToMultiByte(CP_UTF8, 0, response.c_str(), (int)response.size(), nullptr, 0, nullptr, nullptr);
                if (elen > 0) {
                    utf8Resp.resize(elen);
                    WideCharToMultiByte(CP_UTF8, 0, response.c_str(), (int)response.size(), &utf8Resp[0], elen, nullptr, nullptr);
                    argos::ttsSpeak(utf8Resp);
                }
            }

            // Restore focus to input
            SetFocus(GetDlgItem(hwnd, IDC_BUBBLE_EDIT));

            // Stop thinking animation
            if (g_renderer) g_renderer->SetThinking(false);
            if (g_renderer) g_renderer->SetExecutingTools(false);
            return 0;
        }
        case WM_CHAT_ERROR: {
            KillTimer(hwnd, IDT_LOADING);
            g_chatInProgress.store(false);
            EnableWindow(GetDlgItem(hwnd, IDC_BUBBLE_SEND), TRUE);
            // If this was a user-initiated abort (new message), don't show error
            if (g_agent && g_agent->m_abort.load()) {
                // Just clear thinking state — new chat is already starting
                if (g_renderer) g_renderer->SetThinking(false);
                if (g_renderer) g_renderer->SetExecutingTools(false);
                return 0;
            }
            std::wstring errResponse = g_pendingResponse;
            if (errResponse.empty()) errResponse = L"Error: Could not reach AI server.";
            if (!g_chatHistory.empty()) {
                g_chatHistory.back().assistantMsg = errResponse;
            }
            // Log error to file
            FILE* logFile = nullptr;
            fopen_s(&logFile, "argos_error.log", "a");
            if (logFile) {
                time_t now = time(nullptr);
                struct tm tm_buf;
                localtime_s(&tm_buf, &now);
                char timeBuf[64];
                strftime(timeBuf, sizeof(timeBuf), "%Y-%m-%d %H:%M:%S", &tm_buf);
                std::string utf8Err;
                int elen = WideCharToMultiByte(CP_UTF8, 0, errResponse.c_str(), (int)errResponse.size(), nullptr, 0, nullptr, nullptr);
                if (elen > 0) { utf8Err.resize(elen); WideCharToMultiByte(CP_UTF8, 0, errResponse.c_str(), (int)errResponse.size(), &utf8Err[0], elen, nullptr, nullptr); }
                fprintf(logFile, "[%s] WM_CHAT_ERROR: %s\n", timeBuf, utf8Err.c_str());
                fclose(logFile);
            }
            RefreshConversation(hwnd);
            SetFocus(GetDlgItem(hwnd, IDC_BUBBLE_EDIT));
            if (g_renderer) g_renderer->SetThinking(false);
            if (g_renderer) g_renderer->SetExecutingTools(false);
            return 0;
        }
        case WM_VOICE_RESULT: {
            std::wstring transcribed;
            {
                std::lock_guard<std::mutex> lk(g_voiceMutex);
                transcribed = g_voiceTranscribedText;
            }

            if (transcribed.empty()) {
                // No speech detected
                HWND hEdit = GetDlgItem(hwnd, IDC_BUBBLE_EDIT);
                if (hEdit) SetWindowTextW(hEdit, L"");
                MessageBoxW(hwnd, L"No speech detected. Please try again.",
                    L"Argos Voice", MB_OK | MB_ICONINFORMATION);
            } else {
                // Put transcribed text in the edit box
                HWND hEdit = GetDlgItem(hwnd, IDC_BUBBLE_EDIT);
                if (hEdit) SetWindowTextW(hEdit, transcribed.c_str());

                // Auto-send the message
                SendMessageW(hwnd, WM_COMMAND, MAKEWPARAM(IDC_BUBBLE_SEND, BN_CLICKED), 0);
            }
            return 0;
        }
        case WM_RAG_SYNC_PROGRESS: {
            // Update RAG status label from g_ragStatusText
            {
                std::lock_guard<std::mutex> lk(g_ragUiMutex);
                HWND hStatus = GetDlgItem(hwnd, IDC_RAG_STATUS);
                if (hStatus) SetWindowTextW(hStatus, g_ragStatusText.c_str());
            }
            if (wParam == 1) {
                // Sync complete — re-enable button
                EnableWindow(GetDlgItem(hwnd, IDC_RAG_SYNC_BTN), TRUE);
            }
            return 0;
        }
        case WM_CLOSE:
            DestroyWindow(hwnd);
            return 0;
        case WM_DESTROY:
            if (g_bubbleFont) { DeleteObject(g_bubbleFont); g_bubbleFont = nullptr; }
            if (g_bubbleTitleFont) { DeleteObject(g_bubbleTitleFont); g_bubbleTitleFont = nullptr; }
            if (g_bubbleSmallFont) { DeleteObject(g_bubbleSmallFont); g_bubbleSmallFont = nullptr; }
            if (g_bubbleBgBrush) { DeleteObject(g_bubbleBgBrush); g_bubbleBgBrush = nullptr; }
            if (g_bubbleEditBgBrush) { DeleteObject(g_bubbleEditBgBrush); g_bubbleEditBgBrush = nullptr; }
            g_bubbleHwnd = nullptr;
            g_settingsVisible = false;
            g_expanded = false;
            // Resume proactive Argos when chat closes
            if (g_windowMgr && g_windowMgr->GetHwnd()) {
                StartProactiveTimer(g_windowMgr->GetHwnd());
            }
            return 0;
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

// ── Proactive speech bubble — small popup showing Argos's spontaneous messages ──
static LRESULT CALLBACK ProactiveBubbleProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
        case WM_ERASEBKGND:
            return 1;
        case WM_PAINT: {
            PAINTSTRUCT ps;
            HDC hdc = BeginPaint(hwnd, &ps);
            RECT rc;
            GetClientRect(hwnd, &rc);
            int w = rc.right, h = rc.bottom;

            // Double-buffer
            HDC memDC = CreateCompatibleDC(hdc);
            HBITMAP memBmp = CreateCompatibleBitmap(hdc, w, h);
            HBITMAP oldBmp = (HBITMAP)SelectObject(memDC, memBmp);

            // Magenta background (transparent via color key)
            HBRUSH magBrush = CreateSolidBrush(RGB(255, 0, 255));
            FillRect(memDC, &rc, magBrush);
            DeleteObject(magBrush);

            // Bubble geometry — reserve space at bottom for tail
            int tailH = 22;
            int bL = 8, bT = 8, bR = w - 8, bB = h - tailH - 4;
            if (g_bubbleBelowRobot) {
                // Reserve space at top for tail pointing up
                bT = tailH + 4;
                bB = h - 8;
            }
            int radius = 18;
            int tailX = w / 2;
            int tailW = 12;

            HPEN nullPen = (HPEN)GetStockObject(NULL_PEN);
            HBRUSH whiteBrush = CreateSolidBrush(RGB(255, 255, 255));
            HBRUSH glowBrush = CreateSolidBrush(NEON_BLUE_GLOW);
            HBRUSH dimGlowBrush = CreateSolidBrush(NEON_BLUE_DIM);

            // Glow halo
            SelectObject(memDC, nullPen);
            SelectObject(memDC, glowBrush);
            RoundRect(memDC, bL - 5, bT - 5, bR + 5, bB + 5, (radius + 5) * 2, (radius + 5) * 2);
            SelectObject(memDC, dimGlowBrush);
            RoundRect(memDC, bL - 2, bT - 2, bR + 2, bB + 2, (radius + 2) * 2, (radius + 2) * 2);

            // Tail fill
            SelectObject(memDC, nullPen);
            SelectObject(memDC, whiteBrush);
            if (g_bubbleBelowRobot) {
                POINT tailUp[] = {
                    {tailX - tailW, bT + 2},
                    {tailX + tailW, bT + 2},
                    {tailX, bT - tailH}
                };
                Polygon(memDC, tailUp, 3);
            } else {
                POINT tail[] = {
                    {tailX - tailW, bB - 2},
                    {tailX + tailW, bB - 2},
                    {tailX, bB + tailH}
                };
                Polygon(memDC, tail, 3);
            }

            // White bubble body
            RoundRect(memDC, bL, bT, bR, bB, radius * 2, radius * 2);

            // Neon header bar
            HBRUSH barBrush = CreateSolidBrush(NEON_BLUE_BAR);
            SelectObject(memDC, nullPen);
            SelectObject(memDC, barBrush);
            RoundRect(memDC, bL + 1, bT + 1, bR - 1, bT + 6, radius * 2, radius * 2);
            DeleteObject(barBrush);

            // Neon outline
            HPEN neonPen = CreatePen(PS_SOLID, 2, NEON_BLUE);
            SelectObject(memDC, neonPen);
            SelectObject(memDC, GetStockObject(NULL_BRUSH));
            RoundRect(memDC, bL, bT, bR, bB, radius * 2, radius * 2);

            // Erase outline where tail connects
            SelectObject(memDC, nullPen);
            SelectObject(memDC, whiteBrush);
            if (g_bubbleBelowRobot) {
                RECT eraseRect = {tailX - tailW, bT - 2, tailX + tailW, bT + 2};
                FillRect(memDC, &eraseRect, whiteBrush);
            } else {
                RECT eraseRect = {tailX - tailW, bB - 2, tailX + tailW, bB + 2};
                FillRect(memDC, &eraseRect, whiteBrush);
            }

            // Tail outline
            SelectObject(memDC, neonPen);
            SelectObject(memDC, GetStockObject(NULL_BRUSH));
            if (g_bubbleBelowRobot) {
                MoveToEx(memDC, tailX - tailW, bT, nullptr);
                LineTo(memDC, tailX, bT - tailH);
                LineTo(memDC, tailX + tailW, bT);
            } else {
                MoveToEx(memDC, tailX - tailW, bB, nullptr);
                LineTo(memDC, tailX, bB + tailH);
                LineTo(memDC, tailX + tailW, bB);
            }

            // Draw the message text — LARGE bold font for manga-style readability
            HFONT msgFont = CreateFontW(24, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
                DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_SWISS, L"Segoe UI Semibold");
            HFONT oldFont = (HFONT)SelectObject(memDC, msgFont);
            SetBkMode(memDC, TRANSPARENT);

            // "Argos says:" label in neon blue (bold, manga-style)
            HFONT labelFont = CreateFontW(17, 0, 0, 0, FW_EXTRABOLD, FALSE, FALSE, FALSE,
                DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_SWISS, L"Segoe UI Black");
            HFONT emojiFont = CreateFontW(24, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_SWISS, L"Segoe UI Emoji");
            SelectObject(memDC, labelFont);
            SetTextColor(memDC, TEXT_NEON);
            RECT labelRect = {bL + 14, bT + 10, bR - 14, bT + 32};
            DrawTextW(memDC, L"Argos says:", -1, &labelRect, DT_LEFT | DT_SINGLELINE);

            // Message body — bold black text with colorful emoji, fills remaining bubble space
            // Draw text character by character: regular text in bold black, emoji in color
            SelectObject(memDC, msgFont);
            RECT textRect = {bL + 14, bT + 36, bR - 14, bB - 8};
            
            // Check if message contains emoji characters
            bool hasEmoji = false;
            for (wchar_t c : g_proactiveMsg) {
                if (c >= 0x1F000 || (c >= 0x2600 && c <= 0x27BF) || (c >= 0xFE00 && c <= 0xFE0F)) {
                    hasEmoji = true;
                    break;
                }
            }
            
            if (hasEmoji) {
                // Draw with emoji font for colorful rendering on Windows 10+
                SelectObject(memDC, emojiFont);
                SetTextColor(memDC, RGB(0, 0, 0));
                DrawTextW(memDC, g_proactiveMsg.c_str(), (int)g_proactiveMsg.size(),
                         &textRect, DT_LEFT | DT_WORDBREAK | DT_TOP);
            } else {
                SetTextColor(memDC, RGB(0, 0, 0));
                DrawTextW(memDC, g_proactiveMsg.c_str(), (int)g_proactiveMsg.size(),
                         &textRect, DT_LEFT | DT_WORDBREAK | DT_TOP);
            }

            DeleteObject(SelectObject(memDC, oldFont));
            DeleteObject(labelFont);
            DeleteObject(emojiFont);
            DeleteObject(neonPen);
            DeleteObject(whiteBrush);
            DeleteObject(glowBrush);
            DeleteObject(dimGlowBrush);

            BitBlt(hdc, 0, 0, w, h, memDC, 0, 0, SRCCOPY);
            SelectObject(memDC, oldBmp);
            DeleteObject(memBmp);
            DeleteDC(memDC);

            EndPaint(hwnd, &ps);
            return 0;
        }
        case WM_LBUTTONDOWN:
        case WM_RBUTTONDOWN:
            // Click anywhere to dismiss
            DestroyWindow(hwnd);
            return 0;
        case WM_TIMER:
            if (wParam == IDT_PROACTIVE_BUBBLE_TIMEOUT) {
                DestroyWindow(hwnd);
                return 0;
            }
            break;
        case WM_DESTROY:
            g_proactiveBubble = nullptr;
            KillTimer(hwnd, IDT_PROACTIVE_BUBBLE_TIMEOUT);
            // Restart proactive timer: 10 seconds AFTER bubble disappears
            if (g_proactiveActive && !g_bubbleHwnd && g_windowMgr && g_windowMgr->GetHwnd()) {
                StartProactiveTimer(g_windowMgr->GetHwnd());
            }
            return 0;
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

// Strip <think>...</think> tags from AI responses (DeepSeek models output these)
static std::wstring StripThinkTags(const std::wstring& text) {
    std::wstring result = text;
    size_t pos = 0;
    while ((pos = result.find(L"<think>", pos)) != std::wstring::npos) {
        size_t end = result.find(L"</think>", pos);
        if (end == std::wstring::npos) {
            // No closing tag — remove from <think> to end
            result.erase(pos);
            break;
        }
        result.erase(pos, end + 8 - pos);
    }
    // Also strip standalone </think> if any remain
    pos = 0;
    while ((pos = result.find(L"</think>", pos)) != std::wstring::npos) {
        result.erase(pos, 8);
    }
    // Trim leading whitespace/newlines left behind
    while (!result.empty() && (result[0] == L'\n' || result[0] == L'\r' || result[0] == L' ' || result[0] == L'\t')) {
        result.erase(0, 1);
    }
    return result;
}

static void ShowProactiveBubble(HWND robotHwnd, const std::wstring& message) {
    // Strip <think> tags — proactive bubble should only show direct thoughts
    std::wstring cleanMsg = StripThinkTags(message);
    if (cleanMsg.empty()) return;

    if (g_proactiveBubble) {
        // Update existing bubble
        g_proactiveMsg = cleanMsg;
        InvalidateRect(g_proactiveBubble, nullptr, TRUE);
        // Recalculate dismiss time based on new message word count
        int wordCount = 1;
        for (wchar_t c : cleanMsg) if (c == L' ' || c == L'\n') wordCount++;
        int dismissMs = (std::max)(6, wordCount * 2) * 1000;
        SetTimer(g_proactiveBubble, IDT_PROACTIVE_BUBBLE_TIMEOUT, dismissMs, nullptr);
        return;
    }

    g_proactiveMsg = cleanMsg;

    static bool registered = false;
    if (!registered) {
        WNDCLASSW wc = {};
        wc.lpfnWndProc = ProactiveBubbleProc;
        wc.hInstance = GetModuleHandleW(nullptr);
        wc.lpszClassName = L"ArgosProactiveBubble";
        wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
        wc.hbrBackground = nullptr;
        RegisterClassW(&wc);
        registered = true;
    }

    // Auto-adjust bubble size based on actual text measurement
    int bubbleW = 380;
    int bubbleH = 140;  // Minimum height

    // Measure text to determine needed height
    HDC screenDC = GetDC(nullptr);
    HFONT measureFont = CreateFontW(24, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
        DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
        CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_SWISS, L"Segoe UI Semibold");
    HFONT oldFont = (HFONT)SelectObject(screenDC, measureFont);

    // Available text width (bubble width - padding - margins)
    int textAvailW = bubbleW - 16 - 28;  // bL(8) + left margin(14) + right margin(14) + bR(8) - correction
    RECT measureRect = {0, 0, textAvailW, 0};
    DrawTextW(screenDC, message.c_str(), (int)message.size(),
             &measureRect, DT_LEFT | DT_WORDBREAK | DT_TOP | DT_CALCRECT);
    int textH = measureRect.bottom - measureRect.top;

    SelectObject(screenDC, oldFont);
    DeleteObject(measureFont);
    ReleaseDC(nullptr, screenDC);

    // Calculate bubble height: padding + label(32) + text + tail(22) + margins
    int neededH = 8 + 36 + textH + 22 + 12;  // top pad + label area + text + tail + bottom pad
    bubbleH = (std::max)(neededH, 140);

    // Widen bubble if text is very long
    int msgLen = (int)message.size();
    if (msgLen > 80)  { bubbleW = 420; }
    if (msgLen > 160) { bubbleW = 460; }
    if (msgLen > 250) { bubbleW = 500; }

    // Cap height to reasonable max
    if (bubbleH > 320) bubbleH = 320;

    // Position above the robot — clamp to screen edges for readability
    RECT rc;
    GetWindowRect(robotHwnd, &rc);
    int screenW = GetSystemMetrics(SM_CXSCREEN);
    int screenH = GetSystemMetrics(SM_CYSCREEN);
    int x = rc.left + (rc.right - rc.left) / 2 - bubbleW / 2;
    int y = rc.top - bubbleH + 10;
    if (y < 0) {
        y = rc.bottom + 10;
        g_bubbleBelowRobot = true;
    } else {
        g_bubbleBelowRobot = false;
    }
    // Clamp X to keep entire bubble visible on screen
    if (x < 4) x = 4;
    if (x + bubbleW > screenW - 4) x = screenW - bubbleW - 4;
    // Clamp Y to keep entire bubble visible on screen
    if (y + bubbleH > screenH - 4) y = screenH - bubbleH - 4;
    if (y < 4) y = 4;

    g_proactiveBubble = CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST,
        L"ArgosProactiveBubble", L"",
        WS_POPUP,
        x, y, bubbleW, bubbleH,
        nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);

    SetLayeredWindowAttributes(g_proactiveBubble, RGB(255, 0, 255), 255, LWA_COLORKEY);
    ShowWindow(g_proactiveBubble, SW_SHOWNOACTIVATE);
    UpdateWindow(g_proactiveBubble);

    // Auto-dismiss: 2 seconds per word in the message (minimum 6 seconds)
    int wordCount = 1;
    for (wchar_t c : message) if (c == L' ' || c == L'\n') wordCount++;
    int dismissMs = (std::max)(6, wordCount * 2) * 1000;
    SetTimer(g_proactiveBubble, IDT_PROACTIVE_BUBBLE_TIMEOUT, dismissMs, nullptr);
}

static void CloseProactiveBubble() {
    if (g_proactiveBubble) {
        DestroyWindow(g_proactiveBubble);
        g_proactiveBubble = nullptr;
    }
}

static void StartProactiveTimer(HWND hwnd) {
    if (!g_proactiveActive) return;
    int interval = GetRandomProactiveInterval();
    SetTimer(hwnd, IDT_PROACTIVE, interval, nullptr);
}

static void StopProactiveTimer(HWND hwnd) {
    KillTimer(hwnd, IDT_PROACTIVE);
    g_proactiveBusy = false;
    CloseProactiveBubble();
}

static void UpdateBubblePosition(HWND robotHwnd) {
    if (!g_bubbleHwnd || !robotHwnd) return;
    if (g_expanded) return; // Don't reposition when expanded
    RECT rc;
    GetWindowRect(robotHwnd, &rc);
    int bubbleW = 340, bubbleH = g_settingsVisible ? 500 : 280;
    int screenW = GetSystemMetrics(SM_CXSCREEN);
    int x = rc.left + (rc.right - rc.left) / 2 - bubbleW / 2;
    int y = rc.top - bubbleH + 15;
    bool wasBelow = g_bubbleBelowRobot;
    if (y < 0) {
        y = rc.bottom + 10;
        g_bubbleBelowRobot = true;
    } else {
        g_bubbleBelowRobot = false;
    }
    // Clamp X to keep entire bubble visible on screen
    if (x < 4) x = 4;
    if (x + bubbleW > screenW - 4) x = screenW - bubbleW - 4;
    SetWindowPos(g_bubbleHwnd, HWND_TOPMOST, x, y, bubbleW, bubbleH,
                 SWP_NOACTIVATE | SWP_SHOWWINDOW);
    // Repaint if tail direction changed
    if (wasBelow != g_bubbleBelowRobot) {
        InvalidateRect(g_bubbleHwnd, nullptr, TRUE);
    }
}

static void ShowMangaBubble(HINSTANCE hInstance, HWND parent) {
    if (g_bubbleHwnd) {
        SetForegroundWindow(g_bubbleHwnd);
        return;
    }

    static bool registered = false;
    if (!registered) {
        WNDCLASSW wc = {};
        wc.lpfnWndProc = BubbleWndProc;
        wc.hInstance = hInstance;
        wc.lpszClassName = L"ArgosMangaBubble";
        wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
        wc.hbrBackground = nullptr;
        RegisterClassW(&wc);
        registered = true;
    }

    // Position above the robot window — clamp to screen edges for readability
    RECT rc;
    GetWindowRect(parent, &rc);
    int screenW = GetSystemMetrics(SM_CXSCREEN);
    int bubbleW = 340, bubbleH = 280;
    int x = rc.left + (rc.right - rc.left) / 2 - bubbleW / 2;
    int y = rc.top - bubbleH + 15; // tail overlaps robot slightly
    if (y < 0) {
        y = rc.bottom + 10;
        g_bubbleBelowRobot = true;
    } else {
        g_bubbleBelowRobot = false;
    }
    // Clamp X to keep entire bubble visible on screen
    if (x < 4) x = 4;
    if (x + bubbleW > screenW - 4) x = screenW - bubbleW - 4;

    g_bubbleHwnd = CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST,
        L"ArgosMangaBubble", L"",
        WS_POPUP,
        x, y, bubbleW, bubbleH,
        nullptr, nullptr, hInstance, nullptr);

    // Color-key transparency: magenta pixels become transparent
    SetLayeredWindowAttributes(g_bubbleHwnd, RGB(255, 0, 255), 255, LWA_COLORKEY);

    ShowWindow(g_bubbleHwnd, SW_SHOWNOACTIVATE);
    UpdateWindow(g_bubbleHwnd);
    SetFocus(g_bubbleHwnd);

    // Auto-scroll conversation to bottom so latest chat is visible
    HWND hConvo = GetDlgItem(g_bubbleHwnd, IDC_BUBBLE_CONVO);
    if (hConvo) {
        LRESULT textLen = SendMessageW(hConvo, WM_GETTEXTLENGTH, 0, 0);
        SendMessageW(hConvo, EM_SETSEL, textLen, textLen);
        SendMessageW(hConvo, EM_SCROLLCARET, 0, 0);
    }
    // Focus the input edit box for immediate typing
    HWND hEdit = GetDlgItem(g_bubbleHwnd, IDC_BUBBLE_EDIT);
    if (hEdit) SetFocus(hEdit);
}

LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
        case WM_CREATE: {
            g_renderer = new RobotRenderer();
            if (!g_renderer->Initialize(hwnd)) {
                MessageBox(hwnd, L"Failed to initialize Direct2D", L"Error", MB_ICONERROR);
                return -1;
            }
            SetTimer(hwnd, IDT_ANIMATE, ANIMATE_INTERVAL_MS, nullptr);
            // Start proactive Argos — first message after 5 seconds
            SetTimer(hwnd, IDT_PROACTIVE, 5000, nullptr);
            return 0;
        }

        case WM_TIMER: {
            if (wParam == IDT_ANIMATE && g_renderer) {
                g_renderer->Update();
                // Sync tool execution state for lightning effect
                if (g_agent) {
                    g_renderer->SetExecutingTools(g_agent->m_executingTools.load());
                }
                g_renderer->Render();

                // Keep manga bubble positioned above the robot
                UpdateBubblePosition(hwnd);

                // Keep proactive bubble positioned above robot too — with full screen clamping
                if (g_proactiveBubble) {
                    RECT rc; GetWindowRect(hwnd, &rc);
                    RECT brc; GetWindowRect(g_proactiveBubble, &brc);
                    int bw = brc.right - brc.left, bh = brc.bottom - brc.top;
                    int screenW2 = GetSystemMetrics(SM_CXSCREEN);
                    int screenH2 = GetSystemMetrics(SM_CYSCREEN);
                    int x = rc.left + (rc.right - rc.left) / 2 - bw / 2;
                    int y = rc.top - bh + 10;
                    bool wasBelow = g_bubbleBelowRobot;
                    if (y < 0) {
                        y = rc.bottom + 10;
                        g_bubbleBelowRobot = true;
                    } else {
                        g_bubbleBelowRobot = false;
                    }
                    // Clamp X to screen edges
                    if (x < 4) x = 4;
                    if (x + bw > screenW2 - 4) x = screenW2 - bw - 4;
                    // Clamp Y to screen edges
                    if (y + bh > screenH2 - 4) y = screenH2 - bh - 4;
                    if (y < 4) y = 4;
                    SetWindowPos(g_proactiveBubble, HWND_TOPMOST, x, y, 0, 0,
                                 SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
                    // Repaint if tail direction changed
                    if (wasBelow != g_bubbleBelowRobot) {
                        InvalidateRect(g_proactiveBubble, nullptr, TRUE);
                    }
                }

                // Check if head was clicked → show input dialog
                if (g_renderer->WantsInputDialog()) {
                    g_renderer->ClearInputDialogFlag();
                    // Stop proactive when chat opens
                    StopProactiveTimer(hwnd);
                    ShowMangaBubble((HINSTANCE)GetWindowLongPtr(hwnd, GWLP_HINSTANCE), hwnd);
                }
            }
            else if (wParam == IDT_PROACTIVE) {
                // Proactive check-in: gather screen context and ask AI for a message
                if (!g_proactiveBusy && !g_bubbleHwnd && g_proactiveActive) {
                    g_proactiveBusy = true;
                    // Kill this timer; we'll restart with new random interval after response
                    KillTimer(hwnd, IDT_PROACTIVE);

                    // Gather screen context on background thread, then call AI
                    std::thread([hwnd]() {
                        try {
                            // Gather screen context with privacy filtering
                            std::wstring wCtx = GatherScreenContext();

                            // Add personality variety hint
                            std::wstring hint = GetRandomPersonalityHint();
                            std::wstring fullCtx = wCtx + L"\n\nPersonality direction: " + hint;

                            // Call AI for a proactive message
                            std::wstring response = g_agent->ProactiveChat(fullCtx);

                            // If AI returned empty or error, use a conversational fallback
                            if (response.empty()) {
                                static const wchar_t* fallbacks[] = {
                                    L"Hey! What are you up to? 👀",
                                    L"Just checking in — how's it going?",
                                    L"You've been quiet for a bit. Everything good?",
                                    L"Hey, I'm here! Need anything?",
                                    L"Still keeping watch. You're doing great! 😊",
                                };
                                static std::mt19937 fb_rng(std::random_device{}());
                                std::uniform_int_distribution<int> fb_dist(0, 4);
                                response = fallbacks[fb_dist(fb_rng)];
                            }

                            g_proactiveMsg = response;
                            PostMessageW(hwnd, WM_PROACTIVE_RESPONSE, 0, 0);
                        } catch (...) {
                            // Silently ignore proactive errors — don't crash the app
                            g_proactiveBusy = false;
                            if (g_windowMgr && g_windowMgr->GetHwnd()) {
                                StartProactiveTimer(g_windowMgr->GetHwnd());
                            }
                        }
                    }).detach();
                }
                return 0;
            }
            else if (wParam == IDT_VOICE_DELAYED) {
                KillTimer(hwnd, IDT_VOICE_DELAYED);
                if (g_bubbleHwnd) {
                    StartVoiceRecording(g_bubbleHwnd, 30);
                }
                return 0;
            }
            return 0;
        }

        case WM_PROACTIVE_RESPONSE: {
            g_proactiveBusy = false;

            // Show the proactive bubble with Argos's message
            // Show it even if it's an error — so user sees something is happening
            if (!g_proactiveMsg.empty() && !g_bubbleHwnd) {
                ShowProactiveBubble(hwnd, g_proactiveMsg);
                // Auto-TTS: read proactive bubble aloud
                if (g_autoTTS) {
                    std::wstring cleanMsg = StripThinkTags(g_proactiveMsg);
                    std::string utf8Msg;
                    int elen = WideCharToMultiByte(CP_UTF8, 0, cleanMsg.c_str(), (int)cleanMsg.size(), nullptr, 0, nullptr, nullptr);
                    if (elen > 0) {
                        utf8Msg.resize(elen);
                        WideCharToMultiByte(CP_UTF8, 0, cleanMsg.c_str(), (int)cleanMsg.size(), &utf8Msg[0], elen, nullptr, nullptr);
                        argos::ttsSpeak(utf8Msg);
                    }
                }
            }
            // Timer restarts when bubble is destroyed (WM_DESTROY in ProactiveBubbleProc)
            // This ensures 10 seconds starts AFTER the bubble disappears
            return 0;
        }

        case WM_CAPSLOCK_PUSHTOTALK: {
            // Caps Lock pressed — if TTS is speaking, stop it instead of recording
            if (argos::ttsIsSpeaking()) {
                argos::ttsStop();
                return 0;
            }
            // Otherwise, start push-to-talk
            // If bubble is open, record into it; otherwise open bubble first
            if (g_bubbleHwnd) {
                StartVoiceRecording(g_bubbleHwnd, 30);
            } else {
                // Show the bubble, then start recording after a short delay
                StopProactiveTimer(hwnd);
                ShowMangaBubble((HINSTANCE)GetWindowLongPtr(hwnd, GWLP_HINSTANCE), hwnd);
                SetTimer(hwnd, IDT_VOICE_DELAYED, 100, nullptr);
            }
            return 0;
        }

        case WM_PAINT: {
            if (g_renderer) g_renderer->Render();
            ValidateRect(hwnd, nullptr);
            return 0;
        }

        case WM_LBUTTONDOWN: {
            if (g_renderer) {
                int mouseX = GET_X_LPARAM(lParam);
                int mouseY = GET_Y_LPARAM(lParam);
                g_renderer->OnMouseDown(mouseX, mouseY);
                SetCapture(hwnd);
            }
            return 0;
        }

        case WM_MOUSEMOVE: {
            if (g_renderer) {
                int mouseX = GET_X_LPARAM(lParam);
                int mouseY = GET_Y_LPARAM(lParam);
                g_renderer->OnMouseMove(mouseX, mouseY);
            }
            return 0;
        }

        case WM_LBUTTONUP: {
            if (g_renderer) {
                int mouseX = GET_X_LPARAM(lParam);
                int mouseY = GET_Y_LPARAM(lParam);
                g_renderer->OnMouseUp(mouseX, mouseY);
                ReleaseCapture();
            }
            return 0;
        }

        case WM_RBUTTONDOWN: {
            if (g_tray) g_tray->ShowContextMenu(hwnd);
            return 0;
        }

        case WM_COMMAND: {
            switch (LOWORD(wParam)) {
                case ID_TRAY_SHOW: g_windowMgr->Show(); break;
                case ID_TRAY_HIDE: g_windowMgr->Hide(); break;
                case ID_TRAY_QUIT: DestroyWindow(hwnd); break;
            }
            return 0;
        }

        case WM_DESTROY: {
            KillTimer(hwnd, IDT_ANIMATE);
            KillTimer(hwnd, IDT_PROACTIVE);
            CloseProactiveBubble();
            // Uninstall keyboard hook
            if (g_kbHook) { UnhookWindowsHookEx(g_kbHook); g_kbHook = nullptr; }
            if (g_renderer) { delete g_renderer; g_renderer = nullptr; }
            PostQuitMessage(0);
            return 0;
        }

        case WM_SIZE: {
            if (g_renderer) g_renderer->OnResize(LOWORD(lParam), HIWORD(lParam));
            return 0;
        }
    }

    return DefWindowProc(hwnd, msg, wParam, lParam);
}

int APIENTRY WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    // Initialize common controls
    INITCOMMONCONTROLSEX icc = {sizeof(icc), ICC_STANDARD_CLASSES};
    InitCommonControlsEx(&icc);

    g_windowMgr = new WindowManager();
    if (!g_windowMgr->Create(hInstance, WndProc)) {
        MessageBox(nullptr, L"Failed to create window", L"Error", MB_ICONERROR);
        return 1;
    }

    g_tray = new TrayIcon();
    g_tray->Initialize(hInstance, g_windowMgr->GetHwnd());

    g_agent = new AgentClient();
    // Load config from file or environment variables
    ArgosConfig cfg = LoadConfig();
    g_agent->SetServerUrl(cfg.serverUrl);
    if (!cfg.apiKey.empty()) g_agent->SetApiKey(cfg.apiKey);
    g_agent->SetModel(cfg.model);
    g_agent->SetFallbackModel(cfg.fallbackModel);
    g_agent->SetVisionModel(cfg.visionModel);

    g_windowMgr->Show();

    // Install low-level keyboard hook for Caps Lock push-to-talk
    g_kbHook = SetWindowsHookExW(WH_KEYBOARD_LL, LowLevelKbProc, hInstance, 0);

    MSG msg;
    while (GetMessage(&msg, nullptr, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }

    if (g_tray) delete g_tray;
    if (g_agent) delete g_agent;
    if (g_windowMgr) delete g_windowMgr;

    return (int)msg.wParam;
}
