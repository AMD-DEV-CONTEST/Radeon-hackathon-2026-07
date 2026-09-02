package ai

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

// autoSleep=false 时不能有任何睡眠请求打到 vLLM。ROCm 上睡下去就醒不来，
// 之后每个 AI 接口都是 502。
func TestSuspendRespectsAutoSleepDisabled(
	t *testing.T,
) {
	var sleepCalls int64

	server := httptest.NewServer(
		http.HandlerFunc(func(
			writer http.ResponseWriter,
			request *http.Request,
		) {
			switch request.URL.Path {
			case "/sleep":
				atomic.AddInt64(&sleepCalls, 1)
				writer.WriteHeader(http.StatusOK)

			case "/is_sleeping":
				_, _ = writer.Write(
					[]byte(`{"is_sleeping":false}`),
				)

			default:
				writer.WriteHeader(http.StatusOK)
			}
		}),
	)
	defer server.Close()

	runtime := NewRuntime(
		NewClient(
			server.URL,
			"key",
			"model",
			5*time.Second,
		),
		false,
	)

	if err := runtime.Suspend(
		context.Background(),
	); err != nil {
		t.Fatalf("Suspend error: %v", err)
	}

	if got := atomic.LoadInt64(&sleepCalls); got != 0 {
		t.Fatalf(
			"autoSleep=false still issued %d sleep call(s)",
			got,
		)
	}
}

// 开关打开时 Suspend 仍要正常工作，否则这个修复就把功能删掉了。
func TestSuspendSleepsWhenAutoSleepEnabled(
	t *testing.T,
) {
	var sleepCalls int64

	server := httptest.NewServer(
		http.HandlerFunc(func(
			writer http.ResponseWriter,
			request *http.Request,
		) {
			switch request.URL.Path {
			case "/sleep":
				atomic.AddInt64(&sleepCalls, 1)
				writer.WriteHeader(http.StatusOK)

			case "/is_sleeping":
				_, _ = writer.Write(
					[]byte(`{"is_sleeping":false}`),
				)

			default:
				writer.WriteHeader(http.StatusOK)
			}
		}),
	)
	defer server.Close()

	runtime := NewRuntime(
		NewClient(
			server.URL,
			"key",
			"model",
			5*time.Second,
		),
		true,
	)

	if err := runtime.Suspend(
		context.Background(),
	); err != nil {
		t.Fatalf("Suspend error: %v", err)
	}

	if got := atomic.LoadInt64(&sleepCalls); got != 1 {
		t.Fatalf(
			"autoSleep=true issued %d sleep call(s), want 1",
			got,
		)
	}
}
