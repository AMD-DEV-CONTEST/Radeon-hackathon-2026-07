package intelligenceaudit

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/benchmark"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
	"go.opentelemetry.io/otel"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
)

func TestStoreCapturesSafeMetadataAndProtectsBodies(t *testing.T) {
	now := time.Date(2026, 7, 23, 12, 0, 0, 0, time.UTC)
	var logs bytes.Buffer
	store, err := NewStore(Config{
		Directory: t.TempDir(), Enabled: true, Token: "operator-token",
		TTL: time.Hour, Now: func() time.Time { return now }, LogWriter: &logs,
	})
	if err != nil {
		t.Fatal(err)
	}
	recorder, err := store.Begin(context.Background(), "run-safe", "request-safe", "Compare companies. api_key: secret-value")
	if err != nil {
		t.Fatal(err)
	}
	recorder.ObserveModelCall(context.Background(), "request-interpreter/v1", "local-rocm", benchmark.Request{
		Model: "gemma", Messages: []benchmark.Message{
			{Role: "system", Content: "Interpret the request."},
			{Role: "user", Content: "Authorization: Bearer private-token"},
		},
		MaxTokens: 100, ResponseFormat: map[string]any{"type": "json_schema"},
	}, benchmark.Completion{
		Answer:    `{"intent":"company_comparison"}`,
		Usage:     benchmark.Usage{PromptTokens: 20, CompletionTokens: 5},
		StartedAt: now, Duration: time.Second, TTFT: 100 * time.Millisecond,
		FinishReason: "stop",
	}, nil)
	if err := recorder.Complete(ProjectionInput{
		RunID: "run-safe", RequestID: "request-safe", CompletedAt: now.Add(time.Second),
		Status: "completed",
	}); err != nil {
		t.Fatal(err)
	}

	public, err := store.Public("run-safe")
	if err != nil {
		t.Fatal(err)
	}
	if len(public.ModelCalls) != 1 || public.ModelCalls[0].InputTokens != 20 ||
		public.ModelCalls[0].ProtectedInputID == "" {
		t.Fatalf("public record = %+v", public)
	}
	encodedPublic, _ := os.ReadFile(filepath.Join(store.config.Directory, "run-safe.metadata.json"))
	if strings.Contains(string(encodedPublic), "private-token") || strings.Contains(string(encodedPublic), "secret-value") {
		t.Fatal("public metadata leaked a protected value")
	}
	if _, err := store.Protected("run-safe", "wrong"); err == nil {
		t.Fatal("wrong token accessed protected audit")
	}
	protected, err := store.Protected("run-safe", "operator-token")
	if err != nil {
		t.Fatal(err)
	}
	encoded := protected.ModelCalls[0].Messages[1].Content
	if strings.Contains(encoded, "private-token") || !strings.Contains(encoded, "[REDACTED]") {
		t.Fatalf("protected content was not redacted: %q", encoded)
	}
	if strings.Contains(protected.Question, "secret-value") {
		t.Fatalf("question was not redacted: %q", protected.Question)
	}
	logOutput := logs.String()
	for _, blocked := range []string{"private-token", "secret-value", "Compare companies.", `{"intent"`} {
		if strings.Contains(logOutput, blocked) {
			t.Fatalf("structured log leaked %q: %s", blocked, logOutput)
		}
	}
	if !strings.Contains(logOutput, `"event":"journey.completed"`) ||
		!strings.Contains(logOutput, `"event":"model.completed"`) {
		t.Fatalf("safe lifecycle logs were not emitted: %s", logOutput)
	}
}

