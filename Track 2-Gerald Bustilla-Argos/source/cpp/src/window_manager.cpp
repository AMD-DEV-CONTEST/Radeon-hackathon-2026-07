#include "window_manager.h"
#include "resource.h"

#include <dwmapi.h>
#pragma comment(lib, "dwmapi.lib")

WindowManager::WindowManager() {}

WindowManager::~WindowManager() {
    if (m_hwnd) {
        DestroyWindow(m_hwnd);
    }
}

bool WindowManager::Create(HINSTANCE hInstance, WNDPROC wndProc) {
    m_instance = hInstance;

    const wchar_t* className = L"ArgosCompanionWindow";

    WNDCLASSW wc = {};
    wc.lpfnWndProc = wndProc;
    wc.hInstance = hInstance;
    wc.lpszClassName = className;
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    wc.hbrBackground = nullptr; // No background brush — we paint everything
    wc.style = CS_HREDRAW | CS_VREDRAW;

    // Use a custom icon (or default for now)
    wc.hIcon = LoadIcon(nullptr, IDI_APPLICATION);

    RegisterClassW(&wc);

    // Create as a layered, tool-style window (no taskbar entry, always on top).
    // WS_EX_LAYERED enables per-pixel alpha transparency.
    // WS_EX_TOOLWINDOW prevents taskbar entry.
    // WS_EX_TOPMOST keeps it above other windows.
    // WS_EX_TRANSPARENT makes click-through (we toggle this dynamically).
    DWORD exStyle = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_APPWINDOW;
    DWORD style = WS_POPUP; // No title bar, no border

    m_hwnd = CreateWindowExW(
        exStyle,
        className,
        L"Argos",
        style,
        0, 0, 220, 220, // initial size, repositioned below
        nullptr, nullptr, hInstance, nullptr
    );

    if (!m_hwnd) {
        return false;
    }

    // Set layered window attributes: use color key for transparency.
    // Any pixel with the color key (magenta) becomes transparent.
    // We paint the background magenta and the robot on top.
    COLORREF colorKey = RGB(255, 0, 255); // magenta = transparent
    SetLayeredWindowAttributes(m_hwnd, colorKey, 255, LWA_COLORKEY);

    // Position will be set by the renderer based on robot's screen X.
    PositionAtBottomLeft();

    return true;
}

void WindowManager::Show() {
    if (m_hwnd) {
        ShowWindow(m_hwnd, SW_SHOWNOACTIVATE);
    }
}

void WindowManager::Hide() {
    if (m_hwnd) {
        ShowWindow(m_hwnd, SW_HIDE);
    }
}

void WindowManager::PositionAtBottomLeft() {
    if (!m_hwnd) return;

    // Get the work area (screen minus taskbar)
    RECT workArea;
    SystemParametersInfo(SPI_GETWORKAREA, 0, &workArea, 0);

    int windowW = 220;
    int windowH = 220;
    int x = 50; // 50px from left
    int y = workArea.bottom - windowH - 10; // just above taskbar

    SetWindowPos(m_hwnd, HWND_TOPMOST, x, y, windowW, windowH,
                 SWP_NOACTIVATE | SWP_SHOWWINDOW);
}
