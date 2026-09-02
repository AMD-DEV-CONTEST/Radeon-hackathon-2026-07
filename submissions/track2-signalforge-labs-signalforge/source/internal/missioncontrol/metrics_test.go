package missioncontrol

import (
	"context"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/benchmark"
	"github.com/rvbernucci/signalforge/internal/intelligenceaudit"
)

func TestMetricsUseOnlyBoundedLabels(t *testing.T) {
	now := time.Date(2026, 7, 23, 12, 0, 0, 0, time.UTC)
	store, err := intelligenceaudit.NewStore(intelligenceaudit.Config{
		Directory: t.TempDir(), Now: func() time.Time { return now },
	})
	if err != nil {
		t.Fatal(err)
	}
	recorder, err := store.Begin(context.Background(), "run-secret-high-cardinality", "request-secret", "private prompt")
	if err != nil {
		t.Fatal(err)
	}
	recorder.ObserveModelCall(context.Background(), "business-strategy/v1", "radeon-vllm",
		benchmark.Request{Model: "model-secret-id", Messages: []benchmark.Message{{Role: "user", Content: "private prompt"}}, MaxTokens: 100},
		benchmark.Completion{StartedAt: now, Duration: time.Second, Usage: benchmark.Usage{PromptTokens: 10, CompletionTokens: 4}}, nil)
	if err := recorder.Complete(intelligenceaudit.ProjectionInput{
		RunID: "run-secret-high-cardinality", RequestID: "request-secret",
		CompletedAt: now.Add(2 * time.Second), Status: "completed",
	}); err != nil {
		t.Fatal(err)
	}

	response := httptest.NewRecorder()
	MetricsHandler{Store: store, Version: "test"}.ServeHTTP(response, httptest.NewRequest("GET", "/metrics", nil))
	body := response.Body.String()
	for _, forbidden := range []string{"run-secret", "request-secret", "private prompt", "model-secret-id"} {
		if strings.Contains(body, forbidden) {
			t.Fatalf("metrics leaked %q:\n%s", forbidden, body)
		}
	}
	for _, required := range []string{"signalforge_journeys_total", "signalforge_model_calls_total", `provider="radeon-vllm"`, `direction="input"`} {
		if !strings.Contains(body, required) {
			t.Fatalf("metrics omitted %q:\n%s", required, body)
		}
	}
}
