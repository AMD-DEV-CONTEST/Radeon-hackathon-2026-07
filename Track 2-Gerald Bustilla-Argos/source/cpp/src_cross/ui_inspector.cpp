#include "ui_inspector.h"
#include "platform.h"
#include <sstream>
#include <cstring>
#include <chrono>
#include <thread>

#ifdef __ANDROID__
#include <android/log.h>
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "Argos", __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, "Argos", __VA_ARGS__)
#else
#define LOGI(...)
#define LOGE(...)
#endif

namespace argos_ui {

// ── UIElement matching helpers ──

bool UIElement::matchesText(const std::string& query) const {
    if (query.empty()) return false;
    // Case-insensitive substring search in text and contentDesc
    std::string q = query;
    for (auto& c : q) c = (char)tolower(c);

    std::string t = text;
    for (auto& c : t) c = (char)tolower(c);
    if (t.find(q) != std::string::npos) return true;

    std::string d = contentDesc;
    for (auto& c : d) c = (char)tolower(c);
    if (d.find(q) != std::string::npos) return true;

    return false;
}

bool UIElement::matchesRole(const std::string& query) const {
    if (query.empty()) return false;
    std::string q = query;
    for (auto& c : q) c = (char)tolower(c);
    std::string r = role;
    for (auto& c : r) c = (char)tolower(c);
    return r.find(q) != std::string::npos;
}

bool UIElement::matchesResourceId(const std::string& query) const {
    if (query.empty()) return false;
    return resourceId.find(query) != std::string::npos;
}

// ── InspectionSession methods ──

std::vector<int> InspectionSession::findByText(const std::string& text, bool exact) const {
    std::vector<int> results;
    for (const auto& el : elements) {
        if (exact) {
            if (el.text == text || el.contentDesc == text) {
                results.push_back(el.id);
            }
        } else {
            if (el.matchesText(text)) {
                results.push_back(el.id);
            }
        }
    }
    return results;
}

std::vector<int> InspectionSession::findByRole(const std::string& role) const {
    std::vector<int> results;
    for (const auto& el : elements) {
        if (el.matchesRole(role)) {
            results.push_back(el.id);
        }
    }
    return results;
}

std::vector<int> InspectionSession::findByResourceId(const std::string& resId) const {
    std::vector<int> results;
    for (const auto& el : elements) {
        if (el.matchesResourceId(resId)) {
            results.push_back(el.id);
        }
    }
    return results;
}

std::vector<int> InspectionSession::findClickable() const {
    std::vector<int> results;
    for (const auto& el : elements) {
        if (el.isClickable) results.push_back(el.id);
    }
    return results;
}

std::vector<int> InspectionSession::findEditable() const {
    std::vector<int> results;
    for (const auto& el : elements) {
        if (el.isEditable) results.push_back(el.id);
    }
    return results;
}

const UIElement* InspectionSession::getById(int id) const {
    if (id < 0 || id >= (int)elements.size()) return nullptr;
    return &elements[id];
}

static std::string jsonEscape(const std::string& s) {
    std::string out;
    for (char c : s) {
        switch (c) {
            case '"':  out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:   out += c;
        }
    }
    return out;
}

std::string InspectionSession::toJson(bool compact) const {
    std::ostringstream ss;
    ss << "{\"app\":\"" << jsonEscape(appName) << "\",\"package\":\"" << jsonEscape(appPackage)
       << "\",\"element_count\":" << (int)elements.size()
       << ",\"elements\":[";

    for (size_t i = 0; i < elements.size(); i++) {
        const auto& el = elements[i];
        if (i > 0) ss << ",";
        if (!compact) ss << "\n  ";

        ss << "{\"id\":" << el.id;
        if (!el.text.empty()) ss << ",\"text\":\"" << jsonEscape(el.text) << "\"";
        if (!el.contentDesc.empty()) ss << ",\"desc\":\"" << jsonEscape(el.contentDesc) << "\"";
        if (!el.role.empty()) ss << ",\"role\":\"" << jsonEscape(el.role) << "\"";
        if (!el.resourceId.empty()) ss << ",\"resId\":\"" << jsonEscape(el.resourceId) << "\"";
        if (!el.className.empty() && compact) ss << ",\"class\":\"" << jsonEscape(el.className) << "\"";
        ss << ",\"clickable\":" << (el.isClickable ? "true" : "false");
        ss << ",\"longClickable\":" << (el.isLongClickable ? "true" : "false");
        ss << ",\"editable\":" << (el.isEditable ? "true" : "false");
        ss << ",\"focused\":" << (el.isFocused ? "true" : "false");
        if (el.isScrollable) ss << ",\"scrollable\":true";
        if (el.isChecked) ss << ",\"checked\":true";
        ss << ",\"bounds\":{\"x\":" << el.x << ",\"y\":" << el.y
           << ",\"w\":" << el.width << ",\"h\":" << el.height << "}";
        if (!el.childIds.empty()) {
            ss << ",\"children\":[";
            for (size_t j = 0; j < el.childIds.size(); j++) {
                if (j > 0) ss << ",";
                ss << el.childIds[j];
            }
            ss << "]";
        }
        ss << "}";
    }
    if (!compact) ss << "\n";
    ss << "]}";
    return ss.str();
}

std::string InspectionSession::toJsonFiltered(const std::vector<int>& ids) const {
    std::ostringstream ss;
    ss << "{\"app\":\"" << jsonEscape(appName) << "\",\"matched\":" << (int)ids.size() << ",\"elements\":[";
    for (size_t i = 0; i < ids.size(); i++) {
        const UIElement* el = getById(ids[i]);
        if (!el) continue;
        if (i > 0) ss << ",";
        ss << "{\"id\":" << el->id;
        if (!el->text.empty()) ss << ",\"text\":\"" << jsonEscape(el->text) << "\"";
        if (!el->contentDesc.empty()) ss << ",\"desc\":\"" << jsonEscape(el->contentDesc) << "\"";
        if (!el->role.empty()) ss << ",\"role\":\"" << jsonEscape(el->role) << "\"";
        if (!el->resourceId.empty()) ss << ",\"resId\":\"" << jsonEscape(el->resourceId) << "\"";
        ss << ",\"clickable\":" << (el->isClickable ? "true" : "false");
        ss << ",\"editable\":" << (el->isEditable ? "true" : "false");
        ss << ",\"bounds\":{\"x\":" << el->x << ",\"y\":" << el->y
           << ",\"w\":" << el->width << ",\"h\":" << el->height << "}";
        ss << "}";
    }
    ss << "]}";
    return ss.str();
}

// ── Platform interface stubs (non-Android) ──
// On Android, these are implemented in platform_android.cpp via JNI.
// We provide weak defaults here so the code compiles on all platforms.

#ifdef __ANDROID__

// Android: delegate to argos:: platform functions (implemented in platform_android.cpp via JNI)

InspectionSession inspectUI(int maxDepth) {
    std::string json = argos::getUITree(maxDepth);
    InspectionSession session;
    session.timestamp = argos::getTimeMs();

    // Parse JSON to extract app name and elements
    // Simple JSON parsing for our known format
    size_t appPos = json.find("\"app\":\"");
    if (appPos != std::string::npos) {
        appPos += 7;
        size_t end = json.find("\"", appPos);
        if (end != std::string::npos) {
            session.appName = json.substr(appPos, end - appPos);
        }
    }

    size_t pkgPos = json.find("\"package\":\"");
    if (pkgPos != std::string::npos) {
        pkgPos += 11;
        size_t end = json.find("\"", pkgPos);
        if (end != std::string::npos) {
            session.appPackage = json.substr(pkgPos, end - pkgPos);
        }
    }

    // Parse elements — find all {"id":N,...} objects
    // We do a simple pass to extract element IDs and text for convenience methods
    size_t pos = 0;
    while ((pos = json.find("\"id\":", pos)) != std::string::npos) {
        pos += 5;
        int id = 0;
        while (pos < json.size() && json[pos] >= '0' && json[pos] <= '9') {
            id = id * 10 + (json[pos] - '0');
            pos++;
        }

        UIElement el;
        el.id = id;

        // Extract text
        size_t textPos = json.find("\"text\":\"", pos);
        size_t nextId = json.find("\"id\":", pos);
        if (textPos != std::string::npos && (nextId == std::string::npos || textPos < nextId)) {
            textPos += 8;
            size_t end = textPos;
            while (end < json.size() && json[end] != '"') {
                if (json[end] == '\\') end++; // skip escaped char
                end++;
            }
            el.text = json.substr(textPos, end - textPos);
        }

        // Extract desc
        size_t descPos = json.find("\"desc\":\"", pos);
        if (descPos != std::string::npos && (nextId == std::string::npos || descPos < nextId)) {
            descPos += 8;
            size_t end = descPos;
            while (end < json.size() && json[end] != '"') {
                if (json[end] == '\\') end++;
                end++;
            }
            el.contentDesc = json.substr(descPos, end - descPos);
        }

        // Extract role
        size_t rolePos = json.find("\"role\":\"", pos);
        if (rolePos != std::string::npos && (nextId == std::string::npos || rolePos < nextId)) {
            rolePos += 8;
            size_t end = json.find("\"", rolePos);
            if (end != std::string::npos) {
                el.role = json.substr(rolePos, end - rolePos);
            }
        }

        // Extract clickable
        size_t clickPos = json.find("\"clickable\":true", pos);
        if (clickPos != std::string::npos && (nextId == std::string::npos || clickPos < nextId)) {
            el.isClickable = true;
        }

        // Extract editable
        size_t editPos = json.find("\"editable\":true", pos);
        if (editPos != std::string::npos && (nextId == std::string::npos || editPos < nextId)) {
            el.isEditable = true;
        }

        session.elements.push_back(el);
    }

    return session;
}

std::string performAction(int elementId, const std::string& action, const std::string& extra) {
    return argos::performUIAction(elementId, action, extra);
}

std::string takeScreenshot(const std::string& savePath) {
    return argos::takeScreenshot(savePath);
}

std::string getNotifications() {
    return argos::getNotificationsList();
}

std::string replyToNotification(int notificationIndex, const std::string& message) {
    return argos::replyToNotificationByIdx(notificationIndex, message);
}

#else // non-Android stubs

InspectionSession inspectUI(int maxDepth) {
    InspectionSession s;
    s.appName = "Unknown";
    return s;
}

std::string performAction(int elementId, const std::string& action, const std::string& extra) {
    return "{\"error\":\"UI inspection not available on this platform\"}";
}

std::string takeScreenshot(const std::string& savePath) {
    return "{\"error\":\"Screenshot not available on this platform\"}";
}

std::string getNotifications() {
    return "{\"error\":\"Notifications not available on this platform\"}";
}

std::string replyToNotification(int notificationIndex, const std::string& message) {
    return "{\"error\":\"Notification reply not available on this platform\"}";
}

#endif // __ANDROID__

// ── Convenience methods (cross-platform, use inspectUI + performAction) ──

std::string clickElementByText(const std::string& text, bool longClick) {
    InspectionSession session = inspectUI(20);
    auto matches = session.findByText(text);
    if (matches.empty()) {
        // Try partial match with shorter text
        matches = session.findByText(text, false);
    }
    if (matches.empty()) {
        return "{\"error\":\"No element found with text: " + text + "\"}";
    }

    // Prefer clickable elements
    int bestId = matches[0];
    for (int id : matches) {
        const UIElement* el = session.getById(id);
        if (el && el->isClickable) {
            bestId = id;
            break;
        }
    }

    std::string action = longClick ? "long_click" : "click";
    std::string result = performAction(bestId, action);
    std::this_thread::sleep_for(std::chrono::milliseconds(800));
    return result;
}

std::string typeIntoElement(int elementId, const std::string& text) {
    return performAction(elementId, "set_text", text);
}

std::string typeIntoFieldWithHint(const std::string& hintText, const std::string& text) {
    InspectionSession session = inspectUI(20);
    // Find editable elements
    auto editables = session.findEditable();
    if (editables.empty()) {
        return "{\"error\":\"No editable field found on screen\"}";
    }

    // Try to find one with matching hint text
    for (int id : editables) {
        const UIElement* el = session.getById(id);
        if (el && (el->matchesText(hintText) || el->text.empty())) {
            // Focus the field first, then type
            performAction(id, "focus");
            std::this_thread::sleep_for(std::chrono::milliseconds(300));
            return performAction(id, "set_text", text);
        }
    }

    // Fallback: use first editable field
    int firstId = editables[0];
    performAction(firstId, "focus");
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    return performAction(firstId, "set_text", text);
}

// ── Multi-step action sequence ──

std::string executeActionSequence(const std::vector<ActionStep>& steps) {
    std::ostringstream results;
    results << "{\"total_steps\":" << (int)steps.size() << ",\"results\":[";

    for (size_t i = 0; i < steps.size(); i++) {
        const auto& step = steps[i];
        if (i > 0) results << ",";

        results << "{\"step\":" << (int)(i + 1) << ",\"action\":\"" << step.action << "\"";

        std::string stepResult;

        if (step.action == "click" || step.action == "long_click") {
            if (step.elementId >= 0) {
                stepResult = performAction(step.elementId, step.action);
            } else if (!step.text.empty()) {
                stepResult = clickElementByText(step.text, step.action == "long_click");
            } else {
                stepResult = "{\"error\":\"click needs text or elementId\"}";
            }
        } else if (step.action == "type") {
            if (step.elementId >= 0) {
                stepResult = typeIntoElement(step.elementId, step.text);
            } else if (!step.text.empty()) {
                stepResult = typeIntoFieldWithHint("", step.text);
            } else {
                stepResult = "{\"error\":\"type needs text\"}";
            }
        } else if (step.action == "wait") {
            int ms = step.waitMs > 0 ? step.waitMs : 1000;
            std::this_thread::sleep_for(std::chrono::milliseconds(ms));
            stepResult = "{\"status\":\"waited " + std::to_string(ms) + "ms\"}";
        } else if (step.action == "scroll") {
            argos::scrollScreen(step.scrollDir);
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
            stepResult = std::string("{\"status\":\"scrolled ") + (step.scrollDir == 0 ? "up" : "down") + "\"}";
        } else if (step.action == "inspect") {
            InspectionSession session = inspectUI(20);
            stepResult = session.toJson(true);
        } else {
            stepResult = "{\"error\":\"Unknown action: " + step.action + "\"}";
        }

        results << ",\"result\":" << stepResult;

        // Wait after step
        if (step.waitMs > 0 && step.action != "wait") {
            std::this_thread::sleep_for(std::chrono::milliseconds(step.waitMs));
        }

        results << "}";
    }

    results << "],\"status\":\"complete\"}";
    return results.str();
}

// Parse action sequence from simple JSON
// Expected format: [{"action":"click","text":"Reply"},{"action":"type","text":"Hello!"},{"action":"click","text":"Send"}]
std::vector<ActionStep> parseActionSequence(const std::string& json) {
    std::vector<ActionStep> steps;
    size_t pos = 0;

    // Simple JSON parser for array of objects
    while ((pos = json.find('{', pos)) != std::string::npos) {
        size_t end = json.find('}', pos);
        if (end == std::string::npos) break;

        std::string obj = json.substr(pos, end - pos + 1);
        ActionStep step;

        // Extract action
        size_t aPos = obj.find("\"action\"");
        if (aPos != std::string::npos) {
            size_t s = obj.find('"', aPos + 8) + 1;
            size_t e = obj.find('"', s);
            if (e != std::string::npos) step.action = obj.substr(s, e - s);
        }

        // Extract text
        size_t tPos = obj.find("\"text\"");
        if (tPos != std::string::npos) {
            size_t s = obj.find('"', tPos + 6) + 1;
            size_t e = s;
            while (e < obj.size()) {
                if (obj[e] == '\\') { e += 2; continue; }
                if (obj[e] == '"') break;
                e++;
            }
            if (e < obj.size()) step.text = obj.substr(s, e - s);
        }

        // Extract role
        size_t rPos = obj.find("\"role\"");
        if (rPos != std::string::npos) {
            size_t s = obj.find('"', rPos + 6) + 1;
            size_t e = obj.find('"', s);
            if (e != std::string::npos) step.role = obj.substr(s, e - s);
        }

        // Extract resId
        size_t idPos = obj.find("\"resId\"");
        if (idPos != std::string::npos) {
            size_t s = obj.find('"', idPos + 7) + 1;
            size_t e = obj.find('"', s);
            if (e != std::string::npos) step.resId = obj.substr(s, e - s);
        }

        // Extract elementId
        size_t ePos = obj.find("\"elementId\"");
        if (ePos != std::string::npos) {
            size_t s = obj.find(':', ePos) + 1;
            step.elementId = std::atoi(obj.c_str() + s);
        }

        // Extract waitMs
        size_t wPos = obj.find("\"waitMs\"");
        if (wPos != std::string::npos) {
            size_t s = obj.find(':', wPos) + 1;
            step.waitMs = std::atoi(obj.c_str() + s);
        }

        // Extract scrollDir
        size_t sdPos = obj.find("\"scrollDir\"");
        if (sdPos != std::string::npos) {
            size_t s = obj.find(':', sdPos) + 1;
            step.scrollDir = std::atoi(obj.c_str() + s);
        }

        steps.push_back(step);
        pos = end + 1;
    }

    return steps;
}

} // namespace argos_ui
