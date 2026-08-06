#pragma once
#include <string>
#include <vector>
#include <functional>

// Cross-platform UI inspection and automation for Argos.
// On Android: uses Accessibility Service via JNI to inspect and interact with any app's UI.
// On other platforms: stubs return error JSON.

namespace argos_ui {

// ── UI Element Tree ──
// Represents a node in the accessibility tree (Android AccessibilityNodeInfo equivalent)

struct UIElement {
    int id = -1;              // Unique node ID within this inspection session
    std::string text;         // Visible text
    std::string contentDesc;  // Content description (accessibility label)
    std::string className;    // Widget class (e.g. android.widget.Button)
    std::string packageName;  // App package
    std::string resourceId;   // View resource ID (e.g. com.whatsapp:id/send_button)
    std::string role;         // Simplified role: button, text, input, image, list, container, checkbox, etc.

    bool isClickable = false;
    bool isLongClickable = false;
    bool isScrollable = false;
    bool isEditable = false;
    bool isFocused = false;
    bool isChecked = false;
    bool isEnabled = true;

    int x = 0, y = 0;         // Screen coordinates (top-left of bounds)
    int width = 0, height = 0;

    int parentId = -1;
    std::vector<int> childIds;

    // Convenience: does this element match a search query?
    bool matchesText(const std::string& query) const;
    bool matchesRole(const std::string& query) const;
    bool matchesResourceId(const std::string& query) const;
};

// ── Inspection Session ──
// A session captures the current UI tree and allows actions on elements by ID.

struct InspectionSession {
    std::vector<UIElement> elements;
    std::string appPackage;
    std::string appName;
    int64_t timestamp = 0;

    // Find elements by various criteria
    std::vector<int> findByText(const std::string& text, bool exact = false) const;
    std::vector<int> findByRole(const std::string& role) const;
    std::vector<int> findByResourceId(const std::string& resId) const;
    std::vector<int> findClickable() const;
    std::vector<int> findEditable() const;

    // Get element by ID
    const UIElement* getById(int id) const;

    // Serialize to JSON for AI consumption
    std::string toJson(bool compact = false) const;

    // Serialize only matching elements (filtered view)
    std::string toJsonFiltered(const std::vector<int>& ids) const;
};

// ── Platform interface (implemented per-platform) ──

// Capture the current UI tree into a session
// maxDepth limits tree traversal (0 = root only, -1 = unlimited)
InspectionSession inspectUI(int maxDepth = -1);

// Perform an action on a UI element by its ID from the last inspection
// action: "click", "long_click", "focus", "select", "scroll_forward", "scroll_backward",
//         "set_text", "clear_selection", "select", "collapse", "expand"
std::string performAction(int elementId, const std::string& action, const std::string& extra = "");

// Convenience: click element by text (finds and clicks in one call)
std::string clickElementByText(const std::string& text, bool longClick = false);

// Convenience: type text into a specific element by ID
std::string typeIntoElement(int elementId, const std::string& text);

// Convenience: find and type into an editable field containing hint text
std::string typeIntoFieldWithHint(const std::string& hintText, const std::string& text);

// ── Screenshot ──
// Take a screenshot and save to path. Returns JSON with path and dimensions.
// On Android, uses MediaProjection or PixelCopy. May require additional permissions.
std::string takeScreenshot(const std::string& savePath = "");

// ── Notification helpers ──
// Get active notifications (Android: NotificationListenerService or Accessibility)
std::string getNotifications();

// Reply to a specific notification (Android: Notification.Action.REPLY)
std::string replyToNotification(int notificationIndex, const std::string& message);

// ── Multi-step action sequence ──
// Execute a sequence of actions atomically. Each step is a JSON object:
// {"action":"click","text":"Reply"} or {"action":"type","text":"Hello!"} or {"action":"wait","ms":1000}
struct ActionStep {
    std::string action;   // click, long_click, type, wait, scroll, inspect
    std::string text;     // text to find (for click) or type (for type)
    std::string role;     // role filter (for click)
    std::string resId;    // resource ID filter (for click)
    int elementId = -1;   // specific element ID (alternative to text search)
    int waitMs = 500;     // wait after this step (default 500ms)
    int scrollDir = 1;    // 0=up, 1=down (for scroll action)
};

std::string executeActionSequence(const std::vector<ActionStep>& steps);

// Parse action sequence from JSON string (for AI tool dispatch)
std::vector<ActionStep> parseActionSequence(const std::string& json);

} // namespace argos_ui
