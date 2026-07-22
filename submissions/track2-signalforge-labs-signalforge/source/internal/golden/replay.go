package golden

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net"
	"net/url"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
)

const SafeDecisionReplaySchemaV1 = "signalforge/safe-decision-replay/v1"

var safeReplayIdentifier = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$`)

type RuntimeProfile struct {
	Attested           bool   `json:"attested"`
	ProfileID          string `json:"profile_id,omitempty"`
	GPUArchitecture    string `json:"gpu_architecture,omitempty"`
	ROCmVersion        string `json:"rocm_version,omitempty"`
	Runtime            string `json:"runtime,omitempty"`
	RuntimeRevision    string `json:"runtime_revision,omitempty"`
	Quantization       string `json:"quantization,omitempty"`
	ModelID            string `json:"model_id,omitempty"`
	ModelRevision      string `json:"model_revision,omitempty"`
	RuntimeEvidenceSHA string `json:"runtime_evidence_sha256,omitempty"`
}

type SafeDecisionReplay struct {
	SchemaVersion string                   `json:"schema_version"`
	ReplayID      string                   `json:"replay_id"`
	ReplaySHA     string                   `json:"replay_sha256"`
	RunID         string                   `json:"run_id"`
	RequestID     string                   `json:"request_id"`
	PlanID        string                   `json:"plan_id"`
	Status        string                   `json:"status"`
	GeneratedAt   time.Time                `json:"generated_at"`
	StartedAt     time.Time                `json:"started_at"`
	CompletedAt   time.Time                `json:"completed_at"`
	LocalOnly     bool                     `json:"local_only"`
	Runtime       RuntimeProfile           `json:"runtime"`
	Routes        []ReplayRouteDecision    `json:"route_decisions"`
	Artifacts     []ReplayArtifact         `json:"artifacts"`
	Claims        []ReplayClaimDisposition `json:"claim_dispositions"`
	Calls         []ReplayCallMetric       `json:"model_calls"`
	Failures      []ReplayFailure          `json:"failures"`
	Metrics       ReplayMetrics            `json:"metrics"`
	Privacy       ReplayPrivacy            `json:"privacy"`
}

type ReplayRouteDecision struct {
	StepID        string    `json:"step_id"`
	Kind          string    `json:"kind"`
	RoleID        string    `json:"role_id"`
	ReasonCode    string    `json:"reason_code"`
	CapabilityIDs []string  `json:"capability_ids,omitempty"`
	Status        string    `json:"status"`
	StartedAt     time.Time `json:"started_at"`
	CompletedAt   time.Time `json:"completed_at"`
	DurationMS    float64   `json:"duration_ms"`
}

type ReplayArtifact struct {
	ArtifactID string `json:"artifact_id"`
	Kind       string `json:"kind"`
	SHA256     string `json:"sha256"`
}

type ReplayClaimDisposition struct {
	ClaimID          string   `json:"claim_id"`
	SourceRole       string   `json:"source_role"`
	Origin           string   `json:"origin"`
	Disposition      string   `json:"disposition"`
	ApprovedBy       []string `json:"approved_by,omitempty"`
	RejectedBy       []string `json:"rejected_by,omitempty"`
	ReleasedSections []string `json:"released_sections,omitempty"`
	EvidenceRefs     []string `json:"evidence_refs,omitempty"`
	ReceiptRefs      []string `json:"receipt_refs,omitempty"`
	NumericalRefs    []string `json:"numerical_refs,omitempty"`
	AssumptionRefs   []string `json:"assumption_refs,omitempty"`
}

type ReplayCallMetric struct {
	RoleID           string  `json:"role_id"`
	DurationMS       float64 `json:"duration_ms"`
	TTFTMS           float64 `json:"ttft_ms"`
	PromptTokens     int     `json:"prompt_tokens"`
	CompletionTokens int     `json:"completion_tokens"`
	FinishReason     string  `json:"finish_reason,omitempty"`
	Failed           bool    `json:"failed"`
}

type ReplayFailure struct {
	FailureID   string `json:"failure_id"`
	StepID      string `json:"step_id"`
	FailureCode string `json:"failure_code"`
	Retryable   bool   `json:"retryable"`
}

type ReplayMetrics struct {
	EndToEndDurationMS        float64 `json:"end_to_end_duration_ms"`
	ModelCalls                int     `json:"model_calls"`
	CallDurationP50MS         float64 `json:"call_duration_p50_ms"`
	CallDurationP95MS         float64 `json:"call_duration_p95_ms"`
	TTFTP50MS                 float64 `json:"ttft_p50_ms"`
	TTFTP95MS                 float64 `json:"ttft_p95_ms"`
	CompletionTokensPerSecond float64 `json:"completion_tokens_per_second"`
	PromptTokens              int     `json:"prompt_tokens"`
	CompletionTokens          int     `json:"completion_tokens"`
	ContextPackets            int     `json:"context_packets"`
	Critiques                 int     `json:"critiques"`
	ReleasedClaims            int     `json:"released_claims"`
	EvidenceCoverage          float64 `json:"evidence_coverage"`
	MaxConcurrentContext      int     `json:"max_concurrent_context"`
}

type ReplayPrivacy struct {
	PromptBodiesExcluded    bool `json:"prompt_bodies_excluded"`
	ResponseBodiesExcluded  bool `json:"response_bodies_excluded"`
	ChainOfThoughtExcluded  bool `json:"chain_of_thought_excluded"`
	FailureMessagesExcluded bool `json:"failure_messages_excluded"`
}

func BuildSafeDecisionReplay(report Report, profile RuntimeProfile) (SafeDecisionReplay, error) {
	status := "completed"
	if report.Result.Failure != nil {
		status = "failed"
	}
	replay := SafeDecisionReplay{
		SchemaVersion: SafeDecisionReplaySchemaV1,
		ReplayID:      "replay-" + report.Request.RunID,
		RunID:         report.Request.RunID,
		RequestID:     report.Request.RequestID,
		PlanID:        report.Result.Trace.PlanID,
		Status:        status,
		GeneratedAt:   report.GeneratedAt,
		StartedAt:     report.Result.Trace.StartedAt,
		CompletedAt:   report.Result.Trace.CompletedAt,
		LocalOnly:     loopbackURL(report.LocalBaseURL),
		Runtime:       profile,
		Routes:        replayRoutes(report.Result.Trace),
		Artifacts:     replayArtifacts(report),
		Claims:        replayClaims(report.Result),
		Calls:         replayCalls(report.Calls),
		Failures:      replayFailures(report.Result),
		Privacy: ReplayPrivacy{
			PromptBodiesExcluded: true, ResponseBodiesExcluded: true,
			ChainOfThoughtExcluded: true, FailureMessagesExcluded: true,
		},
	}
	replay.Metrics = replayMetrics(report, replay)
	hash, err := hashReplay(replay)
	if err != nil {
		return SafeDecisionReplay{}, err
	}
	replay.ReplaySHA = hash
	if err := ValidateSafeDecisionReplay(replay); err != nil {
		return SafeDecisionReplay{}, err
	}
	return replay, nil
}

func ValidateSafeDecisionReplay(replay SafeDecisionReplay) error {
	if replay.SchemaVersion != SafeDecisionReplaySchemaV1 || !safeID(replay.ReplayID) || !safeID(replay.RunID) || !safeID(replay.RequestID) || !safeID(replay.PlanID) {
		return errors.New("safe replay identity is incomplete")
	}
	if replay.Status != "completed" && replay.Status != "failed" {
		return fmt.Errorf("unsupported safe replay status %q", replay.Status)
	}
	if replay.GeneratedAt.IsZero() || replay.StartedAt.IsZero() || replay.CompletedAt.Before(replay.StartedAt) {
		return errors.New("safe replay timestamps are invalid")
	}
	if replay.GeneratedAt.Before(replay.CompletedAt) {
		return errors.New("safe replay generation predates run completion")
	}
	if !replay.LocalOnly {
		return errors.New("safe replay requires a loopback-local inference endpoint")
	}
	if !isSHA256(replay.ReplaySHA) {
		return errors.New("safe replay hash is invalid")
	}
	expected, err := hashReplay(replay)
	if err != nil || expected != replay.ReplaySHA {
		return errors.New("safe replay hash does not match its content")
	}
	if replay.Runtime.Attested {
		if !safeID(replay.Runtime.ProfileID) || !safeID(replay.Runtime.GPUArchitecture) || replay.Runtime.ROCmVersion == "" || !safeID(replay.Runtime.Runtime) || replay.Runtime.RuntimeRevision == "" || replay.Runtime.Quantization == "" || !safeID(replay.Runtime.ModelID) || replay.Runtime.ModelRevision == "" || !isSHA256(replay.Runtime.RuntimeEvidenceSHA) {
			return errors.New("attested runtime profile is incomplete")
		}
	}
	allowedReasons := map[string]bool{
		"intent_requires_specialist": true, "evidence_release_gate": true,
		"risk_contrarian_gate": true, "independent_review_gate": true,
		"single_release_authority": true,
	}
	if len(replay.Routes) == 0 {
		return errors.New("safe replay has no route decisions")
	}
	for _, route := range replay.Routes {
		if !safeID(route.StepID) || !safeID(route.Kind) || !safeID(route.RoleID) || !allowedReasons[route.ReasonCode] || route.Status == "" || route.CompletedAt.Before(route.StartedAt) || route.CompletedAt.After(replay.CompletedAt) || !finiteNonNegative(route.DurationMS) {
			return fmt.Errorf("invalid replay route %q", route.StepID)
		}
		for _, capabilityID := range route.CapabilityIDs {
			if !safeID(capabilityID) {
				return fmt.Errorf("route %q has unsafe capability identity", route.StepID)
			}
		}
	}
	seenArtifacts := map[string]bool{}
	for _, artifact := range replay.Artifacts {
		key := artifact.Kind + "\x00" + artifact.ArtifactID
		if !safeID(artifact.ArtifactID) || !safeID(artifact.Kind) || !isSHA256(artifact.SHA256) || seenArtifacts[key] {
			return fmt.Errorf("invalid replay artifact %q", artifact.ArtifactID)
		}
		seenArtifacts[key] = true
	}
	allowedDispositions := map[string]bool{"released": true, "rejected": true, "approved_not_released": true, "not_released": true}
	for _, claim := range replay.Claims {
		if !safeID(claim.ClaimID) || !safeID(claim.SourceRole) || !safeID(claim.Origin) || !allowedDispositions[claim.Disposition] {
			return fmt.Errorf("invalid replay claim %q", claim.ClaimID)
		}
		for _, values := range [][]string{claim.ApprovedBy, claim.RejectedBy, claim.ReleasedSections, claim.EvidenceRefs, claim.ReceiptRefs, claim.NumericalRefs} {
			for _, value := range values {
				if !safeID(value) {
					return fmt.Errorf("claim %q contains an unsafe reference", claim.ClaimID)
				}
			}
		}
	}
	for _, call := range replay.Calls {
		if !safeID(call.RoleID) || !finiteNonNegative(call.DurationMS) || !finiteNonNegative(call.TTFTMS) || call.PromptTokens < 0 || call.CompletionTokens < 0 || !safeID(call.FinishReason) {
			return fmt.Errorf("invalid replay model-call metric for %q", call.RoleID)
		}
	}
	for _, failure := range replay.Failures {
		if !safeID(failure.FailureID) || !safeID(failure.StepID) || !safeID(failure.FailureCode) {
			return fmt.Errorf("invalid replay failure %q", failure.FailureID)
		}
	}
	if !validReplayMetrics(replay.Metrics) || replay.Metrics.ModelCalls != len(replay.Calls) {
		return errors.New("safe replay metrics are invalid")
	}
	if !replay.Privacy.PromptBodiesExcluded || !replay.Privacy.ResponseBodiesExcluded || !replay.Privacy.ChainOfThoughtExcluded || !replay.Privacy.FailureMessagesExcluded {
		return errors.New("safe replay privacy guarantees are incomplete")
	}
	return nil
}

func replayRoutes(trace orchestrator.Trace) []ReplayRouteDecision {
	routes := make([]ReplayRouteDecision, 0)
	for index, event := range trace.Events {
		if event.Status != "started" || (event.Type != "context" && event.Type != "review" && event.Type != "synthesis") {
			continue
		}
		terminal := event
		terminal.Status = "incomplete"
		terminal.At = trace.CompletedAt
		for _, candidate := range trace.Events[index+1:] {
			if candidate.StepID != event.StepID {
				continue
			}
			if candidate.Type == event.Type && candidate.Status != "started" {
				terminal = candidate
			}
			if event.Type == "synthesis" && candidate.Type == "run" {
				terminal = candidate
			}
		}
		capabilities := splitCodes(event.Attributes["capability_ids"])
		routes = append(routes, ReplayRouteDecision{
			StepID: event.StepID, Kind: event.Type, RoleID: event.Attributes["role_id"],
			ReasonCode: event.Attributes["route_reason_code"], CapabilityIDs: capabilities,
			Status: terminal.Status, StartedAt: event.At, CompletedAt: terminal.At,
			DurationMS: milliseconds(terminal.At.Sub(event.At)),
		})
	}
	return routes
}

func replayArtifacts(report Report) []ReplayArtifact {
	artifacts := make([]ReplayArtifact, 0)
	seen := map[string]bool{}
	add := func(kind, id, digest string) {
		key := kind + "\x00" + id
		if id == "" || !isSHA256(digest) || seen[key] {
			return
		}
		seen[key] = true
		artifacts = append(artifacts, ReplayArtifact{ArtifactID: id, Kind: kind, SHA256: digest})
	}
	addJSON := func(kind, id string, value any) {
		digest, err := hashJSON(value)
		if err == nil {
			add(kind, id, digest)
		}
	}
	addJSON("research_request", report.Request.RequestID, report.Request)
	addJSON("orchestration_trace", report.Result.Trace.RunID, report.Result.Trace)
	for _, packet := range report.Result.Packets {
		addJSON("context_packet", packet.PacketID, packet)
		for _, evidence := range packet.Evidence {
			add("source_evidence", evidence.EvidenceID, evidence.ContentSHA)
		}
		for _, receipt := range packet.CalculationReceipts {
			add("calculation_receipt", receipt.ReceiptID, receipt.ReceiptSHA)
		}
	}
	for _, critique := range report.Result.Critiques {
		addJSON("critique_report", critique.ReportID, critique)
	}
	if report.Result.Answer != nil {
		addJSON("final_answer", report.Result.Answer.AnswerID, report.Result.Answer)
	}
	if report.Result.Failure != nil {
		addJSON("failure_receipt", report.Result.Failure.FailureID, report.Result.Failure)
	}
	for _, failure := range report.Result.ContextFailures {
		addJSON("failure_receipt", failure.FailureID, failure)
	}
	sort.Slice(artifacts, func(i, j int) bool {
		if artifacts[i].Kind == artifacts[j].Kind {
			return artifacts[i].ArtifactID < artifacts[j].ArtifactID
		}
		return artifacts[i].Kind < artifacts[j].Kind
	})
	return artifacts
}

func replayClaims(result orchestrator.Result) []ReplayClaimDisposition {
	type claimState struct {
		role, origin                               string
		evidence, receipts, numerical, assumptions []string
	}
	states := map[string]claimState{}
	for _, packet := range result.Packets {
		for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
			origin := string(finding.Origin)
			if origin == "" {
				origin = "model"
			}
			states[finding.ClaimID] = claimState{
				role: packet.SpecialistRole, origin: origin,
				evidence: sortedUnique(finding.EvidenceRefs), receipts: sortedUnique(finding.CalculationRefs), numerical: sortedUnique(finding.NumericalRefs),
				assumptions: sortedUnique(finding.AssumptionRefs),
			}
		}
	}
	latest := map[string]contracts.CritiqueReport{}
	for _, critique := range result.Critiques {
		latest[critique.ReviewerRole] = critique
		for _, claimID := range append(append([]string(nil), critique.ApprovedClaims...), critique.RejectedClaims...) {
			if _, ok := states[claimID]; !ok {
				states[claimID] = claimState{role: "unknown", origin: "unknown"}
			}
		}
	}
	approved, rejected := map[string][]string{}, map[string][]string{}
	for roleID, critique := range latest {
		for _, claimID := range critique.ApprovedClaims {
			approved[claimID] = append(approved[claimID], roleID)
		}
		for _, claimID := range critique.RejectedClaims {
			rejected[claimID] = append(rejected[claimID], roleID)
		}
	}
	released := map[string][]string{}
	if result.Answer != nil {
		for _, section := range result.Answer.Sections {
			for _, claimID := range section.ClaimRefs {
				released[claimID] = append(released[claimID], section.SectionType)
				if _, ok := states[claimID]; !ok {
					states[claimID] = claimState{role: "unknown", origin: "unknown"}
				}
			}
		}
	}
	ids := make([]string, 0, len(states))
	for claimID := range states {
		ids = append(ids, claimID)
	}
	sort.Strings(ids)
	claims := make([]ReplayClaimDisposition, 0, len(ids))
	for _, claimID := range ids {
		state := states[claimID]
		disposition := "not_released"
		if len(released[claimID]) > 0 {
			disposition = "released"
		} else if len(rejected[claimID]) > 0 {
			disposition = "rejected"
		} else if len(latest) > 0 && len(approved[claimID]) == len(latest) {
			disposition = "approved_not_released"
		}
		claims = append(claims, ReplayClaimDisposition{
			ClaimID: claimID, SourceRole: state.role, Origin: state.origin, Disposition: disposition,
			ApprovedBy: sortedUnique(approved[claimID]), RejectedBy: sortedUnique(rejected[claimID]),
			ReleasedSections: sortedUnique(released[claimID]), EvidenceRefs: state.evidence,
			ReceiptRefs: state.receipts, NumericalRefs: state.numerical, AssumptionRefs: state.assumptions,
		})
	}
	return claims
}

func replayCalls(calls []CallMetric) []ReplayCallMetric {
	result := make([]ReplayCallMetric, 0, len(calls))
	for _, call := range calls {
		result = append(result, ReplayCallMetric{
			RoleID: call.RoleID, DurationMS: milliseconds(call.Duration), TTFTMS: milliseconds(call.TTFT),
			PromptTokens: call.PromptTokens, CompletionTokens: call.CompletionTokens,
			FinishReason: safeFinishReason(call.FinishReason), Failed: call.Failed,
		})
	}
	return result
}

func safeFinishReason(value string) string {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "stop", "length", "tool_calls", "content_filter", "error", "cancelled":
		return strings.ToLower(strings.TrimSpace(value))
	default:
		return "other"
	}
}

func replayFailures(result orchestrator.Result) []ReplayFailure {
	all := append([]contracts.FailureReceipt(nil), result.ContextFailures...)
	if result.Failure != nil {
		all = append(all, *result.Failure)
	}
	failures := make([]ReplayFailure, 0, len(all))
	for _, failure := range all {
		failures = append(failures, ReplayFailure{
			FailureID: failure.FailureID, StepID: failure.StepID,
			FailureCode: failure.FailureCode, Retryable: failure.Retryable,
		})
	}
	sort.Slice(failures, func(i, j int) bool { return failures[i].FailureID < failures[j].FailureID })
	return failures
}

func replayMetrics(report Report, replay SafeDecisionReplay) ReplayMetrics {
	durations, ttfts := make([]float64, 0, len(report.Calls)), make([]float64, 0, len(report.Calls))
	totalSeconds := 0.0
	released := 0
	for _, call := range report.Calls {
		durationMS := milliseconds(call.Duration)
		durations = append(durations, durationMS)
		ttfts = append(ttfts, milliseconds(call.TTFT))
		totalSeconds += call.Duration.Seconds()
	}
	for _, claim := range replay.Claims {
		if claim.Disposition == "released" {
			released++
		}
	}
	throughput := 0.0
	if totalSeconds > 0 {
		throughput = float64(report.Metrics.CompletionTokens) / totalSeconds
	}
	return ReplayMetrics{
		EndToEndDurationMS: report.Metrics.DurationMS, ModelCalls: report.Metrics.ModelCalls,
		CallDurationP50MS: percentile(durations, 0.50), CallDurationP95MS: percentile(durations, 0.95),
		TTFTP50MS: percentile(ttfts, 0.50), TTFTP95MS: percentile(ttfts, 0.95),
		CompletionTokensPerSecond: throughput, PromptTokens: report.Metrics.PromptTokens,
		CompletionTokens: report.Metrics.CompletionTokens, ContextPackets: report.Metrics.ContextPackets,
		Critiques: report.Metrics.Critiques, ReleasedClaims: released,
		EvidenceCoverage: report.Metrics.EvidenceCoverage, MaxConcurrentContext: report.Metrics.MaxConcurrentContext,
	}
}

func hashReplay(replay SafeDecisionReplay) (string, error) {
	replay.ReplaySHA = ""
	return hashJSON(replay)
}

func hashJSON(value any) (string, error) {
	payload, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(payload)
	return hex.EncodeToString(digest[:]), nil
}

func loopbackURL(raw string) bool {
	parsed, err := url.Parse(raw)
	if err != nil {
		return false
	}
	host := parsed.Hostname()
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func splitCodes(value string) []string {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return sortedUnique(strings.Split(value, ","))
}

func sortedUnique(values []string) []string {
	seen := map[string]bool{}
	result := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value != "" && !seen[value] {
			seen[value] = true
			result = append(result, value)
		}
	}
	sort.Strings(result)
	return result
}

func percentile(values []float64, p float64) float64 {
	if len(values) == 0 {
		return 0
	}
	copyValues := append([]float64(nil), values...)
	sort.Float64s(copyValues)
	index := int(math.Ceil(p*float64(len(copyValues)))) - 1
	if index < 0 {
		index = 0
	}
	if index >= len(copyValues) {
		index = len(copyValues) - 1
	}
	return copyValues[index]
}

func milliseconds(duration time.Duration) float64 {
	return float64(duration.Microseconds()) / 1000
}

func safeID(value string) bool {
	return safeReplayIdentifier.MatchString(value)
}

func finiteNonNegative(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0) && value >= 0
}

func validReplayMetrics(metrics ReplayMetrics) bool {
	for _, value := range []float64{
		metrics.EndToEndDurationMS,
		metrics.CallDurationP50MS,
		metrics.CallDurationP95MS,
		metrics.TTFTP50MS,
		metrics.TTFTP95MS,
		metrics.CompletionTokensPerSecond,
		metrics.EvidenceCoverage,
	} {
		if !finiteNonNegative(value) {
			return false
		}
	}
	if metrics.EvidenceCoverage > 1 {
		return false
	}
	for _, value := range []int{
		metrics.ModelCalls,
		metrics.PromptTokens,
		metrics.CompletionTokens,
		metrics.ContextPackets,
		metrics.Critiques,
		metrics.ReleasedClaims,
		metrics.MaxConcurrentContext,
	} {
		if value < 0 {
			return false
		}
	}
	return true
}

func isSHA256(value string) bool {
	if len(value) != sha256.Size*2 {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil && strings.ToLower(value) == value
}
