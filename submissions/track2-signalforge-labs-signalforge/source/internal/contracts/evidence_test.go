package contracts

import (
	"strings"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/runid"
)

func TestRunIdentityLinksManifestBenchmarkTraceAndDemo(t *testing.T) {
	now := time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC)
	id, err := runid.New(now)
	if err != nil {
		t.Fatal(err)
	}
	hash := strings.Repeat("a", 64)
	manifest := EvidenceManifest{
		SchemaVersion: SchemaVersionV1, RunID: id, CodeCommit: "abc123", CodeTreeSHA: hash, CreatedAt: now,
		Runtime:     RuntimeIdentity{OS: "linux", Architecture: "amd64"},
		Artifacts:   []EvidenceArtifact{{ArtifactID: "report", Kind: "report", Path: "report.json", SHA256: hash}},
		ManifestSHA: hash,
	}
	if err := ValidateEvidenceManifest(manifest); err != nil {
		t.Fatal(err)
	}
	row := BenchmarkRow{
		SchemaVersion: SchemaVersionV1, RunID: id, BenchmarkID: "bench-1", CaseID: "case-1",
		WorkloadClass: "routing", StartedAt: now, DurationMS: 1, Success: true, ArtifactRefs: []string{"report"},
	}
	if err := ValidateBenchmarkRow(row); err != nil {
		t.Fatal(err)
	}
	completed := now.Add(time.Second)
	trace := ResearchTrace{
		SchemaVersion: SchemaVersionV1, RunID: id, RequestID: "request-1", StartedAt: now,
		CompletedAt: &completed, Status: "success",
		Events: []TraceEvent{{EventID: "event-1", RunID: id, ComponentID: "request-interpreter/v1", EventType: "artifact_created", Status: "success", OccurredAt: now}},
	}
	if err := ValidateResearchTrace(trace); err != nil {
		t.Fatal(err)
	}
	demo := DemoEvidence{
		SchemaVersion: SchemaVersionV1, DemoID: "demo-1", RunID: id, ScenarioID: "golden",
		RecordedAt: now, TraceRef: "trace.json", ManifestRef: "manifest.json", Claims: []string{"local inference"},
	}
	if err := ValidateDemoEvidence(demo); err != nil {
		t.Fatal(err)
	}
}

func TestTraceRejectsSecretMetadataAndMismatchedRun(t *testing.T) {
	now := time.Now().UTC()
	id, _ := runid.New(now)
	other, _ := runid.New(now)
	trace := ResearchTrace{
		SchemaVersion: SchemaVersionV1, RunID: id, RequestID: "request-1", StartedAt: now, Status: "running",
		Events: []TraceEvent{{EventID: "event-1", RunID: other, ComponentID: "component", EventType: "start", Status: "ok", OccurredAt: now}},
	}
	if err := ValidateResearchTrace(trace); err == nil {
		t.Fatal("mismatched event run ID must fail")
	}
	trace.Events[0].RunID = id
	trace.Events[0].SafeMetadata = map[string]string{"api_key": "forbidden"}
	if err := ValidateResearchTrace(trace); err == nil {
		t.Fatal("secret-like metadata key must fail")
	}
}
