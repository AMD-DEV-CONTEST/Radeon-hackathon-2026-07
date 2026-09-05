#pragma once
#include <windows.h>

// Manages the transparent, always-on-top, borderless overlay window.
class WindowManager {
public:
    WindowManager();
    ~WindowManager();

    bool Create(HINSTANCE hInstance, WNDPROC wndProc);
    void Show();
    void Hide();
    HWND GetHwnd() const { return m_hwnd; }

private:
    HWND m_hwnd = nullptr;
    HINSTANCE m_instance = nullptr;

    void PositionAtBottomLeft();
};
