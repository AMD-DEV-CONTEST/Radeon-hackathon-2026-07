#pragma once
#include <string>
#include <vector>
#include <functional>
#include <atomic>

// Chat message entry for multi-turn conversation context
struct ChatMessage {
    std::wstring role;    // "system", "user", or "assistant"
    std::wstring content;
};

// Streaming callback: called with each text delta as it arrives
// Returns false to abort the stream
using StreamCallback = std::function<bool(const std::wstring& delta)>;

// HTTP client that talks to any OpenAI-compatible API using WinHTTP.
// Named Argos — the faithful dog of Odysseus. Loyal, vigilant, always ready.
class AgentClient {
public:
    AgentClient();
    ~AgentClient();

    void SetServerUrl(const std::wstring& url);
    void SetApiKey(const std::wstring& key);
    void SetModel(const std::wstring& model);
    void SetFallbackModel(const std::wstring& model);
    void SetVisionModel(const std::wstring& model);

    // Send a chat completion request with full conversation context.
    // Returns the assistant's response text.
    std::wstring Chat(const std::wstring& userMessage);

    // Streaming chat: calls callback with each text delta in real-time.
    // Returns the full accumulated response.
    std::wstring ChatStreaming(const std::wstring& userMessage, StreamCallback callback);

    // Send a chat completion with explicit message list.
    std::wstring ChatWithMessages(const std::vector<ChatMessage>& messages);

    // Streaming version of ChatWithMessages
    std::wstring ChatWithMessagesStreaming(const std::vector<ChatMessage>& messages, StreamCallback callback);

    // Proactive chat: one-off message based on screen context.
    // Does NOT add to conversation history. Returns a short message.
    std::wstring ProactiveChat(const std::wstring& screenContext);

    // Health check — returns true if the server is reachable.
    bool IsServerAlive();

    // Clear conversation history
    void ClearHistory();

    // Get conversation history
    const std::vector<ChatMessage>& GetHistory() const { return m_history; }

    // Abort flag — set to true to cancel an in-progress streaming request
    std::atomic<bool> m_abort{false};

    // Tool execution flag — true while tools are being executed
    std::atomic<bool> m_executingTools{false};

private:
    std::wstring m_serverUrl = L"https://developer.amd.com.cn/radeon/api/v1";
    std::wstring m_apiKey = L"";  // Set via config file, env var, or settings UI
    std::wstring m_model = L"DeepSeek-V4-Flash";
    std::wstring m_fallbackModel = L"MiniCPM5-1B";
    std::wstring m_visionModel = L"Qwen3.6-35B-A3B"; // Used for OCR/vision tasks

    // Conversation history for multi-turn context
    std::vector<ChatMessage> m_history;

    // System prompt defining Argos identity and tool capabilities
    std::wstring m_systemPrompt;

    // Build the system prompt with Argos identity and available tools
    void InitSystemPrompt();

    // Process tool commands embedded in AI response (e.g. [TOOL: ...])
    // Executes tools and returns a combined result string.
    std::wstring ExecuteTools(const std::wstring& response);

    // Strip [TOOL:...] and [Tool result:...] tags from text for clean display
    std::wstring StripToolTags(const std::wstring& response);

    // Check if response contains any [TOOL:...] tags
    bool HasToolTags(const std::wstring& response);

    // Parse a single SSE data line and extract content delta
    std::wstring ParseSSEChunk(const std::string& chunk);

    // Send a chat completion using a specific model (for vision/OCR tasks)
    std::wstring ChatWithModel(const std::vector<ChatMessage>& messages, const std::wstring& model);

    // Internal: streaming chat with a specific model
    std::wstring ChatWithMessagesStreamingModel(const std::vector<ChatMessage>& messages, StreamCallback callback, const std::wstring& model);

    // Check if a tool requires vision/multimodal model
    bool IsVisionTool(const std::wstring& toolName);
};
