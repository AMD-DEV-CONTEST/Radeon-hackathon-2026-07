#include "computer_use_tool.h"

#if defined(_WIN32)
    #ifndef NOMINMAX
    #define NOMINMAX
    #endif
    #include <windows.h>
#endif

#include <vector>
#include <cctype>

namespace computetool {

// ===== Key Name to Virtual Key Code Mapping =====

unsigned short key_name_to_vk(const std::string& key) {
    std::string lower = key;
    for (auto& c : lower) c = static_cast<char>(tolower(static_cast<unsigned char>(c)));

#if defined(_WIN32)
    if (lower == "enter" || lower == "return") return VK_RETURN;
    if (lower == "tab") return VK_TAB;
    if (lower == "escape" || lower == "esc") return VK_ESCAPE;
    if (lower == "backspace" || lower == "back") return VK_BACK;
    if (lower == "delete" || lower == "del") return VK_DELETE;
    if (lower == "space") return VK_SPACE;
    if (lower == "up") return VK_UP;
    if (lower == "down") return VK_DOWN;
    if (lower == "left") return VK_LEFT;
    if (lower == "right") return VK_RIGHT;
    if (lower == "home") return VK_HOME;
    if (lower == "end") return VK_END;
    if (lower == "pageup") return VK_PRIOR;
    if (lower == "pagedown") return VK_NEXT;
    if (lower == "insert") return VK_INSERT;
    if (lower == "f1") return VK_F1;
    if (lower == "f2") return VK_F2;
    if (lower == "f3") return VK_F3;
    if (lower == "f4") return VK_F4;
    if (lower == "f5") return VK_F5;
    if (lower == "f6") return VK_F6;
    if (lower == "f7") return VK_F7;
    if (lower == "f8") return VK_F8;
    if (lower == "f9") return VK_F9;
    if (lower == "f10") return VK_F10;
    if (lower == "f11") return VK_F11;
    if (lower == "f12") return VK_F12;
    if (lower == "ctrl" || lower == "control") return VK_CONTROL;
    if (lower == "shift") return VK_SHIFT;
    if (lower == "alt") return VK_MENU;
    if (lower == "win" || lower == "meta") return VK_LWIN;
    if (lower == "capslock") return VK_CAPITAL;
    if (lower == "numlock") return VK_NUMLOCK;
    if (lower == "scrolllock") return VK_SCROLL;
    if (lower == "printscreen") return VK_SNAPSHOT;
    if (lower == "pause") return VK_PAUSE;
    if (key.size() == 1) return VkKeyScanA(key[0]) & 0xFF;
#else
    (void)lower;
    (void)key;
#endif
    return 0;
}

// ===== Mouse API =====

std::string mouse_click(int x, int y) {
#if defined(_WIN32)
    INPUT inputs[3] = {};
    // Move mouse to (x, y) in absolute coordinates
    inputs[0].type = INPUT_MOUSE;
    inputs[0].mi.dx = static_cast<LONG>(x * 65535.0 / GetSystemMetrics(SM_CXSCREEN));
    inputs[0].mi.dy = static_cast<LONG>(y * 65535.0 / GetSystemMetrics(SM_CYSCREEN));
    inputs[0].mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE;
    // Left button down
    inputs[1].type = INPUT_MOUSE;
    inputs[1].mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
    // Left button up
    inputs[2].type = INPUT_MOUSE;
    inputs[2].mi.dwFlags = MOUSEEVENTF_LEFTUP;
    SendInput(3, inputs, sizeof(INPUT));
    Sleep(150);
    return "{\"success\":true,\"x\":" + std::to_string(x) + ",\"y\":" + std::to_string(y) + "}";
#else
    (void)x; (void)y;
    return "{\"success\":false,\"error\":\"Not supported on this platform\"}";
#endif
}

std::string mouse_right_click(int x, int y) {
#if defined(_WIN32)
    INPUT inputs[3] = {};
    inputs[0].type = INPUT_MOUSE;
    inputs[0].mi.dx = static_cast<LONG>(x * 65535.0 / GetSystemMetrics(SM_CXSCREEN));
    inputs[0].mi.dy = static_cast<LONG>(y * 65535.0 / GetSystemMetrics(SM_CYSCREEN));
    inputs[0].mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE;
    inputs[1].type = INPUT_MOUSE;
    inputs[1].mi.dwFlags = MOUSEEVENTF_RIGHTDOWN;
    inputs[2].type = INPUT_MOUSE;
    inputs[2].mi.dwFlags = MOUSEEVENTF_RIGHTUP;
    SendInput(3, inputs, sizeof(INPUT));
    Sleep(150);
    return "{\"success\":true,\"x\":" + std::to_string(x) + ",\"y\":" + std::to_string(y) + "}";
#else
    (void)x; (void)y;
    return "{\"success\":false,\"error\":\"Not supported on this platform\"}";
#endif
}

std::string mouse_double_click(int x, int y) {
#if defined(_WIN32)
    // First click
    mouse_click(x, y);
    Sleep(100);
    // Second click (just down + up, mouse already positioned)
    INPUT inputs[2] = {};
    inputs[0].type = INPUT_MOUSE;
    inputs[0].mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
    inputs[1].type = INPUT_MOUSE;
    inputs[1].mi.dwFlags = MOUSEEVENTF_LEFTUP;
    SendInput(2, inputs, sizeof(INPUT));
    Sleep(150);
    return "{\"success\":true,\"x\":" + std::to_string(x) + ",\"y\":" + std::to_string(y) + "}";
#else
    (void)x; (void)y;
    return "{\"success\":false,\"error\":\"Not supported on this platform\"}";
#endif
}

std::string mouse_move(int x, int y) {
#if defined(_WIN32)
    INPUT input = {};
    input.type = INPUT_MOUSE;
    input.mi.dx = static_cast<LONG>(x * 65535.0 / GetSystemMetrics(SM_CXSCREEN));
    input.mi.dy = static_cast<LONG>(y * 65535.0 / GetSystemMetrics(SM_CYSCREEN));
    input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE;
    SendInput(1, &input, sizeof(INPUT));
    return "{\"success\":true,\"x\":" + std::to_string(x) + ",\"y\":" + std::to_string(y) + "}";
#else
    (void)x; (void)y;
    return "{\"success\":false,\"error\":\"Not supported on this platform\"}";
#endif
}

std::string mouse_position() {
#if defined(_WIN32)
    POINT pt;
    GetCursorPos(&pt);
    return "{\"success\":true,\"x\":" + std::to_string(pt.x) + ",\"y\":" + std::to_string(pt.y) + "}";
#else
    return "{\"success\":false,\"error\":\"Not supported on this platform\"}";
#endif
}

std::string mouse_scroll(int delta) {
#if defined(_WIN32)
    INPUT input = {};
    input.type = INPUT_MOUSE;
    input.mi.dwFlags = MOUSEEVENTF_WHEEL;
    input.mi.mouseData = static_cast<DWORD>(delta * WHEEL_DELTA);
    SendInput(1, &input, sizeof(INPUT));
    return "{\"success\":true,\"delta\":" + std::to_string(delta) + "}";
#else
    (void)delta;
    return "{\"success\":false,\"error\":\"Not supported on this platform\"}";
#endif
}

// ===== Keyboard API =====

std::string keyboard_type(const std::string& text) {
#if defined(_WIN32)
    for (char c : text) {
        if (c == ' ') {
            keybd_event(VK_SPACE, 0, 0, 0);
            keybd_event(VK_SPACE, 0, KEYEVENTF_KEYUP, 0);
        } else if (c == '\n' || c == '\r') {
            keybd_event(VK_RETURN, 0, 0, 0);
            keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0);
        } else if (static_cast<unsigned char>(c) >= 0x80) {
            // Non-ASCII: use Unicode input
            INPUT input = {};
            input.type = INPUT_KEYBOARD;
            input.ki.wScan = static_cast<unsigned char>(c);
            input.ki.dwFlags = KEYEVENTF_UNICODE;
            SendInput(1, &input, sizeof(INPUT));
            input.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP;
            SendInput(1, &input, sizeof(INPUT));
        } else {
            short vk = VkKeyScanA(c);
            if (vk != -1) {
                BYTE vkey = vk & 0xFF;
                bool shift = (vk & 0x100) != 0;
                if (shift) keybd_event(VK_SHIFT, 0, 0, 0);
                keybd_event(vkey, 0, 0, 0);
                keybd_event(vkey, 0, KEYEVENTF_KEYUP, 0);
                if (shift) keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0);
            }
        }
        Sleep(10);
    }
    return "{\"success\":true,\"text\":\"" + text + "\"}";
