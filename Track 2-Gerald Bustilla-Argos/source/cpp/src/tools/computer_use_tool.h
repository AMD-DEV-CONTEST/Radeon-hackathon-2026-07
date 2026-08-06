#pragma once

#include <string>

// ===== Computer Use Tool =====
// Direct mouse and keyboard control via Win32 API.
// Reusable across projects — no dependency on Argos-specific code.
//
// Platform: Windows (Win32 API). Stubs return false on other platforms.

namespace computetool {

// ===== Mouse API =====

// Left-click at screen coordinates (x, y)
std::string mouse_click(int x, int y);

// Right-click at screen coordinates (x, y)
std::string mouse_right_click(int x, int y);

// Double-click at screen coordinates (x, y)
std::string mouse_double_click(int x, int y);

// Move mouse cursor to screen coordinates (x, y) without clicking
std::string mouse_move(int x, int y);

// Get current mouse cursor position
std::string mouse_position();

// Scroll the mouse wheel (positive = up, negative = down)
std::string mouse_scroll(int delta);

// ===== Keyboard API =====

// Type a string of text as if pressing each key
std::string keyboard_type(const std::string& text);

// Press a single key by name (enter, tab, escape, f5, etc.)
std::string keyboard_key(const std::string& key);

// Press a key combination / hotkey (e.g. "ctrl+c", "shift+tab", "alt+f4")
std::string keyboard_hotkey(const std::string& keys);

// Hold down a key (useful for modifier keys)
std::string keyboard_key_down(const std::string& key);

// Release a held key
std::string keyboard_key_up(const std::string& key);

// ===== Utility =====

// Map a key name string to a Win32 virtual key code
// Returns 0 if the key name is not recognized
unsigned short key_name_to_vk(const std::string& key);

} // namespace computetool
