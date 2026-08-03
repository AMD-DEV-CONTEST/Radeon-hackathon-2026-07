package ai

import (
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
	baseURL    string
	apiKey     string
	model      string
	httpClient *http.Client
}

type Message struct {
	Role    string `json:"role"`
	Content any    `json:"content"`
}

type CompletionOptions struct {
	Temperature float64
	MaxTokens   int
}

type Metrics struct {
	PromptTokens     int
	CompletionTokens int
	TotalTokens      int
	Latency          time.Duration
}

type completionRequest struct {
	Model              string         `json:"model"`
	Messages           []Message      `json:"messages"`
	Stream             bool           `json:"stream"`
	Temperature        float64        `json:"temperature,omitempty"`
	MaxTokens          int            `json:"max_tokens,omitempty"`
	ChatTemplateKwargs map[string]any `json:"chat_template_kwargs,omitempty"`
}

type completionResponse struct {
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	} `json:"choices"`

	Usage struct {
		PromptTokens     int `json:"prompt_tokens"`
		CompletionTokens int `json:"completion_tokens"`
		TotalTokens      int `json:"total_tokens"`
	} `json:"usage"`

	Error *struct {
		Message string `json:"message"`
		Type    string `json:"type"`
	} `json:"error,omitempty"`
}

func NewClient(
	baseURL string,
	apiKey string,
	model string,
	timeout time.Duration,
) *Client {
	if timeout <= 0 {
		timeout = 90 * time.Second
	}

	return &Client{
		baseURL: strings.TrimRight(
			strings.TrimSpace(baseURL),
			"/",
		),
		apiKey: strings.TrimSpace(apiKey),
		model:  strings.TrimSpace(model),
		httpClient: &http.Client{
			Timeout: timeout,
		},
	}
}

func (client *Client) Health(
	ctx context.Context,
) error {
	if client.baseURL == "" {
		return errors.New("VLM base URL is empty")
	}

	request, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		client.baseURL+"/v1/models",
		nil,
	)
	if err != nil {
		return fmt.Errorf(
			"create VLM health request: %w",
			err,
		)
	}

	client.applyHeaders(request)

	response, err := client.httpClient.Do(request)
	if err != nil {
		return fmt.Errorf(
			"request VLM health: %w",
			err,
		)
	}
	defer response.Body.Close()

	if response.StatusCode < 200 ||
		response.StatusCode >= 300 {
		body, _ := io.ReadAll(
			io.LimitReader(response.Body, 4096),
		)

		return fmt.Errorf(
			"VLM health returned %s: %s",
			response.Status,
			strings.TrimSpace(string(body)),
		)
	}

	return nil
}

func (client *Client) Complete(
	ctx context.Context,
	messages []Message,
	options CompletionOptions,
) (string, Metrics, error) {
	if client.baseURL == "" {
		return "", Metrics{},
			errors.New("VLM base URL is empty")
	}

	if client.model == "" {
		return "", Metrics{},
			errors.New("VLM model is empty")
	}

	if len(messages) == 0 {
		return "", Metrics{},
			errors.New("VLM messages are empty")
	}

	if options.MaxTokens <= 0 {
		options.MaxTokens = 800
	}

	payload := completionRequest{
		Model:       client.model,
		Messages:    messages,
		Stream:      false,
		Temperature: options.Temperature,
		MaxTokens:   options.MaxTokens,
		ChatTemplateKwargs: map[string]any{
			"enable_thinking": false,
		},
	}

	encoded, err := json.Marshal(payload)
	if err != nil {
		return "", Metrics{},
			fmt.Errorf(
				"encode VLM request: %w",
				err,
			)
	}

	request, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		client.baseURL+"/v1/chat/completions",
		bytes.NewReader(encoded),
	)
	if err != nil {
		return "", Metrics{},
			fmt.Errorf(
				"create VLM request: %w",
				err,
			)
	}

	client.applyHeaders(request)
	request.Header.Set(
		"Content-Type",
		"application/json",
	)

	started := time.Now()

	response, err := client.httpClient.Do(request)
	latency := time.Since(started)

	if err != nil {
		return "", Metrics{
				Latency: latency,
			}, fmt.Errorf(
				"request VLM completion: %w",
				err,
			)
	}
	defer response.Body.Close()

	body, err := io.ReadAll(
		io.LimitReader(response.Body, 4<<20),
	)
	if err != nil {
		return "", Metrics{
				Latency: latency,
			}, fmt.Errorf(
				"read VLM response: %w",
				err,
			)
	}

	if response.StatusCode < 200 ||
		response.StatusCode >= 300 {
		return "", Metrics{
				Latency: latency,
			}, fmt.Errorf(
				"VLM returned %s: %s",
				response.Status,
				strings.TrimSpace(string(body)),
			)
	}

	var decoded completionResponse

	if err := json.Unmarshal(
		body,
		&decoded,
	); err != nil {
		return "", Metrics{
				Latency: latency,
			}, fmt.Errorf(
				"decode VLM response: %w",
				err,
			)
	}

	if decoded.Error != nil {
		return "", Metrics{
				Latency: latency,
			}, fmt.Errorf(
				"VLM error %s: %s",
				decoded.Error.Type,
				decoded.Error.Message,
			)
	}

	if len(decoded.Choices) == 0 {
		return "", Metrics{
				Latency: latency,
			}, errors.New(
				"VLM returned no choices",
			)
	}

	content := strings.TrimSpace(
		decoded.Choices[0].Message.Content,
	)

	if content == "" {
		return "", Metrics{
				Latency: latency,
			}, errors.New(
				"VLM returned empty content",
			)
	}

	return content, Metrics{
		PromptTokens:     decoded.Usage.PromptTokens,
		CompletionTokens: decoded.Usage.CompletionTokens,
		TotalTokens:      decoded.Usage.TotalTokens,
		Latency:          latency,
	}, nil
}

func (client *Client) CompleteJSON(
	ctx context.Context,
	messages []Message,
	options CompletionOptions,
	output any,
) (Metrics, error) {
	content, metrics, err := client.Complete(
		ctx,
		messages,
		options,
	)
	if err != nil {
		return metrics, err
	}

	if err := DecodeJSONObject(
		content,
		output,
	); err != nil {
		return metrics, fmt.Errorf(
			"decode VLM JSON: %w",
			err,
		)
	}

	return metrics, nil
}

func (client *Client) applyHeaders(
	request *http.Request,
) {
	if client.apiKey != "" {
		request.Header.Set(
			"Authorization",
			"Bearer "+client.apiKey,
		)
	}
}