func TestStoreExpiryAndPurgeAreFailClosed(t *testing.T) {
	now := time.Date(2026, 7, 23, 12, 0, 0, 0, time.UTC)
	store, err := NewStore(Config{
		Directory: t.TempDir(), Enabled: true, Token: "operator-token",
		TTL: time.Minute, Now: func() time.Time { return now },
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.Begin(context.Background(), "run-expire", "request-expire", "question"); err != nil {
		t.Fatal(err)
	}
	now = now.Add(2 * time.Minute)
	if _, err := store.Protected("run-expire", "operator-token"); err == nil {
		t.Fatal("expired protected record remained readable")
	}
	public, err := store.Public("run-expire")
	if err != nil {
		t.Fatal(err)
	}
	if public.Capture.Status != "expired" || public.Capture.Available {
		t.Fatalf("capture state = %+v", public.Capture)
	}

	now = now.Add(time.Minute)
	if _, err := store.Begin(context.Background(), "run-purge", "request-purge", "question"); err != nil {
		t.Fatal(err)
	}
	if err := store.Purge("run-purge", "operator-token"); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Protected("run-purge", "operator-token"); err == nil {
		t.Fatal("purged protected record remained readable")
	}
}

func TestDisabledCaptureStillRecordsMetadata(t *testing.T) {
	store, err := NewStore(Config{Directory: t.TempDir()})
	if err != nil {
		t.Fatal(err)
	}
	recorder, err := store.Begin(context.Background(), "run-disabled", "request-disabled", "question")
	if err != nil {
		t.Fatal(err)
	}
	recorder.ObserveModelCall(context.Background(), "final-research-analyst/v1", "local-rocm",
		benchmark.Request{Model: "gemma", Messages: []benchmark.Message{{Role: "system", Content: "answer"}}, MaxTokens: 10},
		benchmark.Completion{}, errors.New("provider failure"))
	public, err := store.Public("run-disabled")
	if err != nil {
		t.Fatal(err)
	}
	if public.Capture.Status != "disabled" || len(public.ModelCalls) != 1 ||
		public.ModelCalls[0].FailureCode != "model_call_failed" {
		t.Fatalf("public record = %+v", public)
	}
}

func TestLifecycleProjectionIsBoundedTypedAndBodyFree(t *testing.T) {
	now := time.Date(2026, 7, 26, 12, 0, 0, 0, time.UTC)
	spanRecorder := tracetest.NewSpanRecorder()
	tracerProvider := sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(spanRecorder))
	previousTracerProvider := otel.GetTracerProvider()
	otel.SetTracerProvider(tracerProvider)
	t.Cleanup(func() {
		otel.SetTracerProvider(previousTracerProvider)
		_ = tracerProvider.Shutdown(context.Background())
	})
	var logs bytes.Buffer
	store, err := NewStore(Config{
		Directory: t.TempDir(), Now: func() time.Time { return now }, LogWriter: &logs,
	})
	if err != nil {
		t.Fatal(err)
	}
	recorder, err := store.Begin(context.Background(), "run-lifecycle", "request-lifecycle", "private question")
	if err != nil {
		t.Fatal(err)
	}
	recorder.ObserveLifecycle(context.Background(), orchestrator.Event{
		Sequence: 1, RunID: "run-lifecycle", StepID: "context-wave-1",
		Type: "wave", Status: "started", At: now,
		Attributes: map[string]string{
			"wave": "1", "specialist_count": "4", "concurrency_limit": "4",
			"prompt": "never log this prompt", "answer": "never log this answer",
		},
	})
	recorder.ObserveLifecycle(context.Background(), orchestrator.Event{
		Sequence: 2, RunID: "run-lifecycle", StepID: "context-wave-1",
		Type: "wave", Status: "completed", At: now.Add(time.Second),
		Attributes: map[string]string{
			"wave": "1", "specialist_count": "4", "concurrency_limit": "4", "succeeded_count": "4",
			"failed_count": "0", "observed_concurrency": "4",
			"authorization": "Bearer private-token", "raw_response": "private response",
		},
	})
	recorder.ObserveLifecycle(context.Background(), orchestrator.Event{
		Sequence: 3, RunID: "different-run", StepID: "context-wave-2",
		Type: "wave", Status: "completed", At: now.Add(2 * time.Second),
	})
	recorder.ObserveLifecycle(context.Background(), orchestrator.Event{
		Sequence: 4, RunID: "run-lifecycle", StepID: "context-wave-2",
		Type: "wave", Status: "invented", At: now.Add(3 * time.Second),
	})

	public, err := store.Public("run-lifecycle")
	if err != nil {
		t.Fatal(err)
	}
	if len(public.Timeline) != 2 {
		t.Fatalf("timeline=%+v, want only the two accepted lifecycle events", public.Timeline)
	}
	terminal := public.Timeline[1]
	if terminal.EventType != "wave" || terminal.Status != "completed" || terminal.Wave != 1 ||
		terminal.SpecialistCount != 4 || terminal.ConcurrencyLimit != 4 ||
		terminal.SucceededCount != 4 ||
		terminal.ObservedConcurrency != 4 {
		t.Fatalf("terminal lifecycle projection=%+v", terminal)
	}
	publicJSON, err := json.Marshal(public)
	if err != nil {
		t.Fatal(err)
	}
	logOutput := logs.String()
	for _, blocked := range []string{
		"never log this prompt", "never log this answer", "private-token", "private response",
		`"prompt"`, `"answer"`, `"authorization"`, `"raw_response"`,
	} {
		if strings.Contains(string(publicJSON), blocked) || strings.Contains(logOutput, blocked) {
			t.Fatalf("lifecycle projection leaked %q: public=%s logs=%s", blocked, publicJSON, logOutput)
		}
	}
	if !strings.Contains(logOutput, `"event":"orchestration.wave"`) ||
		!strings.Contains(logOutput, `"specialist_count":4`) {
		t.Fatalf("bounded lifecycle log was not emitted: %s", logOutput)
	}
	spans := spanRecorder.Ended()
	if len(spans) != 1 || spans[0].Name() != "signalforge.wave" ||
		!spans[0].StartTime().Equal(now) || !spans[0].EndTime().Equal(now.Add(time.Second)) {
		t.Fatalf("correlated wave spans=%+v", spans)
	}
	spanAttributes := map[string]string{}
	for _, item := range spans[0].Attributes() {
		spanAttributes[string(item.Key)] = item.Value.Emit()
	}
	if spanAttributes["signalforge.run_id"] != "run-lifecycle" ||
		spanAttributes["signalforge.step_id"] != "context-wave-1" ||
		spanAttributes["signalforge.event_type"] != "wave" ||
		spanAttributes["signalforge.wave"] != "1" ||
		spanAttributes["signalforge.concurrency_limit"] != "4" {
		t.Fatalf("wave span attributes=%v", spanAttributes)
	}
}

func TestLifecycleProjectionRetainsOnlyTheNewest256Events(t *testing.T) {
	now := time.Date(2026, 7, 26, 12, 0, 0, 0, time.UTC)
	store, err := NewStore(Config{Directory: t.TempDir(), Now: func() time.Time { return now }})
	if err != nil {
		t.Fatal(err)
	}
	recorder, err := store.Begin(context.Background(), "run-bounded", "request-bounded", "question")
	if err != nil {
		t.Fatal(err)
	}
	for sequence := 1; sequence <= 260; sequence++ {
		recorder.ObserveLifecycle(context.Background(), orchestrator.Event{
			Sequence: sequence, RunID: "run-bounded",
			StepID: "step-" + strconv.Itoa(sequence),
			Type:   "context", Status: "started", At: now.Add(time.Duration(sequence) * time.Millisecond),
		})
	}
	public, err := store.Public("run-bounded")
	if err != nil {
		t.Fatal(err)
	}
	if len(public.Timeline) != 256 || public.Timeline[0].Sequence != 5 ||
		public.Timeline[len(public.Timeline)-1].Sequence != 260 {
		t.Fatalf("bounded timeline=%d first=%d last=%d", len(public.Timeline),
			public.Timeline[0].Sequence, public.Timeline[len(public.Timeline)-1].Sequence)
	}
}

func TestStoreBoundsCompletedHistoryAndRemovesEvictedFiles(t *testing.T) {
	now := time.Date(2026, 7, 26, 12, 0, 0, 0, time.UTC)
	store, err := NewStore(Config{
		Directory: t.TempDir(), MaxRecords: 3, Now: func() time.Time { return now },
	})
	if err != nil {
		t.Fatal(err)
	}
	for index := 1; index <= 5; index++ {
		runID := "run-history-" + strconv.Itoa(index)
		recorder, beginErr := store.Begin(context.Background(), runID,
			"request-history-"+strconv.Itoa(index), "question")
		if beginErr != nil {
			t.Fatal(beginErr)
		}
		if completeErr := recorder.Complete(ProjectionInput{
			RunID: runID, RequestID: "request-history-" + strconv.Itoa(index),
			Status: "completed", CompletedAt: now.Add(time.Second),
		}); completeErr != nil {
			t.Fatal(completeErr)
		}
		now = now.Add(time.Minute)
	}
	snapshot := store.Snapshot()
	if len(snapshot) != 3 || snapshot[0].RunID != "run-history-3" ||
		snapshot[2].RunID != "run-history-5" {
		t.Fatalf("bounded history=%+v", snapshot)
	}
	for _, evicted := range []string{"run-history-1", "run-history-2"} {
		if _, err := store.Public(evicted); !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("evicted run %q remains available: %v", evicted, err)
		}
		if _, err := os.Stat(store.publicPath(evicted)); !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("evicted public file %q remains available: %v", evicted, err)
		}
	}
	for _, retained := range []string{"run-history-3", "run-history-4", "run-history-5"} {
		if _, err := store.Public(retained); err != nil {
			t.Fatalf("retained run %q is unavailable: %v", retained, err)
		}
	}
}