#else
    (void)text;
    return "{\"success\":false,\"error\":\"Not supported on this platform\"}";
#endif
}

std::string keyboard_key(const std::string& key) {
#if defined(_WIN32)
    unsigned short vk = key_name_to_vk(key);
    if (vk == 0) return "{\"success\":false,\"error\":\"Unknown key: " + key + "\"}";
    keybd_event(vk, 0, 0, 0);
    keybd_event(vk, 0, KEYEVENTF_KEYUP, 0);
    Sleep(100);
    return "{\"success\":true,\"key\":\"" + key + "\"}";
#else
    (void)key;
    return "{\"success\":false,\"error\":\"Not supported on this platform\"}";
#endif
}

std::string keyboard_hotkey(const std::string& keys) {
#if defined(_WIN32)
    // Parse keys separated by '+' (e.g. "ctrl+c", "shift+tab", "alt+f4")
    std::vector<std::string> parts;
    std::string current;
    for (char c : keys) {
        if (c == '+') {
            if (!current.empty()) { parts.push_back(current); current.clear(); }
        } else {
            current += c;
        }
    }
    if (!current.empty()) parts.push_back(current);
    if (parts.empty()) return "{\"success\":false,\"error\":\"No keys specified\"}";

    // Press all keys down in order
    std::vector<unsigned short> vks;
    for (const auto& p : parts) {
        unsigned short vk = key_name_to_vk(p);
        if (vk == 0) return "{\"success\":false,\"error\":\"Unknown key: " + p + "\"}";
        vks.push_back(vk);
        keybd_event(vk, 0, 0, 0);
        Sleep(20);
    }
    // Release in reverse order
    for (int i = static_cast<int>(vks.size()) - 1; i >= 0; i--) {
        keybd_event(vks[i], 0, KEYEVENTF_KEYUP, 0);
        Sleep(20);
    }
    return "{\"success\":true,\"hotkey\":\"" + keys + "\"}";
#else
    (void)keys;
    return "{\"success\":false,\"error\":\"Not supported on this platform\"}";
#endif
}

std::string keyboard_key_down(const std::string& key) {
#if defined(_WIN32)
    unsigned short vk = key_name_to_vk(key);
    if (vk == 0) return "{\"success\":false,\"error\":\"Unknown key: " + key + "\"}";
    keybd_event(vk, 0, 0, 0);
    return "{\"success\":true,\"key\":\"" + key + "\",\"action\":\"down\"}";
#else
    (void)key;
    return "{\"success\":false,\"error\":\"Not supported on this platform\"}";
#endif
}

std::string keyboard_key_up(const std::string& key) {
#if defined(_WIN32)
    unsigned short vk = key_name_to_vk(key);
    if (vk == 0) return "{\"success\":false,\"error\":\"Unknown key: " + key + "\"}";
    keybd_event(vk, 0, KEYEVENTF_KEYUP, 0);
    return "{\"success\":true,\"key\":\"" + key + "\",\"action\":\"up\"}";
#else
    (void)key;
    return "{\"success\":false,\"error\":\"Not supported on this platform\"}";
#endif
}

} // namespace computetool
