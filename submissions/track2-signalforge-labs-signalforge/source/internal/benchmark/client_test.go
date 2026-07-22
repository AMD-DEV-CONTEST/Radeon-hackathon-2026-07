package benchmark

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
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
