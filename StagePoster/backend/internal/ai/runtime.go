package ai

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"sync"
	"time"
)

type Runtime struct {
	client        *Client
	autoSleep     bool
	beforeAcquire func(context.Context) error
	mu            sync.Mutex
}

func NewRuntime(
	client *Client,
	autoSleep bool,
) *Runtime {
	return &Runtime{
		client:    client,
		autoSleep: autoSleep,
	}
}

func (runtime *Runtime) SetBeforeAcquire(
	hook func(context.Context) error,
) {
	runtime.mu.Lock()
	defer runtime.mu.Unlock()

	runtime.beforeAcquire = hook
}

func (runtime *Runtime) Acquire(
	ctx context.Context,
) (func(), error) {
	runtime.mu.Lock()

	if runtime.beforeAcquire != nil {
		if err := runtime.beforeAcquire(ctx); err != nil {
			runtime.mu.Unlock()

			return nil, fmt.Errorf(
				"prepare GPU before waking VLM: %w",
				err,
			)
		}
	}

	if err := runtime.client.EnsureAwake(ctx); err != nil {
		runtime.mu.Unlock()

		return nil, fmt.Errorf(
			"wake VLM runtime: %w",
			err,
		)
	}

	var once sync.Once

	release := func() {
		once.Do(func() {
			defer runtime.mu.Unlock()

			if !runtime.autoSleep {
				return
			}

			sleepContext, cancel :=
				context.WithTimeout(
					context.Background(),
					90*time.Second,
				)

			defer cancel()

			// Sleep 失败不能覆盖已经成功的业务结果。
			_ = runtime.client.Sleep(
				sleepContext,
			)
		})
	}

	return release, nil
}

func (client *Client) EnsureAwake(
	ctx context.Context,
) error {
	sleeping, err := client.IsSleeping(ctx)
	if err != nil {
		return err
	}

	if !sleeping {
		return nil
	}

	return client.Wake(ctx)
}

func (client *Client) IsSleeping(
	ctx context.Context,
) (bool, error) {
	response, err := client.controlRequest(
		ctx,
		http.MethodGet,
		"/is_sleeping",
		nil,
	)
	if err != nil {
		return false, err
	}

	defer response.Body.Close()

	body, err := io.ReadAll(
		io.LimitReader(response.Body, 64*1024),
	)
	if err != nil {
		return false, fmt.Errorf(
			"read VLM sleep response: %w",
			err,
		)
	}

	var sleeping bool

	if err := json.Unmarshal(body, &sleeping); err == nil {
		return sleeping, nil
	}

	var object struct {
		IsSleeping bool `json:"is_sleeping"`
		Sleeping   bool `json:"sleeping"`
	}

	if err := json.Unmarshal(body, &object); err == nil {
		return object.IsSleeping ||
				object.Sleeping,
			nil
	}

	parsed, err := strconv.ParseBool(
		string(bytes.TrimSpace(body)),
	)
	if err != nil {
		return false, fmt.Errorf(
			"decode VLM sleeping state %q",
			string(body),
		)
	}

	return parsed, nil
}

func (client *Client) Wake(
	ctx context.Context,
) error {
	response, err := client.controlRequest(
		ctx,
		http.MethodPost,
		"/wake_up",
		nil,
	)
	if err != nil {
		return err
	}

	defer response.Body.Close()

	return nil
}

func (client *Client) Sleep(
	ctx context.Context,
) error {
	response, err := client.controlRequest(
		ctx,
		http.MethodPost,
		"/sleep?level=1",
		nil,
	)
	if err != nil {
		return err
	}

	defer response.Body.Close()

	return nil
}

func (client *Client) controlRequest(
	ctx context.Context,
	method string,
	path string,
	body io.Reader,
) (*http.Response, error) {
	request, err := http.NewRequestWithContext(
		ctx,
		method,
		client.baseURL+path,
		body,
	)
	if err != nil {
		return nil, fmt.Errorf(
			"create VLM control request: %w",
			err,
		)
	}

	if client.apiKey != "" {
		request.Header.Set(
			"Authorization",
			"Bearer "+client.apiKey,
		)
	}

	response, err := client.httpClient.Do(request)
	if err != nil {
		return nil, fmt.Errorf(
			"execute VLM control request: %w",
			err,
		)
	}

	if response.StatusCode < 200 ||
		response.StatusCode >= 300 {
		defer response.Body.Close()

		message, _ := io.ReadAll(
			io.LimitReader(
				response.Body,
				64*1024,
			),
		)

		return nil, fmt.Errorf(
			"VLM control %s %s returned %d: %s",
			method,
			path,
			response.StatusCode,
			string(message),
		)
	}

	return response, nil
}

func (runtime *Runtime) Suspend(
	ctx context.Context,
) error {
	runtime.mu.Lock()
	defer runtime.mu.Unlock()

	// autoSleep=false 必须是真正的总开关。ROCm 7.2 + vLLM 0.20.0 上睡眠之后
	// wake_up 会死在 CUDA Error: invalid argument，之后每个 AI 接口都是 502。
	// Acquire 的 release 已经尊重这个开关，Suspend 以前却绕过它。
	if !runtime.autoSleep {
		return nil
	}

	sleeping, err := runtime.client.IsSleeping(ctx)
	if err != nil {
		return fmt.Errorf(
			"read VLM sleep state: %w",
			err,
		)
	}

	if sleeping {
		return nil
	}

	if err := runtime.client.Sleep(ctx); err != nil {
		return fmt.Errorf(
			"sleep VLM runtime: %w",
			err,
		)
	}

	return nil
}
