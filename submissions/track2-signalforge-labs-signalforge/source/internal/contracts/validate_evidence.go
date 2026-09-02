package contracts

import (
	"errors"
	"fmt"
	"regexp"
	"strings"

	"github.com/rvbernucci/signalforge/internal/runid"
)

var sha256Pattern = regexp.MustCompile("^[a-f0-9]{64}$")

func ValidateEvidenceManifest(manifest EvidenceManifest) error {
	if manifest.SchemaVersion != SchemaVersionV1 {
		return fmt.Errorf("unsupported schema_version %q", manifest.SchemaVersion)
	}
	if err := validateRunID(manifest.RunID); err != nil {
		return err
	}
	if manifest.CodeCommit == "" || !sha256Pattern.MatchString(manifest.CodeTreeSHA) ||
		manifest.CreatedAt.IsZero() || manifest.Runtime.OS == "" ||
		manifest.Runtime.Architecture == "" || len(manifest.Artifacts) == 0 {
		return errors.New("evidence manifest is incomplete")
	}
	if !sha256Pattern.MatchString(manifest.ManifestSHA) {
		return errors.New("manifest_sha256 must be a lowercase SHA-256 digest")
	}
	seen := map[string]bool{}
	for _, artifact := range manifest.Artifacts {
		if artifact.ArtifactID == "" || artifact.Kind == "" || artifact.Path == "" ||
			!sha256Pattern.MatchString(artifact.SHA256) {
			return fmt.Errorf("invalid artifact %q", artifact.ArtifactID)
		}
		if seen[artifact.ArtifactID] {
			return fmt.Errorf("duplicate artifact %q", artifact.ArtifactID)
		}
		seen[artifact.ArtifactID] = true
	}
	for _, model := range manifest.Models {
		if model.ModelID == "" || model.Revision == "" || model.Quantization == "" ||
			model.Runtime == "" || !sha256Pattern.MatchString(model.ArtifactSHA256) {
			return fmt.Errorf("invalid model identity %q", model.ModelID)
		}
	}
	for _, dataset := range manifest.Datasets {
		if dataset.DatasetID == "" || dataset.Version == "" ||
			!sha256Pattern.MatchString(dataset.ManifestSHA256) {
			return fmt.Errorf("invalid dataset identity %q", dataset.DatasetID)
		}
	}
	return nil
}

func ValidateBenchmarkRow(row BenchmarkRow) error {
	if row.SchemaVersion != SchemaVersionV1 || validateRunID(row.RunID) != nil {
		return errors.New("benchmark row has invalid schema or run ID")
	}
	if row.BenchmarkID == "" || row.CaseID == "" || row.WorkloadClass == "" ||
		row.StartedAt.IsZero() || row.DurationMS < 0 || len(row.ArtifactRefs) == 0 {
		return errors.New("benchmark row is incomplete")
	}
	return nil
}

func ValidateResearchTrace(trace ResearchTrace) error {
	if trace.SchemaVersion != SchemaVersionV1 {
		return fmt.Errorf("unsupported schema_version %q", trace.SchemaVersion)
	}
	if err := validateRunID(trace.RunID); err != nil {
		return err
	}
	if trace.RequestID == "" || trace.StartedAt.IsZero() {
		return errors.New("research trace is incomplete")
	}
	switch trace.Status {
	case "running", "success", "failure", "cancelled":
	default:
		return fmt.Errorf("invalid trace status %q", trace.Status)
	}
	if trace.Status != "running" && trace.CompletedAt == nil {
		return errors.New("completed trace requires completed_at")
	}
	seen := map[string]bool{}
	for _, event := range trace.Events {
		if event.EventID == "" || event.RunID != trace.RunID || event.ComponentID == "" ||
			event.EventType == "" || event.Status == "" || event.OccurredAt.IsZero() {
			return fmt.Errorf("invalid trace event %q", event.EventID)
		}
		if seen[event.EventID] {
			return fmt.Errorf("duplicate trace event %q", event.EventID)
		}
		seen[event.EventID] = true
		for key := range event.SafeMetadata {
			lower := strings.ToLower(key)
			if strings.Contains(lower, "secret") || strings.Contains(lower, "token") ||
				strings.Contains(lower, "password") || strings.Contains(lower, "api_key") {
				return fmt.Errorf("unsafe trace metadata key %q", key)
			}
		}
	}
	return nil
}

func ValidateDemoEvidence(evidence DemoEvidence) error {
	if evidence.SchemaVersion != SchemaVersionV1 {
		return fmt.Errorf("unsupported schema_version %q", evidence.SchemaVersion)
	}
	if err := validateRunID(evidence.RunID); err != nil {
		return err
	}
	if evidence.DemoID == "" || evidence.ScenarioID == "" || evidence.RecordedAt.IsZero() ||
		evidence.TraceRef == "" || evidence.ManifestRef == "" || len(evidence.Claims) == 0 {
		return errors.New("demo evidence is incomplete")
	}
	if evidence.VideoSHA256 != "" && !sha256Pattern.MatchString(evidence.VideoSHA256) {
		return errors.New("video_sha256 is invalid")
	}
	return nil
}

func validateRunID(value string) error {
	if _, err := runid.Timestamp(value); err != nil {
		return fmt.Errorf("invalid run_id: %w", err)
	}
	return nil
}
