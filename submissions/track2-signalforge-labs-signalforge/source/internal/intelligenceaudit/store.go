package intelligenceaudit

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/rvbernucci/signalforge/internal/benchmark"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
	"github.com/rvbernucci/signalforge/internal/telemetry"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"
)

const (
	defaultTTL        = 15 * time.Minute
	defaultMaxBytes   = 16 << 20
	defaultMaxRecords = 64
	maxTimelineItems  = 256
)

var safeIdentity = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$`)

type Config struct {
	Directory  string
	Enabled    bool
	Token      string
	TTL        time.Duration
	MaxBytes   int64
	MaxRecords int
	Now        func() time.Time
	LogWriter  io.Writer
}

type Store struct {
	config     Config
	mu         sync.RWMutex
	records    map[string]*storedRecord
	removeFile func(string) error
}

type storedRecord struct {
	public    Record
	protected ProtectedRecord
}

type Recorder struct {
	store            *Store
	runID            string
	ctx              context.Context
	counter          atomic.Uint64
	lifecycleMu      sync.Mutex
	lifecycleStarted map[string]time.Time
}

func NewStore(config Config) (*Store, error) {
	if config.Directory == "" {
		config.Directory = ".signalforge/intelligence-audit"
	}
	if config.TTL <= 0 {
		config.TTL = defaultTTL
	}
	if config.MaxBytes <= 0 {
		config.MaxBytes = defaultMaxBytes
	}
	if config.MaxRecords <= 0 {
		config.MaxRecords = defaultMaxRecords
	}
	if config.Now == nil {
		config.Now = func() time.Time { return time.Now().UTC() }
	}
	if config.Enabled && strings.TrimSpace(config.Token) == "" {
		return nil, errors.New("enabled intelligence audit capture requires an operator token")
	}
	return &Store{
		config: config, records: map[string]*storedRecord{}, removeFile: os.Remove,
	}, nil
}

func (store *Store) Begin(ctx context.Context, runID, requestID, question string) (*Recorder, error) {
	if !safeIdentity.MatchString(runID) || !safeIdentity.MatchString(requestID) {
		return nil, errors.New("safe run_id and request_id are required")
	}
	now := store.config.Now()
	traceID := telemetry.TraceIDForRun(runID)
	if ctx != nil {
		if spanContext := trace.SpanContextFromContext(ctx); spanContext.IsValid() {
			traceID = spanContext.TraceID().String()
		}
	}
	capture := CaptureState{
		Enabled: store.config.Enabled, Available: store.config.Enabled,
		Status: "disabled", MaximumBytes: store.config.MaxBytes,
	}
	protected := ProtectedRecord{
		SchemaVersion: ProtectedSchemaVersionV1, RunID: runID, RequestID: requestID,
		CreatedAt: now, ExpiresAt: now.Add(store.config.TTL),
		ModelCalls: []ProtectedModelCall{}, Receipts: []ProtectedReceipt{},
	}
	if store.config.Enabled {
		capture.Status = "active"
		capture.ExpiresAt = &protected.ExpiresAt
		protected.Question = redact(question)
	}
	store.mu.Lock()
	store.records[runID] = &storedRecord{
		public: Record{
			SchemaVersion: SchemaVersionV1, RunID: runID, RequestID: requestID,
			TraceID: traceID, Status: "running", Capture: capture, StartedAt: now,
			Timeline:   []LifecycleEvent{},
			ModelCalls: []ModelCall{}, Retrievals: []RetrievalRecord{},
			Engines: []EngineCall{}, Reviews: []ReviewRecord{},
		},
		protected: protected,
	}
	err := store.persistLocked(store.records[runID])
	store.emitLocked("journey.started", map[string]any{
		"run_id": runID, "request_id": requestID, "trace_id": traceID,
		"capture_status": capture.Status,
	})
	store.mu.Unlock()
	if err != nil {
		return nil, err
	}
	if ctx == nil {
		ctx = context.Background()
	}
	return &Recorder{
		store: store, runID: runID, ctx: ctx,
		lifecycleStarted: map[string]time.Time{},
	}, nil
}

// ObserveLifecycle projects only closed, low-cardinality orchestration metadata into the public
// timeline, Loki JSONL stream, and Tempo trace. Invalid or mismatched events fail closed.
func (recorder *Recorder) ObserveLifecycle(ctx context.Context, event orchestrator.Event) {
	if recorder == nil || recorder.store == nil || event.RunID != recorder.runID {
		return
	}
	projected, ok := projectLifecycleEvent(event)
	if !ok {
		return
	}
	if ctx == nil {
		ctx = recorder.ctx
	}
	startedAt := projected.At
	key := projected.EventType + "\x00" + projected.StepID
	recorder.lifecycleMu.Lock()
	if projected.Status == "started" {
		recorder.lifecycleStarted[key] = projected.At
	} else if candidate, exists := recorder.lifecycleStarted[key]; exists {
		startedAt = candidate
		delete(recorder.lifecycleStarted, key)
	}
	recorder.lifecycleMu.Unlock()
	if projected.At.Before(startedAt) {
		startedAt = projected.At
	}

	if projected.Status != "started" {
		attributes := []attribute.KeyValue{
			attribute.String("signalforge.run_id", recorder.runID),
			attribute.String("signalforge.step_id", projected.StepID),
			attribute.String("signalforge.event_type", projected.EventType),
			attribute.String("signalforge.status", projected.Status),
		}
		if projected.Wave > 0 {
			attributes = append(attributes, attribute.Int("signalforge.wave", projected.Wave))
		}
		if projected.ConcurrencyLimit > 0 {
			attributes = append(attributes,
				attribute.Int("signalforge.concurrency_limit", projected.ConcurrencyLimit))
		}
		if projected.RoleID != "" {
			attributes = append(attributes,
				attribute.String("signalforge.role_id", projected.RoleID),
				attribute.String("signalforge.role_class", roleClass(projected.RoleID)),
			)
		}
		if projected.RouteReasonCode != "" {
			attributes = append(attributes,
				attribute.String("signalforge.route_reason_code", projected.RouteReasonCode))
		}
		_, span := otel.Tracer("signalforge/orchestration").Start(
			ctx,
			"signalforge."+projected.EventType,
			trace.WithTimestamp(startedAt),
			trace.WithAttributes(attributes...),
		)
		if projected.Status == "failed" || projected.Status == "cancelled" {
			span.SetStatus(codes.Error, projected.Status)
			span.RecordError(errors.New(projected.Status))
		}
		span.End(trace.WithTimestamp(projected.At))
	}

	recorder.store.mu.Lock()
	defer recorder.store.mu.Unlock()
	record, exists := recorder.store.records[recorder.runID]
	if !exists || timelineContains(record.public.Timeline, projected.Sequence) {
		return
	}
	record.public.Timeline = append(record.public.Timeline, projected)
	sort.Slice(record.public.Timeline, func(i, j int) bool {
		return record.public.Timeline[i].Sequence < record.public.Timeline[j].Sequence
	})
	if len(record.public.Timeline) > maxTimelineItems {
		record.public.Timeline = append([]LifecycleEvent(nil),
			record.public.Timeline[len(record.public.Timeline)-maxTimelineItems:]...)
	}
	recorder.store.emitLocked(
		"orchestration."+projected.EventType,
		lifecycleLogFields(recorder.runID, record.public.TraceID, projected),
	)
	_ = recorder.store.persistLocked(record)
}

func projectLifecycleEvent(event orchestrator.Event) (LifecycleEvent, bool) {
	if event.Sequence <= 0 || event.At.IsZero() || !safeIdentity.MatchString(event.RunID) ||
		event.StepID != "" && !safeIdentity.MatchString(event.StepID) ||
		!allowedLifecyclePair(event.Type, event.Status) {
		return LifecycleEvent{}, false
	}
	result := LifecycleEvent{
		Sequence: event.Sequence, StepID: event.StepID, EventType: event.Type,
		Status: event.Status, At: event.At.UTC(),
	}
	result.Wave = boundedAttributeInt(event.Attributes["wave"], 0, 64)
	result.Attempt = boundedAttributeInt(event.Attributes["attempt"], 0, 16)
	result.SpecialistCount = boundedAttributeInt(event.Attributes["specialist_count"], 0, 64)
	result.ConcurrencyLimit = boundedAttributeInt(event.Attributes["concurrency_limit"], 0, 4)
	result.SucceededCount = boundedAttributeInt(event.Attributes["succeeded_count"], 0, 64)
	result.FailedCount = boundedAttributeInt(event.Attributes["failed_count"], 0, 64)
	result.ObservedConcurrency = boundedAttributeInt(event.Attributes["observed_concurrency"], 0, 4)
	for source, target := range map[string]*string{
		"role_id": &result.RoleID, "route": &result.Route,
		"route_reason_code": &result.RouteReasonCode, "code": &result.FailureCode,
	} {
		value := strings.TrimSpace(event.Attributes[source])
		if value != "" && safeIdentity.MatchString(value) {
			*target = value
		}
	}
	return result, true
}

func allowedLifecyclePair(eventType, status string) bool {
	allowed := map[string]map[string]bool{
		"interpretation": {"completed": true, "clarification_required": true},
		"planning":       {"completed": true}, "plan": {"accepted": true},
		"wave":      {"started": true, "completed": true, "degraded": true, "failed": true},
		"context":   {"started": true, "completed": true, "failed": true},
		"retrieval": {"started": true, "passed": true, "completed": true, "degraded": true, "failed": true, "unavailable": true},
		"tool":      {"started": true, "passed": true, "completed": true, "failed": true, "unavailable": true},
		"review":    {"started": true, "approve": true, "reject": true, "repair_requested": true, "narrowed": true, "approved_subset": true, "repair_unresolved": true},
		"synthesis": {"started": true, "passed": true, "completed": true},
		"run":       {"completed": true, "failed": true},
		"retention": {"not_requested": true, "requested": true, "approved": true, "saved": true, "unavailable": true, "failed": true, "deleted": true},
		"workspace": {"completed": true, "cancelled": true, "failed": true},
	}
	return allowed[eventType][status]
}

func boundedAttributeInt(value string, minimum, maximum int) int {
	parsed, err := strconv.Atoi(strings.TrimSpace(value))
	if err != nil || parsed < minimum || parsed > maximum {
		return 0
	}
	return parsed
}

func timelineContains(items []LifecycleEvent, sequence int) bool {
	for _, item := range items {
		if item.Sequence == sequence {
			return true
		}
	}
	return false
}

func lifecycleLogFields(runID, traceID string, event LifecycleEvent) map[string]any {
	fields := map[string]any{
		"run_id": runID, "trace_id": traceID, "sequence": event.Sequence,
		"step_id": event.StepID, "event_type": event.EventType, "status": event.Status,
	}
	if event.Wave > 0 {
		fields["wave"] = event.Wave
	}
	if event.RoleID != "" {
		fields["role_id"] = event.RoleID
		fields["role_class"] = roleClass(event.RoleID)
	}
	if event.Route != "" {
		fields["route"] = event.Route
	}
	if event.SpecialistCount > 0 {
		fields["specialist_count"] = event.SpecialistCount
	}
	if event.ConcurrencyLimit > 0 {
		fields["concurrency_limit"] = event.ConcurrencyLimit
	}
	if event.SucceededCount > 0 {
		fields["succeeded_count"] = event.SucceededCount
	}
	if event.FailedCount > 0 {
		fields["failed_count"] = event.FailedCount
	}
	return fields
}

func (recorder *Recorder) ObserveModelCall(ctx context.Context, roleID, providerID string, request benchmark.Request, completion benchmark.Completion, callErr error) {
	if recorder == nil || recorder.store == nil {
		return
	}
	sequence := recorder.counter.Add(1)
	systemPrompt := ""
	if len(request.Messages) > 0 {
		systemPrompt = request.Messages[0].Content
	}
	requestPayload, _ := json.Marshal(request)
	responseSchema, _ := json.Marshal(request.ResponseFormat)
	responsePayload := []byte(completion.Answer)
	callID := fmt.Sprintf("call-%s-%03d", digestString(recorder.runID + ":" + roleID + ":" + fmt.Sprint(sequence))[:16], sequence)
	promptID := "prompt-" + digestBytes(requestPayload)[:20]
	status, failureCode := "completed", ""
	if callErr != nil {
		status, failureCode = "failed", "model_call_failed"
	}
	startedAt := completion.StartedAt
	if startedAt.IsZero() {
		startedAt = recorder.store.config.Now()
	}
	if ctx == nil {
		ctx = recorder.ctx
	}
	_, span := otel.Tracer("signalforge/intelligence").Start(ctx, "signalforge.model.complete",
		trace.WithTimestamp(startedAt),
		trace.WithAttributes(
			attribute.String("signalforge.run_id", recorder.runID),
			attribute.String("signalforge.role_id", roleID),
			attribute.String("signalforge.role_class", roleClass(roleID)),
			attribute.String("signalforge.provider_id", providerID),
			attribute.String("signalforge.route", routeForProvider(providerID)),
			attribute.String("gen_ai.request.model", request.Model),
			attribute.Int("gen_ai.usage.input_tokens", completion.Usage.PromptTokens),
			attribute.Int("gen_ai.usage.output_tokens", completion.Usage.CompletionTokens),
		))
	if callErr != nil {
		span.SetStatus(codes.Error, "model_call_failed")
		span.RecordError(errors.New("model_call_failed"))
	}
	endedAt := startedAt.Add(completion.Duration)
	if completion.Duration <= 0 {
		endedAt = recorder.store.config.Now()
	}
	span.End(trace.WithTimestamp(endedAt))
	spanContext := trace.SpanContextFromContext(ctx)
	call := ModelCall{
		ModelCallID: callID, StepID: stepForRole(roleID), RoleID: roleID,
		RoleClass: roleClass(roleID), ProviderID: providerID, ModelID: request.Model,
		Route:            routeForProvider(providerID),
		PromptTemplateID: roleID + "@signalforge-role-prompts/v12",
		PromptInstanceID: promptID, SystemPromptSHA: digestString(systemPrompt),
		RequestPayloadSHA: digestBytes(requestPayload), ResponseSchemaSHA: digestBytes(responseSchema),
		InputTokens: completion.Usage.PromptTokens, OutputTokens: completion.Usage.CompletionTokens,
		MaxOutputTokens: request.MaxTokens, StartedAt: startedAt,
		DurationMS: milliseconds(completion.Duration), TTFTMS: milliseconds(completion.TTFT),
		FinishReason: completion.FinishReason, Status: status, FailureCode: failureCode,
	}
	if len(responsePayload) > 0 {
		call.ResponseSHA = digestBytes(responsePayload)
	}

	recorder.store.mu.Lock()
	defer recorder.store.mu.Unlock()
	record, ok := recorder.store.records[recorder.runID]
	if !ok {
		return
	}
	if spanContext.IsValid() {
		record.public.TraceID = spanContext.TraceID().String()
	}
	if recorder.store.config.Enabled && record.public.Capture.Status == "active" {
		protected := ProtectedModelCall{
			ModelCallID: callID, PromptInstanceID: promptID,
			ResponseFormat: cloneMap(request.ResponseFormat),
			Parameters: ModelParameters{
				Model: request.Model, MaxTokens: request.MaxTokens,
				Temperature: request.Temperature, Stream: request.Stream,
			},
			RawOutput: redact(completion.Answer),
		}
		for _, message := range request.Messages {
			protected.Messages = append(protected.Messages, SafeMessage{Role: message.Role, Content: redact(message.Content)})
		}
		candidate := append(append([]ProtectedModelCall(nil), record.protected.ModelCalls...), protected)
		encoded, _ := json.Marshal(candidate)
		if int64(len(encoded)) <= recorder.store.config.MaxBytes {
			record.protected.ModelCalls = candidate
			record.public.Capture.StoredBytes = int64(len(encoded))
			call.ProtectedInputID = "input-" + promptID
			if call.ResponseSHA != "" {
				call.ProtectedOutputID = "output-" + call.ResponseSHA[:20]
			}
		} else {
			record.public.Capture.Available = false
			record.public.Capture.Status = "capacity_exceeded"
		}
	}
	record.public.ModelCalls = append(record.public.ModelCalls, call)
	recorder.store.emitLocked("model.completed", map[string]any{
		"run_id": recorder.runID, "trace_id": record.public.TraceID,
		"model_call_id": call.ModelCallID, "role_id": call.RoleID,
		"role_class": call.RoleClass, "provider_id": call.ProviderID,
		"route": call.Route, "status": call.Status, "failure_code": call.FailureCode,
		"input_tokens": call.InputTokens, "output_tokens": call.OutputTokens,
		"duration_ms": call.DurationMS, "ttft_ms": call.TTFTMS,
	})
	_ = recorder.store.persistLocked(record)
}

func (recorder *Recorder) Complete(input ProjectionInput) error {
	if recorder == nil || recorder.store == nil {
		return nil
	}
	recorder.store.mu.Lock()
	defer recorder.store.mu.Unlock()
	record, ok := recorder.store.records[recorder.runID]
	if !ok {
		return errors.New("intelligence audit run is unavailable")
	}
	completed := input.CompletedAt
	if completed.IsZero() {
		completed = recorder.store.config.Now()
	}
	record.public.CompletedAt = &completed
	record.public.Status = input.Status
	if record.public.Status == "" {
		record.public.Status = "completed"
	}
	record.public.Retrievals = append([]RetrievalRecord{}, input.Retrievals...)
	for index := range record.public.Retrievals {
		record.public.Retrievals[index].EvidenceIDs =
			append([]string{}, record.public.Retrievals[index].EvidenceIDs...)
	}
	record.public.Engines = append([]EngineCall{}, input.Engines...)
	for index := range record.public.Engines {
		record.public.Engines[index].InputRefs =
			append([]string{}, record.public.Engines[index].InputRefs...)
		record.public.Engines[index].OutputRefs =
			append([]string{}, record.public.Engines[index].OutputRefs...)
	}
	record.public.Reviews = append([]ReviewRecord{}, input.Reviews...)
	record.public.Release = cloneRelease(input.Release)
	if recorder.store.config.Enabled && record.public.Capture.Status == "active" {
		record.protected.Receipts = append([]ProtectedReceipt(nil), input.Receipts...)
		encoded, _ := json.Marshal(record.protected)
		if int64(len(encoded)) > recorder.store.config.MaxBytes {
			record.protected.Receipts = nil
			record.public.Capture.Available = false
			record.public.Capture.Status = "capacity_exceeded"
		} else {
			record.public.Capture.StoredBytes = int64(len(encoded))
		}
	}
	recorder.store.emitLocked("journey.completed", map[string]any{
		"run_id": recorder.runID, "trace_id": record.public.TraceID,
		"status": record.public.Status, "model_calls": len(record.public.ModelCalls),
		"retrievals": len(record.public.Retrievals), "engine_calls": len(record.public.Engines),
		"reviews": len(record.public.Reviews), "released": record.public.Release != nil,
	})
	if err := recorder.store.persistLocked(record); err != nil {
		return err
	}
	recorder.store.evictCompletedLocked()
	return nil
}

func (store *Store) evictCompletedLocked() {
	for store.completedRecordCountLocked() > store.config.MaxRecords {
		oldestRunID := ""
		var oldestStartedAt time.Time
		for runID, record := range store.records {
			if record.public.Status == "running" {
				continue
			}
			if oldestRunID == "" || record.public.StartedAt.Before(oldestStartedAt) ||
				record.public.StartedAt.Equal(oldestStartedAt) && runID < oldestRunID {
				oldestRunID = runID
				oldestStartedAt = record.public.StartedAt
			}
		}
		if oldestRunID == "" {
			return
		}
		record := store.records[oldestRunID]
		if err := store.removeIfPresentLocked(store.publicPath(oldestRunID)); err != nil {
			store.emitEvictionFailureLocked(oldestRunID, record.public.TraceID, "public_metadata", err)
			return
		}
		if err := store.removeIfPresentLocked(store.protectedPath(oldestRunID)); err != nil {
			store.emitEvictionFailureLocked(oldestRunID, record.public.TraceID, "protected_capture", err)
			return
		}
		delete(store.records, oldestRunID)
		store.emitLocked("audit.evicted", map[string]any{
			"run_id": oldestRunID, "trace_id": record.public.TraceID,
			"reason": "bounded_completed_history",
		})
	}
}

func (store *Store) completedRecordCountLocked() int {
	count := 0
	for _, record := range store.records {
		if record.public.Status != "running" {
			count++
		}
	}
	return count
}

func (store *Store) removeIfPresentLocked(path string) error {
	err := store.removeFile(path)
	if err == nil || errors.Is(err, os.ErrNotExist) {
		return nil
	}
	return err
}

func (store *Store) emitEvictionFailureLocked(runID, traceID, artifact string, err error) {
	store.emitLocked("audit.eviction_failed", map[string]any{
		"run_id": runID, "trace_id": traceID, "artifact": artifact,
		"reason": "durable_cleanup_failed", "error_class": evictionErrorClass(err),
	})
}

func evictionErrorClass(err error) string {
	switch {
	case errors.Is(err, os.ErrPermission):
		return "permission_denied"
	case errors.Is(err, os.ErrNotExist):
		return "already_absent"
	default:
		return "io_failure"
	}
}

func (store *Store) Public(runID string) (Record, error) {
	store.expire()
	store.mu.RLock()
	defer store.mu.RUnlock()
	record, ok := store.records[runID]
	if !ok {
		return Record{}, os.ErrNotExist
	}
	return clonePublic(record.public), nil
}

func (store *Store) Protected(runID, token string) (ProtectedRecord, error) {
	store.expire()
	if !store.authorized(token) {
		return ProtectedRecord{}, errors.New("audit authorization failed")
	}
	store.mu.RLock()
	defer store.mu.RUnlock()
	record, ok := store.records[runID]
	if !ok {
		return ProtectedRecord{}, os.ErrNotExist
	}
	if !record.public.Capture.Available || record.public.Capture.Status != "active" {
		return ProtectedRecord{}, errors.New("protected audit capture is unavailable")
	}
	return cloneProtected(record.protected), nil
}

func (store *Store) Purge(runID, token string) error {
	if !store.authorized(token) {
		return errors.New("audit authorization failed")
	}
	store.mu.Lock()
	defer store.mu.Unlock()
	record, ok := store.records[runID]
	if !ok {
		return os.ErrNotExist
	}
	record.protected.ModelCalls = nil
	record.protected.Receipts = nil
	record.protected.Question = ""
	record.public.Capture.Available = false
	record.public.Capture.Status = "purged"
	record.public.Capture.StoredBytes = 0
	store.emitLocked("audit.purged", map[string]any{"run_id": runID, "trace_id": record.public.TraceID})
	_ = os.Remove(store.protectedPath(runID))
	return store.persistPublicLocked(record)
}

func (store *Store) Enabled() bool {
	return store.config.Enabled
}

func (store *Store) Snapshot() []Record {
	store.expire()
	store.mu.RLock()
	defer store.mu.RUnlock()
	result := make([]Record, 0, len(store.records))
	for _, record := range store.records {
		result = append(result, clonePublic(record.public))
	}
	sort.Slice(result, func(i, j int) bool {
		return result[i].StartedAt.Before(result[j].StartedAt)
	})
	return result
}

func (store *Store) authorized(token string) bool {
	expected := []byte(strings.TrimSpace(store.config.Token))
	provided := []byte(strings.TrimSpace(token))
	return len(expected) > 0 && len(expected) == len(provided) &&
		subtle.ConstantTimeCompare(expected, provided) == 1
}

func (store *Store) expire() {
	now := store.config.Now()
	store.mu.Lock()
	defer store.mu.Unlock()
	for runID, record := range store.records {
		if record.public.Capture.Status != "active" || now.Before(record.protected.ExpiresAt) {
			continue
		}
		record.protected.ModelCalls = nil
		record.protected.Receipts = nil
		record.protected.Question = ""
		record.public.Capture.Available = false
		record.public.Capture.Status = "expired"
		record.public.Capture.StoredBytes = 0
		store.emitLocked("audit.expired", map[string]any{"run_id": runID, "trace_id": record.public.TraceID})
		_ = os.Remove(store.protectedPath(runID))
		_ = store.persistPublicLocked(record)
	}
}

func (store *Store) persistLocked(record *storedRecord) error {
	if err := store.persistPublicLocked(record); err != nil {
		return err
	}
	if !store.config.Enabled || record.public.Capture.Status != "active" {
		return nil
	}
	return writeJSONAtomic(store.protectedPath(record.public.RunID), record.protected)
}

func (store *Store) persistPublicLocked(record *storedRecord) error {
	return writeJSONAtomic(store.publicPath(record.public.RunID), record.public)
}

func (store *Store) publicPath(runID string) string {
	return filepath.Join(store.config.Directory, runID+".metadata.json")
}

func (store *Store) protectedPath(runID string) string {
	return filepath.Join(store.config.Directory, runID+".protected.json")
}

func writeJSONAtomic(path string, value any) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	payload, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	payload = append(payload, '\n')
	temporary, err := os.CreateTemp(filepath.Dir(path), ".audit-*.tmp")
	if err != nil {
		return err
	}
	name := temporary.Name()
	defer os.Remove(name)
	if err := temporary.Chmod(0o600); err != nil {
		temporary.Close()
		return err
	}
	if _, err := temporary.Write(payload); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	return os.Rename(name, path)
}

func (store *Store) emitLocked(event string, fields map[string]any) {
	if store.config.LogWriter == nil {
		return
	}
	entry := map[string]any{
		"timestamp": store.config.Now().Format(time.RFC3339Nano),
		"severity":  "INFO", "service": "signalforge-workspace",
		"component": "intelligence-audit", "event": event,
	}
	for key, value := range fields {
		entry[key] = value
	}
	payload, err := json.Marshal(entry)
	if err != nil {
		return
	}
	_, _ = store.config.LogWriter.Write(append(payload, '\n'))
}

func clonePublic(record Record) Record {
	payload, _ := json.Marshal(record)
	var result Record
	_ = json.Unmarshal(payload, &result)
	return result
}

func cloneProtected(record ProtectedRecord) ProtectedRecord {
	payload, _ := json.Marshal(record)
	var result ProtectedRecord
	_ = json.Unmarshal(payload, &result)
	return result
}

func cloneRelease(record *ReleaseRecord) *ReleaseRecord {
	if record == nil {
		return nil
	}
	result := *record
	result.SectionTypes = append([]string{}, record.SectionTypes...)
	result.ClaimRefs = append([]string{}, record.ClaimRefs...)
	result.EvidenceRefs = append([]string{}, record.EvidenceRefs...)
	result.ReceiptRefs = append([]string{}, record.ReceiptRefs...)
	return &result
}

func cloneMap(value map[string]any) map[string]any {
	payload, _ := json.Marshal(value)
	result := map[string]any{}
	_ = json.Unmarshal(payload, &result)
	return result
}

func digestString(value string) string {
	return digestBytes([]byte(value))
}

func digestBytes(value []byte) string {
	hash := sha256.Sum256(value)
	return hex.EncodeToString(hash[:])
}

func milliseconds(value time.Duration) float64 {
	return float64(value.Microseconds()) / 1000
}

func routeForProvider(provider string) string {
	if provider == "radeon-vllm" {
		return "provided_radeon_api"
	}
	return "local_rocm"
}

func roleClass(roleID string) string {
	switch {
	case strings.Contains(roleID, "interpreter"):
		return "interpreter"
	case strings.Contains(roleID, "orchestrator"):
		return "planner"
	case strings.Contains(roleID, "critic"), strings.Contains(roleID, "risk"):
		return "review"
	case strings.Contains(roleID, "final"):
		return "synthesis"
	default:
		return "context"
	}
}

func stepForRole(roleID string) string {
	return "model-" + strings.NewReplacer("/", "-", ".", "-", "_", "-").Replace(roleID)
}

var (
	authorizationPattern = regexp.MustCompile(`(?i)authorization\s*[:=]\s*(?:bearer\s+)?[^\s",}]+`)
	secretPattern        = regexp.MustCompile(`(?i)(api[_-]?key|password|secret|bearer)[\s:=]+[^\s",}]+`)
)

func redact(value string) string {
	value = strings.ReplaceAll(value, "\x00", "")
	value = authorizationPattern.ReplaceAllString(value, "Authorization=[REDACTED]")
	return secretPattern.ReplaceAllStringFunc(value, func(match string) string {
		key := strings.FieldsFunc(match, func(r rune) bool {
			return r == ' ' || r == '\t' || r == ':' || r == '='
		})
		if len(key) == 0 {
			return "[REDACTED]"
		}
		return key[0] + "=[REDACTED]"
	})
}

func SortRecord(record *Record) {
	sort.Slice(record.ModelCalls, func(i, j int) bool {
		return record.ModelCalls[i].StartedAt.Before(record.ModelCalls[j].StartedAt)
	})
}
