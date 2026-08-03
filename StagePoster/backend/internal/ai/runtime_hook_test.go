package ai

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

func TestRuntimeRunsBeforeAcquireHook(t *testing.T) {
	t.Parallel()

	var sleepChecks atomic.Int32
	var hookCalls atomic.Int32

	server := httptest.NewServer(
		http.HandlerFunc(
			func(
				writer http.ResponseWriter,
				request *http.Request,
			) {
				switch request.URL.Path {
				case "/is_sleeping":
					sleepChecks.Add(1)

					writer.Header().Set(
						"Content-Type",
						"application/json",
					)

					_, _ = writer.Write(
						[]byte(`false`),
					)

				default:
					http.NotFound(
						writer,
						request,
					)
				}
			},
		),
	)
	defer server.Close()

	client := NewClient(
		server.URL,
		"",
		"test-model",
		5*time.Second,
	)

	runtime := NewRuntime(
		client,
		false,
	)

	runtime.SetBeforeAcquire(
		func(context.Context) error {
			hookCalls.Add(1)
			return nil
		},
	)

	release, err := runtime.Acquire(
		context.Background(),
	)
	if err != nil {
		t.Fatalf(
			"Acquire error: %v",
			err,
		)
	}

	release()

	if hookCalls.Load() != 1 {
		t.Fatalf(
			"hook calls = %d, want 1",
			hookCalls.Load(),
		)
	}

	if sleepChecks.Load() != 1 {
		t.Fatalf(
			"sleep checks = %d, want 1",
			sleepChecks.Load(),
		)
	}
}

func TestRuntimeStopsWhenBeforeAcquireFails(t *testing.T) {
	t.Parallel()

	var sleepChecks atomic.Int32

	server := httptest.NewServer(
		http.HandlerFunc(
			func(
				writer http.ResponseWriter,
				request *http.Request,
			) {
				sleepChecks.Add(1)
				writer.WriteHeader(http.StatusOK)
				_, _ = writer.Write([]byte(`false`))
			},
		),
	)
	defer server.Close()

	client := NewClient(
		server.URL,
		"",
		"test-model",
		5*time.Second,
	)

	runtime := NewRuntime(
		client,
		false,
	)

	runtime.SetBeforeAcquire(
		func(context.Context) error {
			return context.DeadlineExceeded
		},
	)

	release, err := runtime.Acquire(
		context.Background(),
	)

	if err == nil {
		if release != nil {
			release()
		}

		t.Fatal(
			"Acquire returned nil error",
		)
	}

	if sleepChecks.Load() != 0 {
		t.Fatalf(
			"sleep checks = %d, want 0",
			sleepChecks.Load(),
		)
	}
}