func TestRunningRecordsDoNotConsumeCompletedHistoryQuota(t *testing.T) {
	store, err := NewStore(Config{
		Directory: t.TempDir(), MaxRecords: 3,
		Now: func() time.Time { return time.Date(2026, 7, 26, 12, 0, 0, 0, time.UTC) },
	})
	if err != nil {
		t.Fatal(err)
	}
	for index := 1; index <= 3; index++ {
		runID := fmt.Sprintf("run-completed-%d", index)
		recorder, beginErr := store.Begin(context.Background(), runID,
			fmt.Sprintf("request-completed-%d", index), "question")
		if beginErr != nil {
			t.Fatal(beginErr)
		}
		if completeErr := recorder.Complete(ProjectionInput{
			Status: "completed", CompletedAt: store.config.Now(),
		}); completeErr != nil {
			t.Fatal(completeErr)
		}
	}
	if _, err := store.Begin(context.Background(), "run-active", "request-active", "question"); err != nil {
		t.Fatal(err)
	}
	for index := 1; index <= 3; index++ {
		if _, err := store.Public(fmt.Sprintf("run-completed-%d", index)); err != nil {
			t.Fatalf("active run evicted completed history slot %d: %v", index, err)
		}
	}
	if len(store.records) != 4 {
		t.Fatalf("expected three completed records plus one active record, got %d", len(store.records))
	}
}

