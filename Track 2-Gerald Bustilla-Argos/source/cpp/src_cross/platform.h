#pragma once
#include <string>
#include <functional>

// Platform abstraction layer for Argos cross-platform support.
// Each platform (Windows, Android, iOS, macOS, Linux) implements these.

namespace argos {

// HTTP request (POST with JSON body). Returns response body or empty on error.
std::string httpPost(const std::string& url, const std::string& headers, const std::string& body);

// HTTP streaming request. Calls callback with each chunk. Returns full response.
std::string httpPostStream(const std::string& url, const std::string& headers,
                           const std::string& body,
                           std::function<bool(const std::string& chunk)> callback);

// Get app data directory for persistent storage
std::string getAppDataDir();

// Set app data directory (called by platform init)
void setAppDataDir(const char* dir);

// Log a message (platform-specific: OutputDebugString, __android_log_print, etc.)
void log(const char* message);

// Set JNI environment for HTTP requests (Android only — uses Java HttpURLConnection for HTTPS)
void setJniForHttp(void* jvm, void* service);

// ── Browser / Screen interaction (platform-specific) ──
// On Android these use Accessibility Service via JNI.
// On other platforms they may be stubs.

// Open a URL in the device's default browser
std::string openUrl(const std::string& url);

// Get all text content currently visible on screen (any app, including browser)
std::string getScreenText();

// Get the package name of the currently focused app
std::string getActiveApp();

// Click on the first element containing the given text
std::string clickText(const std::string& text);

// Type text into the currently focused input field
std::string typeText(const std::string& text);

// Scroll the current screen: direction 0=up, 1=down
std::string scrollScreen(int direction);

// ── UI Inspection & Automation (Android Accessibility Service) ──

// Get the full UI element tree as JSON (from Accessibility Service)
// maxDepth limits traversal depth (-1 = unlimited)
std::string getUITree(int maxDepth);

// Perform an accessibility action on a node by ID
// action: "click", "long_click", "focus", "set_text", "scroll_forward", "scroll_backward", "select", "expand", "collapse"
// extra: optional text for set_text action
std::string performUIAction(int elementId, const std::string& action, const std::string& extra);

// Take a screenshot and return base64-encoded JPEG (or save to file)
std::string takeScreenshot(const std::string& savePath);

// Get active notifications as JSON
std::string getNotificationsList();

// Reply to a notification by index
std::string replyToNotificationByIdx(int index, const std::string& message);

// ── Gesture-based UI automation (dispatchGesture) ──

// Tap (click) at a screen coordinate
std::string clickAtPoint(int x, int y);

// Long press at a screen coordinate
std::string longPressAtPoint(int x, int y);

// Swipe from one point to another
std::string swipeGesture(int x1, int y1, int x2, int y2, int durationMs);

// Swipe up (scroll down content)
std::string swipeUp();

// Swipe down (scroll up content)
std::string swipeDown();

// Smart click at point — tries accessibility action first, falls back to gesture
std::string smartClick(int x, int y);

// Smart long press at point — tries accessibility action first, falls back to gesture
std::string smartLongPress(int x, int y);

// Get all clickable/interactive elements with their bounds and center points
std::string getClickableElements();

// Get screen size as JSON {"width":W,"height":H}
std::string getScreenSize();

// ── Voice / Audio (whisper.cpp + native TTS) ──

// Record audio from microphone (Android: AudioRecord via JNI, Windows: WaveIn)
// Returns raw 16-bit PCM data as a string (bytes)
std::string recordAudioJava(int durationSeconds);

// Text-to-Speech (Android: TextToSpeech, Windows: SAPI)
std::string ttsSpeakJava(const std::string& text);
std::string ttsStopJava();
std::string ttsIsSpeakingJava();

// Get current time in milliseconds
int64_t getTimeMs();

} // namespace argos
