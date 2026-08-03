package comfy

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

type Client struct {
	baseURL string
	http    *http.Client
}

type submitResponse struct {
	PromptID   string         `json:"prompt_id"`
	Number     int            `json:"number"`
	NodeErrors map[string]any `json:"node_errors"`
}

type historyStatus struct {
	StatusStr string `json:"status_str"`
	Completed bool   `json:"completed"`
	Messages  []any  `json:"messages"`
}

type historyOutput struct {
	Images []domain.ImageMeta `json:"images"`
}

type historyEntry struct {
	Status  historyStatus            `json:"status"`
	Outputs map[string]historyOutput `json:"outputs"`
}

func NewClient(baseURL string) *Client {
	return &Client{
		baseURL: strings.TrimRight(baseURL, "/"),
		http: &http.Client{
			Timeout: 60 * time.Second,
		},
	}
}

func (c *Client) Health(ctx context.Context) error {
	request, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		c.baseURL+"/system_stats",
		nil,
	)
	if err != nil {
		return err
	}

	response, err := c.http.Do(request)
	if err != nil {
		return fmt.Errorf("request ComfyUI health: %w", err)
	}
	defer response.Body.Close()

	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf(
			"ComfyUI health returned HTTP %d",
			response.StatusCode,
		)
	}

	return nil
}

func (c *Client) FreeMemory(
	ctx context.Context,
) error {
	payload, err := json.Marshal(
		map[string]bool{
			"unload_models": true,
			"free_memory":   true,
		},
	)
	if err != nil {
		return fmt.Errorf(
			"marshal ComfyUI free request: %w",
			err,
		)
	}

	request, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		c.baseURL+"/free",
		bytes.NewReader(payload),
	)
	if err != nil {
		return fmt.Errorf(
			"create ComfyUI free request: %w",
			err,
		)
	}

	request.Header.Set(
		"Content-Type",
		"application/json",
	)

	response, err := c.http.Do(request)
	if err != nil {
		return fmt.Errorf(
			"request ComfyUI memory release: %w",
			err,
		)
	}
	defer response.Body.Close()

	body, readErr := io.ReadAll(
		io.LimitReader(
			response.Body,
			64*1024,
		),
	)
	if readErr != nil {
		return fmt.Errorf(
			"read ComfyUI memory release response: %w",
			readErr,
		)
	}

	if response.StatusCode < 200 ||
		response.StatusCode >= 300 {

		return fmt.Errorf(
			"ComfyUI /free returned HTTP %d: %s",
			response.StatusCode,
			strings.TrimSpace(string(body)),
		)
	}

	return nil
}

func (c *Client) Submit(
	ctx context.Context,
	workflow map[string]any,
) (string, error) {
	payload := map[string]any{
		"prompt": workflow,
		"client_id": fmt.Sprintf(
			"poster-go-%d",
			time.Now().UnixNano(),
		),
	}

	raw, err := json.Marshal(payload)
	if err != nil {
		return "", fmt.Errorf("marshal ComfyUI request: %w", err)
	}

	request, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		c.baseURL+"/prompt",
		bytes.NewReader(raw),
	)
	if err != nil {
		return "", err
	}

	request.Header.Set("Content-Type", "application/json")

	response, err := c.http.Do(request)
	if err != nil {
		return "", fmt.Errorf("submit workflow: %w", err)
	}
	defer response.Body.Close()

	body, err := io.ReadAll(
		io.LimitReader(response.Body, 4*1024*1024),
	)
	if err != nil {
		return "", fmt.Errorf("read ComfyUI response: %w", err)
	}

	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return "", fmt.Errorf(
			"ComfyUI returned HTTP %d: %s",
			response.StatusCode,
			string(body),
		)
	}

	var result submitResponse
	if err := json.Unmarshal(body, &result); err != nil {
		return "", fmt.Errorf(
			"decode ComfyUI response: %w",
			err,
		)
	}

	if result.PromptID == "" {
		return "", fmt.Errorf(
			"ComfyUI response has no prompt_id: %s",
			string(body),
		)
	}

	return result.PromptID, nil
}