func TestEvictionFailureRetainsRecordAndReportsTypedFailure(t *testing.T) {
	var logs bytes.Buffer
	store, err := NewStore(Config{
		Directory: t.TempDir(), MaxRecords: 1, Enabled: true, Token: "operator-token",
		LogWriter: &logs,
		Now:       func() time.Time { return time.Date(2026, 7, 26, 12, 0, 0, 0, time.UTC) },
	})
	if err != nil {
		t.Fatal(err)
	}
	complete := func(runID string) {
		t.Helper()
		recorder, beginErr := store.Begin(context.Background(), runID, "request-"+runID, "question")
		if beginErr != nil {
			t.Fatal(beginErr)
		}
		if completeErr := recorder.Complete(ProjectionInput{
			Status: "completed", CompletedAt: store.config.Now(),
		}); completeErr != nil {
			t.Fatal(completeErr)
		}
	}
	complete("run-old")
	store.removeFile = func(path string) error {
		if strings.HasSuffix(path, ".protected.json") {
			return os.ErrPermission
		}
		return os.Remove(path)
	}
	complete("run-new")

	if _, err := store.Public("run-old"); err != nil {
		t.Fatalf("failed eviction must retain the public record: %v", err)
	}
	if _, err := store.Protected("run-old", "operator-token"); err != nil {
		t.Fatalf("failed eviction must retain protected record access: %v", err)
	}
	if strings.Contains(logs.String(), `"event":"audit.evicted"`) {
		t.Fatal("failed durable cleanup must not emit successful eviction")
	}
	for _, expected := range []string{
		`"event":"audit.eviction_failed"`,
		`"artifact":"protected_capture"`,
		`"error_class":"permission_denied"`,
	} {
		if !strings.Contains(logs.String(), expected) {
			t.Fatalf("typed eviction failure is missing %s: %s", expected, logs.String())
		}
	}
}

