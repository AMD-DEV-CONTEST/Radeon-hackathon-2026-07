package benchmark

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type Client struct {
	BaseURL    string
	HTTPClient *http.Client
}

type Request struct {
	Model              string         `json:"model"`
	Messages           []Message      `json:"messages"`
	MaxTokens          int            `json:"max_tokens"`
	Temperature        float64        `json:"temperature"`
	Seed               *int           `json:"seed,omitempty"`
	Stream             bool           `json:"stream"`
	StreamOptions      any            `json:"stream_options,omitempty"`
	Tools              []Tool         `json:"tools,omitempty"`
	ToolChoice         any            `json:"tool_choice,omitempty"`
	ResponseFormat     map[string]any `json:"response_format,omitempty"`
	ChatTemplateKwargs map[string]any `json:"chat_template_kwargs,omitempty"`
}

type Usage struct {
	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
	TotalTokens      int `json:"total_tokens"`
}

type Completion struct {
	Answer       string
	ToolNames    []string
	ToolCalls    []ToolCall
	FinishReason string
	Usage        Usage
	StartedAt    time.Time
	Duration     time.Duration
	TTFT         time.Duration
	ChunkTimes   []time.Duration
}

type ToolCall struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

type streamChunk struct {
	Choices []struct {
		Delta struct {
			Content   any `json:"content"`
			ToolCalls []struct {
				Index    int `json:"index"`
				Function struct {
					Name      string `json:"name"`
					Arguments string `json:"arguments"`
				} `json:"function"`
			} `json:"tool_calls"`
		} `json:"delta"`
		FinishReason string `json:"finish_reason"`
	} `json:"choices"`
	Usage Usage `json:"usage"`
}

func (client Client) Complete(ctx context.Context, request Request) (Completion, error) {
	if client.BaseURL == "" || request.Model == "" || len(request.Messages) == 0 {
		return Completion{}, errors.New("completion request is incomplete")
	}
	request.Stream = true
	request.StreamOptions = map[string]bool{"include_usage": true}
	payload, err := json.Marshal(request)
	if err != nil {
		return Completion{}, fmt.Errorf("encode completion request: %w", err)
	}
	started := time.Now().UTC()
	httpRequest, err := http.NewRequestWithContext(ctx, http.MethodPost,
		strings.TrimRight(client.BaseURL, "/")+"/chat/completions", bytes.NewReader(payload))
	if err != nil {
		return Completion{}, fmt.Errorf("create completion request: %w", err)
	}
	httpRequest.Header.Set("Content-Type", "application/json")
	// Local model servers may retire idle keep-alive sockets while a long prompt is
	// running in another slot. A fresh loopback connection avoids replaying a POST
	// after that race; the handshake cost is negligible compared with inference.
	httpRequest.Close = true
	httpClient := client.HTTPClient
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	response, err := httpClient.Do(httpRequest)
	if err != nil {
		return Completion{}, fmt.Errorf("execute completion request: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(response.Body, 8192))
		return Completion{}, fmt.Errorf("completion endpoint returned %s: %s", response.Status, strings.TrimSpace(string(body)))
	}

	completion := Completion{StartedAt: started}
	toolCalls := map[int]ToolCall{}
	scanner := bufio.NewScanner(response.Body)
	scanner.Buffer(make([]byte, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if data == "[DONE]" {
			break
		}
		var chunk streamChunk
		if err := json.Unmarshal([]byte(data), &chunk); err != nil {
			return Completion{}, fmt.Errorf("decode stream chunk: %w", err)
		}
		completion.Usage = mergeUsage(completion.Usage, chunk.Usage)
		for _, choice := range chunk.Choices {
			content := contentText(choice.Delta.Content)
			if content != "" {
				now := time.Now()
				if completion.TTFT == 0 {
					completion.TTFT = now.Sub(started)
				}
				completion.ChunkTimes = append(completion.ChunkTimes, now.Sub(started))
				completion.Answer += content
			}
			for _, call := range choice.Delta.ToolCalls {
				current := toolCalls[call.Index]
				current.Name += call.Function.Name
				current.Arguments += call.Function.Arguments
				toolCalls[call.Index] = current
			}
			if choice.FinishReason != "" {
				completion.FinishReason = choice.FinishReason
			}
		}
	}
	completion.Duration = time.Since(started)
	for index := 0; index < len(toolCalls); index++ {
		call := toolCalls[index]
		completion.ToolCalls = append(completion.ToolCalls, call)
		if call.Name != "" {
			completion.ToolNames = append(completion.ToolNames, call.Name)
		}
	}
	if err := scanner.Err(); err != nil {
		return Completion{}, fmt.Errorf("read completion stream: %w", err)
	}
	if completion.TTFT == 0 && (completion.Answer != "" || len(completion.ToolNames) > 0) {
		completion.TTFT = completion.Duration
	}
	if completion.Answer == "" && len(completion.ToolNames) == 0 {
		return Completion{}, errors.New("completion stream contained no answer or tool call")
	}
	return completion, nil
}

func mergeUsage(current, update Usage) Usage {
	if update.PromptTokens != 0 || update.CompletionTokens != 0 || update.TotalTokens != 0 {
		return update
	}
	return current
}

func contentText(value any) string {
	switch typed := value.(type) {
	case string:
		return typed
	case []any:
		var result strings.Builder
		for _, item := range typed {
			part, ok := item.(map[string]any)
			if !ok {
				continue
			}
			if text, ok := part["text"].(string); ok {
				result.WriteString(text)
			}
		}
		return result.String()
	default:
		return ""
	}
}

func (completion Completion) InterTokenLatency() time.Duration {
	if len(completion.ChunkTimes) < 2 {
		return 0
	}
	return (completion.ChunkTimes[len(completion.ChunkTimes)-1] - completion.ChunkTimes[0]) /
		time.Duration(len(completion.ChunkTimes)-1)
}
