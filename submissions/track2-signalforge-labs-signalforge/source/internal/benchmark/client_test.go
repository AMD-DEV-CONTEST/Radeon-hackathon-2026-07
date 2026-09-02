package benchmark

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestCompleteMeasuresStreamAndUsage(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/v1/chat/completions" {
			t.Fatalf("unexpected path %q", request.URL.Path)
		}
		if !request.Close {
			t.Fatal("local inference request must not reuse an idle connection")
		}
		response.Header().Set("Content-Type", "text/event-stream")
		flusher := response.(http.Flusher)
		fmt.Fprintln(response, `data: {"choices":[{"delta":{"content":"Revenue "},"finish_reason":""}],"usage":{}}`)
		flusher.Flush()
		fmt.Fprintln(response, `data: {"choices":[{"delta":{"content":"grew."},"finish_reason":"stop"}],"usage":{}}`)
		fmt.Fprintln(response, `data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":3,"total_tokens":15}}`)
		fmt.Fprintln(response, "data: [DONE]")
	}))
	defer server.Close()

	completion, err := (Client{BaseURL: server.URL + "/v1"}).Complete(context.Background(), Request{
		Model: "test-model", Messages: []Message{{Role: "user", Content: "Test"}}, MaxTokens: 8,
	})
	if err != nil {
		t.Fatal(err)
	}
	if completion.Answer != "Revenue grew." || completion.FinishReason != "stop" || completion.Usage.TotalTokens != 15 {
		t.Fatalf("unexpected completion: %+v", completion)
	}
	if completion.TTFT <= 0 || completion.Duration <= 0 {
		t.Fatalf("missing timing data: %+v", completion)
	}
}

func TestCompleteAuthenticatesRemoteCompatibleEndpointWithoutClosingConnection(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if got := request.Header.Get("Authorization"); got != "Bearer test-secret" {
			t.Fatalf("unexpected authorization header %q", got)
		}
		if request.Close {
			t.Fatal("remote-compatible client should preserve HTTP connections")
		}
		var payload map[string]any
		if err := json.NewDecoder(request.Body).Decode(&payload); err != nil {
			t.Fatal(err)
		}
		if _, present := payload["response_format"]; present {
			t.Fatal("remote-compatible request must omit unsupported response_format")
		}
		messages, ok := payload["messages"].([]any)
		if !ok || len(messages) == 0 {
			t.Fatal("remote-compatible request is missing messages")
		}
		system, ok := messages[0].(map[string]any)
		if !ok || system["role"] != "system" ||
			!strings.Contains(system["content"].(string), `"status"`) {
			t.Fatal("remote-compatible request must embed the response contract in the system prompt")
		}
		response.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprintln(response, `data: {"choices":[{"delta":{"content":"{\"ok\":true}"},"finish_reason":"stop"}],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}}`)
		fmt.Fprintln(response, "data: [DONE]")
	}))
	defer server.Close()

	completion, err := (Client{
		BaseURL: server.URL, APIKey: "test-secret", ReuseConnections: true,
		EmbedResponseFormatInPrompt: true,
	}).Complete(context.Background(), Request{
		Model: "test-model", Messages: []Message{
			{Role: "system", Content: "Return JSON."},
			{Role: "user", Content: "Test"},
		},
		MaxTokens: 8,
		ResponseFormat: map[string]any{
			"type": "json_schema",
			"json_schema": map[string]any{
				"schema": map[string]any{
					"type": "object",
					"properties": map[string]any{
						"status": map[string]any{"type": "string"},
					},
				},
			},
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if completion.Answer != `{"ok":true}` || completion.Usage.TotalTokens != 6 {
		t.Fatalf("unexpected completion: %+v", completion)
	}
}

func TestCompleteSerializesModelSpecificThinkingControl(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		var payload map[string]any
		if err := json.NewDecoder(request.Body).Decode(&payload); err != nil {
			t.Fatal(err)
		}
		thinking, ok := payload["thinking"].(map[string]any)
		if !ok || thinking["type"] != "disabled" {
			t.Fatalf("unexpected thinking control: %#v", payload["thinking"])
		}
		if _, present := payload["chat_template_kwargs"]; present {
			t.Fatal("DeepSeek request must not include Qwen chat-template controls")
		}
		response.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprintln(response, `data: {"choices":[{"delta":{"content":"{\"ok\":true}"},"finish_reason":"stop"}],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}}`)
		fmt.Fprintln(response, "data: [DONE]")
	}))
	defer server.Close()

	_, err := (Client{BaseURL: server.URL}).Complete(context.Background(), Request{
		Model: "DeepSeek-V4-Flash", Messages: []Message{{Role: "user", Content: "Test"}}, MaxTokens: 8,
		Thinking: map[string]any{"type": "disabled"},
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestCompleteRejectsEmptyStream(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		response.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprintln(response, "data: [DONE]")
	}))
	defer server.Close()

	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	_, err := (Client{BaseURL: server.URL}).Complete(ctx, Request{
		Model: "test-model", Messages: []Message{{Role: "user", Content: "Test"}}, MaxTokens: 8,
	})
	if err == nil {
		t.Fatal("expected empty stream failure")
	}
}

func TestCompleteReassemblesStreamedToolArguments(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		response.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprintln(response, `data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"calculate_dcf","arguments":"{\"wacc\":"}}]},"finish_reason":""}],"usage":{}}`)
		fmt.Fprintln(response, `data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\"0.09\"}"}}]},"finish_reason":"tool_calls"}],"usage":{}}`)
		fmt.Fprintln(response, "data: [DONE]")
	}))
	defer server.Close()

	completion, err := (Client{BaseURL: server.URL}).Complete(context.Background(), Request{
		Model: "test-model", Messages: []Message{{Role: "user", Content: "Test"}}, MaxTokens: 8,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(completion.ToolCalls) != 1 || completion.ToolCalls[0].Name != "calculate_dcf" ||
		completion.ToolCalls[0].Arguments != `{"wacc":"0.09"}` {
		t.Fatalf("unexpected tool calls: %+v", completion.ToolCalls)
	}
}