func TestCompleteSerializesRequiredCollectionsAsArrays(t *testing.T) {
	store, err := NewStore(Config{Directory: t.TempDir()})
	if err != nil {
		t.Fatal(err)
	}
	recorder, err := store.Begin(context.Background(), "run-arrays", "request-arrays", "question")
	if err != nil {
		t.Fatal(err)
	}
	if err := recorder.Complete(ProjectionInput{
		RunID: "run-arrays", RequestID: "request-arrays", Status: "completed",
		Retrievals: []RetrievalRecord{{
			RetrievalID: "retrieval-empty", StepID: "context-empty",
			RoleID: "financial-quality/v1", Method: "authorized_context_packet",
			ContextPacketID: "packet-empty", Status: "selected",
		}},
		Engines: []EngineCall{{
			EngineCallID: "engine-empty", StepID: "tool-empty",
			EngineID: "financial", EngineVersion: "1.0.0",
			OperationID: "financial.empty", FormulaVersion: "1.0.0",
			ReceiptID: "receipt-empty", ReceiptSHA: strings.Repeat("a", 64),
			Status: "success",
		}},
		Release: &ReleaseRecord{AnswerID: "answer-empty", Status: "released"},
	}); err != nil {
		t.Fatal(err)
	}

	payload, err := os.ReadFile(filepath.Join(store.config.Directory, "run-arrays.metadata.json"))
	if err != nil {
		t.Fatal(err)
	}
	var raw map[string]any
	if err := json.Unmarshal(payload, &raw); err != nil {
		t.Fatal(err)
	}
	assertJSONArray(t, raw, "model_calls")
	assertJSONArray(t, raw, "timeline")
	assertJSONArray(t, raw, "retrievals")
	assertJSONArray(t, raw, "engine_calls")
	assertJSONArray(t, raw, "reviews")
	retrieval := raw["retrievals"].([]any)[0].(map[string]any)
	assertJSONArray(t, retrieval, "evidence_ids")
	engine := raw["engine_calls"].([]any)[0].(map[string]any)
	assertJSONArray(t, engine, "input_refs")
	assertJSONArray(t, engine, "output_refs")
	release := raw["release"].(map[string]any)
	assertJSONArray(t, release, "section_types")
	assertJSONArray(t, release, "claim_refs")
	assertJSONArray(t, release, "evidence_refs")
	assertJSONArray(t, release, "receipt_refs")
}

func assertJSONArray(t *testing.T, value map[string]any, key string) {
	t.Helper()
	if _, ok := value[key].([]any); !ok {
		t.Fatalf("%s = %#v, want JSON array", key, value[key])
	}
}
