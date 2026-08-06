#pragma once
#include <windows.h>
#include "resource.h"

// System tray icon with context menu (Show/Hide/Quit).
class TrayIcon {
public:
    TrayIcon();
    ~TrayIcon();

    void Initialize(HINSTANCE hInstance, HWND hwnd);
    void ShowContextMenu(HWND hwnd);

private:
    HWND m_hwnd = nullptr;
    HMENU m_menu = nullptr;
    NOTIFYICONDATAW m_nid = {};
};
