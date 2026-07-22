package contracts

import "time"

type RuntimeIdentity struct {
	OS             string `json:"os"`
	Architecture   string `json:"architecture"`
	GoVersion      string `json:"go_version,omitempty"`
	PythonVersion  string `json:"python_version,omitempty"`
	ContainerImage string `json:"container_image,omitempty"`
	ROCmVersion    string `json:"rocm_version,omitempty"`
	EngineVersion  string `json:"engine_version,omitempty"`
}

type GPUIdentity struct {
	Vendor       string `json:"vendor"`
	Product      string `json:"product"`
	Architecture string `json:"architecture,omitempty"`
	VRAMBytes    uint64 `json:"vram_bytes,omitempty"`
	Driver       string `json:"driver,omitempty"`
}

type ModelIdentity struct {
	ModelID         string `json:"model_id"`
	Revision        string `json:"revision"`
	ArtifactSHA256  string `json:"artifact_sha256"`
	TokenizerSHA256 string `json:"tokenizer_sha256,omitempty"`
	Quantization    string `json:"quantization"`
	Runtime         string `json:"runtime"`
}

type DatasetIdentity struct {
	DatasetID      string `json:"dataset_id"`
	Version        string `json:"version"`
	ManifestSHA256 string `json:"manifest_sha256"`
	Split          string `json:"split,omitempty"`
}

type BenchmarkRow struct {
	SchemaVersion string             `json:"schema_version"`
	RunID         string             `json:"run_id"`
	BenchmarkID   string             `json:"benchmark_id"`
	CaseID        string             `json:"case_id"`
	WorkloadClass string             `json:"workload_class"`
	ModelID       string             `json:"model_id,omitempty"`
	StartedAt     time.Time          `json:"started_at"`
	DurationMS    float64            `json:"duration_ms"`
	Success       bool               `json:"success"`
	Quality       map[string]float64 `json:"quality,omitempty"`
	Runtime       map[string]float64 `json:"runtime,omitempty"`
	ArtifactRefs  []string           `json:"artifact_refs"`
}

type TraceEvent struct {
	EventID      string            `json:"event_id"`
	RunID        string            `json:"run_id"`
	ParentID     string            `json:"parent_id,omitempty"`
	ComponentID  string            `json:"component_id"`
	ArtifactID   string            `json:"artifact_id,omitempty"`
	EventType    string            `json:"event_type"`
	Status       string            `json:"status"`
	OccurredAt   time.Time         `json:"occurred_at"`
	DurationMS   int64             `json:"duration_ms,omitempty"`
	SafeMetadata map[string]string `json:"safe_metadata,omitempty"`
}

type ResearchTrace struct {
	SchemaVersion string       `json:"schema_version"`
	RunID         string       `json:"run_id"`
	RequestID     string       `json:"request_id"`
	StartedAt     time.Time    `json:"started_at"`
	CompletedAt   *time.Time   `json:"completed_at,omitempty"`
	Status        string       `json:"status"`
	Events        []TraceEvent `json:"events"`
}

type DemoEvidence struct {
	SchemaVersion string    `json:"schema_version"`
	DemoID        string    `json:"demo_id"`
	RunID         string    `json:"run_id"`
	ScenarioID    string    `json:"scenario_id"`
	RecordedAt    time.Time `json:"recorded_at"`
	VideoSHA256   string    `json:"video_sha256,omitempty"`
	TraceRef      string    `json:"trace_ref"`
	ManifestRef   string    `json:"manifest_ref"`
	Claims        []string  `json:"claims"`
}
