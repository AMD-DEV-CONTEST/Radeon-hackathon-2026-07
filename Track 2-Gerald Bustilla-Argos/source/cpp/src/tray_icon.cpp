#include "tray_icon.h"

#define WM_TRAYICON (WM_USER + 1)

TrayIcon::TrayIcon() {}

TrayIcon::~TrayIcon() {
    if (m_nid.hWnd) {
        Shell_NotifyIconW(NIM_DELETE, &m_nid);
    }
    if (m_menu) {
        DestroyMenu(m_menu);
    }
}

void TrayIcon::Initialize(HINSTANCE hInstance, HWND hwnd) {
    m_hwnd = hwnd;

    // Create context menu
    m_menu = CreatePopupMenu();
    AppendMenuW(m_menu, MF_STRING, ID_TRAY_SHOW, L"Show Argos");
    AppendMenuW(m_menu, MF_STRING, ID_TRAY_HIDE, L"Hide Argos");
    AppendMenuW(m_menu, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(m_menu, MF_STRING, ID_TRAY_QUIT, L"Quit");

    // Add tray icon
    m_nid.cbSize = sizeof(NOTIFYICONDATAW);
    m_nid.hWnd = hwnd;
    m_nid.uID = 1;
    m_nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP;
    m_nid.uCallbackMessage = WM_TRAYICON;
    m_nid.hIcon = LoadIcon(nullptr, IDI_APPLICATION); // default icon for now
    wcscpy_s(m_nid.szTip, L"Argos — Faithful AI Companion");

    Shell_NotifyIconW(NIM_ADD, &m_nid);
}

void TrayIcon::ShowContextMenu(HWND hwnd) {
    if (!m_menu) return;

    POINT pt;
    GetCursorPos(&pt);

    // Required for tray menus to work properly
    SetForegroundWindow(hwnd);

    TrackPopupMenu(m_menu, TPM_RIGHTALIGN | TPM_BOTTOMALIGN | TPM_RIGHTBUTTON,
                   pt.x, pt.y, 0, hwnd, nullptr);
}