func (c *Client) Inspect(
	ctx context.Context,
	promptID string,
) (
	status string,
	image *domain.ImageMeta,
	messages []any,
	err error,
) {
	requestURL := c.baseURL +
		"/history/" +
		url.PathEscape(promptID)

	request, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		requestURL,
		nil,
	)
	if err != nil {
		return "", nil, nil, err
	}

	response, err := c.http.Do(request)
	if err != nil {
		return "", nil, nil, fmt.Errorf(
			"request ComfyUI history: %w",
			err,
		)
	}
	defer response.Body.Close()

	if response.StatusCode < 200 || response.StatusCode >= 300 {
		body, _ := io.ReadAll(
			io.LimitReader(response.Body, 1024*1024),
		)

		return "", nil, nil, fmt.Errorf(
			"ComfyUI history HTTP %d: %s",
			response.StatusCode,
			string(body),
		)
	}

	var histories map[string]historyEntry
	if err := json.NewDecoder(response.Body).Decode(&histories); err != nil {
		return "", nil, nil, fmt.Errorf(
			"decode ComfyUI history: %w",
			err,
		)
	}

	entry, found := histories[promptID]
	if !found {
		return "running", nil, nil, nil
	}

	if entry.Status.StatusStr == "error" {
		return "failed", nil, entry.Status.Messages, nil
	}

	for _, output := range entry.Outputs {
		if len(output.Images) > 0 {
			foundImage := output.Images[0]
			return "succeeded", &foundImage, nil, nil
		}
	}

	if entry.Status.Completed {
		return "succeeded", nil, nil, nil
	}

	return "running", nil, nil, nil
}

func (c *Client) OpenImage(
	ctx context.Context,
	image domain.ImageMeta,
) (*http.Response, error) {
	query := url.Values{}
	query.Set("filename", image.Filename)
	query.Set("subfolder", image.Subfolder)
	query.Set("type", image.Type)

	request, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		c.baseURL+"/view?"+query.Encode(),
		nil,
	)
	if err != nil {
		return nil, err
	}

	response, err := c.http.Do(request)
	if err != nil {
		return nil, fmt.Errorf("fetch ComfyUI image: %w", err)
	}

	if response.StatusCode < 200 || response.StatusCode >= 300 {
		defer response.Body.Close()

		body, _ := io.ReadAll(
			io.LimitReader(response.Body, 1024*1024),
		)

		return nil, fmt.Errorf(
			"ComfyUI image HTTP %d: %s",
			response.StatusCode,
			string(body),
		)
	}

	return response, nil
}

func (c *Client) CancelPrompt(
	ctx context.Context,
	promptID string,
) error {
	payload, err := json.Marshal(
		map[string]string{
			"prompt_id": promptID,
		},
	)
	if err != nil {
		return fmt.Errorf(
			"marshal ComfyUI cancel request: %w",
			err,
		)
	}

	request, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		c.baseURL+"/interrupt",
		bytes.NewReader(payload),
	)
	if err != nil {
		return fmt.Errorf(
			"create ComfyUI cancel request: %w",
			err,
		)
	}

	request.Header.Set(
		"Content-Type",
		"application/json",
	)

	response, err := c.http.Do(request)
	if err != nil {
		return fmt.Errorf(
			"request ComfyUI cancel: %w",
			err,
		)
	}
	defer response.Body.Close()

	body, readErr := io.ReadAll(
		io.LimitReader(
			response.Body,
			64*1024,
		),
	)
	if readErr != nil {
		return fmt.Errorf(
			"read ComfyUI cancel response: %w",
			readErr,
		)
	}

	if response.StatusCode < 200 ||
		response.StatusCode >= 300 {

		return fmt.Errorf(
			"ComfyUI /interrupt returned HTTP %d: %s",
			response.StatusCode,
			strings.TrimSpace(string(body)),
		)
	}

	return nil
}
