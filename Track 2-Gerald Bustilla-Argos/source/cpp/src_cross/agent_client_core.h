#pragma once
#include <string>
#include <vector>
#include <functional>
#include <atomic>
#include "platform.h"

// Cross-platform chat message and agent client
// This is a platform-agnostic version of AgentClient that uses the platform abstraction.

struct ChatMessageCore {
    std::string role;    // "system", "user", or "assistant"
    std::string content;
};

using StreamCallbackCore = std::function<bool(const std::string& delta)>;
using ThoughtsCallbackCore = std::function<void(const std::string& thoughts)>;
using ToolStatusCallbackCore = std::function<void(const std::string& status)>;

class AgentClientCore {
public:
    AgentClientCore();
    ~AgentClientCore();

    void setServerUrl(const std::string& url);
    void setApiKey(const std::string& key);
    void setModel(const std::string& model);

    std::string chat(const std::string& userMessage);
    std::string chatStreaming(const std::string& userMessage, StreamCallbackCore callback,
                              ThoughtsCallbackCore thoughtsCallback = nullptr,
                              ToolStatusCallbackCore toolStatusCallback = nullptr);

    void clearHistory();
    std::atomic<bool> m_abort{false};

private:
    std::string m_serverUrl = "https://developer.amd.com.cn/radeon/api/v1";
    std::string m_apiKey = "";  // Set via config file, env var, or settings UI
    std::string m_model = "DeepSeek-V4-Flash";
    std::string m_fallbackModel = "MiniCPM5-1B";
    std::string m_systemPrompt;
    std::vector<ChatMessageCore> m_history;

    void initSystemPrompt();
    std::string buildJsonBody(const std::vector<ChatMessageCore>& messages, bool stream);
    std::string parseSSEChunk(const std::string& chunk, std::string* thoughts = nullptr);
    bool hasToolTags(const std::string& response);
    std::string executeTools(const std::string& response, ToolStatusCallbackCore toolStatusCallback = nullptr);
    std::string stripToolTags(const std::string& response);
    std::string chatWithMessages(const std::vector<ChatMessageCore>& messages);
    std::string chatWithMessagesStreaming(const std::vector<ChatMessageCore>& messages,
                                           StreamCallbackCore callback,
                                           ThoughtsCallbackCore thoughtsCallback = nullptr,
                                           ToolStatusCallbackCore toolStatusCallback = nullptr);
};
