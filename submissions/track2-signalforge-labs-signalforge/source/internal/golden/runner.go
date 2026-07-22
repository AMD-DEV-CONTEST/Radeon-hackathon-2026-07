package golden

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/rvbernucci/signalforge/internal/benchmark"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/localagent"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
	"github.com/rvbernucci/signalforge/internal/requestparser"
	"github.com/rvbernucci/signalforge/internal/retrieval"
	"github.com/rvbernucci/signalforge/internal/roles"
	"github.com/rvbernucci/signalforge/internal/taxonomy"
)

const ReportSchemaV1 = "signalforge/golden-investor-report/v1"

const DefaultQuestion = "Compare Microsoft and NVIDIA as long-term businesses under higher-for-longer interest rates and slower AI infrastructure spending. Include business quality, accounting comparability, financial quality, market behavior, DCF valuation ranges, multiples, explicit assumptions, counterevidence, and thesis invalidation conditions."

type RunConfig struct {
	SnapshotPath       string
	RetrievalPath      string
	TraceDir           string
	BaseURL            string
	Model              string
	CodeCommit         string
	Question           string
	RunID              string
	RequestID          string
	Timeout            time.Duration
	Prices             []PriceInput
	HTTPClient         *http.Client
	ContextConcurrency int
	EventSink          orchestrator.EventSink
	RequestOverride    *contracts.ResearchRequest
	Assumptions        []string
	UseAssumptions     bool
}

type CallMetric struct {
	RoleID           string        `json:"role_id"`
	StartedAt        time.Time     `json:"started_at"`
	Duration         time.Duration `json:"duration_ns"`
	TTFT             time.Duration `json:"ttft_ns"`
	PromptTokens     int           `json:"prompt_tokens"`
	CompletionTokens int           `json:"completion_tokens"`
	FinishReason     string        `json:"finish_reason"`
	Failed           bool          `json:"failed"`
	Error            string        `json:"error,omitempty"`
}

type Metrics struct {
	DurationMS              float64 `json:"duration_ms"`
	ModelCalls              int     `json:"model_calls"`
	PromptTokens            int     `json:"prompt_tokens"`
	CompletionTokens        int     `json:"completion_tokens"`
	ContextPackets          int     `json:"context_packets"`
	Critiques               int     `json:"critiques"`
	Claims                  int     `json:"claims"`
	SupportedClaims         int     `json:"supported_claims"`
	EvidenceCoverage        float64 `json:"evidence_coverage"`
	UniqueEvidenceRefs      int     `json:"unique_evidence_refs"`
	UniqueCalculationRefs   int     `json:"unique_calculation_refs"`
	DCFReceipts             int     `json:"dcf_receipts"`
	SensitivityReceipts     int     `json:"sensitivity_receipts"`
	MultipleReceipts        int     `json:"multiple_receipts"`
	RequiredSections        int     `json:"required_sections"`
	PresentRequiredSections int     `json:"present_required_sections"`
	MaxConcurrentContext    int     `json:"max_concurrent_context"`
	FailureSurfaced         bool    `json:"failure_surfaced"`
}

type Acceptance struct {
	CompleteLocalPath     bool `json:"complete_local_path"`
	AllSixSpecialists     bool `json:"all_six_specialists"`
	BothCriticsApproved   bool `json:"both_critics_approved"`
	AllClaimsSupported    bool `json:"all_claims_supported"`
	RequiredSectionsReady bool `json:"required_sections_ready"`
	ScenarioReceiptsReady bool `json:"scenario_receipts_ready"`
	MarketInputsExplicit  bool `json:"market_inputs_explicit"`
}

type Report struct {
	SchemaVersion string                    `json:"schema_version"`
	GeneratedAt   time.Time                 `json:"generated_at"`
	Question      string                    `json:"question"`
	AsOf          time.Time                 `json:"as_of"`
	Model         string                    `json:"model"`
	LocalBaseURL  string                    `json:"local_base_url"`
	Request       contracts.ResearchRequest `json:"request"`
	Result        orchestrator.Result       `json:"result"`
	Calls         []CallMetric              `json:"model_calls"`
	Metrics       Metrics                   `json:"metrics"`
	Acceptance    Acceptance                `json:"acceptance"`
}

func Run(ctx context.Context, config RunConfig) (Report, error) {
	if err := validateRunConfig(config); err != nil {
		return Report{}, err
	}
	snapshot, err := LoadSnapshot(config.SnapshotPath)
	if err != nil {
		return Report{}, fmt.Errorf("load financial snapshot: %w", err)
	}
	_, chunks, err := retrieval.LoadEvalSet(config.RetrievalPath)
	if err != nil {
		return Report{}, fmt.Errorf("load qualitative evidence: %w", err)
	}
	provider, err := NewProvider(snapshot, chunks, config.CodeCommit, config.Prices)
	if err != nil {
		return Report{}, fmt.Errorf("build golden material provider: %w", err)
	}
	client := benchmark.Client{BaseURL: strings.TrimRight(config.BaseURL, "/"), HTTPClient: config.HTTPClient}
	recorder := newRecordingCompleter(client)
	adapters, err := localagent.New(recorder, config.Model, provider)
	if err != nil {
		return Report{}, err
	}
	runtime, err := orchestrator.New(orchestrator.Dependencies{
		Specialist: adapters, Reviewer: adapters, Synthesizer: adapters,
		Sink: config.EventSink, TraceStore: orchestrator.FileTraceStore{Directory: config.TraceDir},
	})
	if err != nil {
		return Report{}, err
	}
	runtime.ContextConcurrency = config.ContextConcurrency
	runtime.Planner.DeadlineMS = int(config.Timeout.Milliseconds())
	runtime.Planner.ContextTimeoutMS = 60000
	runtime.Planner.ReviewTimeoutMS = 60000
	runtime.Planner.SynthesisTimeoutMS = 120000
	var request contracts.ResearchRequest
	if config.RequestOverride != nil {
		request = *config.RequestOverride
		if err := contracts.ValidateResearchRequest(request); err != nil {
			return Report{}, fmt.Errorf("validate request override: %w", err)
		}
	} else {
		request, err = goldenRequest(config, snapshot.AsOf)
		if err != nil {
			return Report{}, err
		}
	}
	started := time.Now()
	result := runtime.Run(ctx, request)
	report := Report{
		SchemaVersion: ReportSchemaV1, GeneratedAt: time.Now().UTC(), Question: request.UserText,
		AsOf: request.AsOf, Model: config.Model, LocalBaseURL: config.BaseURL,
		Request: request, Result: result, Calls: recorder.Metrics(),
	}
	report.Metrics = measureReport(report, time.Since(started))
	report.Acceptance = acceptance(report)
	return report, nil
}

func goldenRequest(config RunConfig, asOf time.Time) (contracts.ResearchRequest, error) {
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: config.Question, AsOf: asOf, RunID: config.RunID, RequestID: config.RequestID,
	})
	if err != nil {
		return contracts.ResearchRequest{}, err
	}
	if len(request.Entities) == 2 && strings.Contains(strings.ToLower(config.Question), "compare") {
		request.PrimaryIntent = string(taxonomy.CompanyComparison)
		request.Comparison.Mode = "peer"
		request.Comparison.EntityIDs = []string{request.Entities[0].EntityID, request.Entities[1].EntityID}
	}
	if request.PrimaryIntent != string(taxonomy.CompanyComparison) || len(request.Entities) != 2 {
		return contracts.ResearchRequest{}, errors.New("golden question must resolve to a two-company comparison")
	}
	request.SecondaryIntents = []string{
		string(taxonomy.FinancialQuality), string(taxonomy.EconomicTransmission),
		string(taxonomy.Valuation), string(taxonomy.MarketBehavior), string(taxonomy.ThesisReview),
	}
	request.AnswerDepth = "deep"
	request.RequestedOutputs = []string{
		"comparison", "transmission_mechanisms", "market_measurement", "scenarios",
		"counterevidence", "invalidation_conditions", "evidence", "limitations",
	}
	request.Assumptions = []string{
		"Higher-for-longer interest rates are an explicit scenario, not a claim that the future path of rates is known.",
		"Slower AI infrastructure spending is an explicit downside scenario, not an observed causal forecast.",
	}
	if config.UseAssumptions {
		request.Assumptions = append([]string(nil), config.Assumptions...)
	}
	if err := contracts.ValidateResearchRequest(request); err != nil {
		return contracts.ResearchRequest{}, err
	}
	return request, nil
}

func validateRunConfig(config RunConfig) error {
	for name, value := range map[string]string{
		"snapshot path": config.SnapshotPath, "retrieval path": config.RetrievalPath,
		"trace directory": config.TraceDir, "base URL": config.BaseURL,
		"model": config.Model, "code commit": config.CodeCommit,
		"question": config.Question, "run ID": config.RunID, "request ID": config.RequestID,
	} {
		if strings.TrimSpace(value) == "" {
			return fmt.Errorf("%s is required", name)
		}
	}
	parsed, err := url.Parse(config.BaseURL)
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") {
		return errors.New("local base URL must be HTTP or HTTPS")
	}
	host := parsed.Hostname()
	if host != "127.0.0.1" && host != "localhost" && host != "::1" {
		return fmt.Errorf("core inference endpoint %q is not loopback-local", host)
	}
	if config.Timeout <= 0 {
		return errors.New("positive run timeout is required")
	}
	if config.ContextConcurrency < 1 || config.ContextConcurrency > 4 {
		return errors.New("context concurrency must be between one and four")
	}
	return nil
}

type recordingCompleter struct {
	client  benchmark.Client
	roles   map[string]string
	prompts []promptRole
	mu      sync.Mutex
	calls   []CallMetric
}

type promptRole struct {
	system string
	roleID string
}

func newRecordingCompleter(client benchmark.Client) *recordingCompleter {
	registry := localagent.DefaultPromptRegistry()
	roleByPrompt := map[string]string{}
	prompts := make([]promptRole, 0)
	for _, prompt := range registry.List() {
		roleByPrompt[prompt.System] = prompt.RoleID
		prompts = append(prompts, promptRole{system: prompt.System, roleID: prompt.RoleID})
	}
	sort.Slice(prompts, func(i, j int) bool { return len(prompts[i].system) > len(prompts[j].system) })
	return &recordingCompleter{client: client, roles: roleByPrompt, prompts: prompts}
}

func (recorder *recordingCompleter) Complete(ctx context.Context, request benchmark.Request) (benchmark.Completion, error) {
	roleID := "unknown"
	if len(request.Messages) > 0 {
		roleID = recorder.roleForSystemPrompt(request.Messages[0].Content)
	}
	started := time.Now().UTC()
	completion, err := recorder.client.Complete(ctx, request)
	metric := CallMetric{RoleID: roleID, StartedAt: started, Failed: err != nil}
	if err != nil {
		metric.Duration = time.Since(started)
		metric.Error = err.Error()
	} else {
		metric.Duration = completion.Duration
		metric.TTFT = completion.TTFT
		metric.PromptTokens = completion.Usage.PromptTokens
		metric.CompletionTokens = completion.Usage.CompletionTokens
		metric.FinishReason = completion.FinishReason
	}
	recorder.mu.Lock()
	recorder.calls = append(recorder.calls, metric)
	recorder.mu.Unlock()
	return completion, err
}

func (recorder *recordingCompleter) roleForSystemPrompt(system string) string {
	if roleID, ok := recorder.roles[system]; ok {
		return roleID
	}
	// Bounded repair prompts append corrective instructions to the canonical
	// role prompt. Longest-prefix matching preserves the originating role while
	// refusing arbitrary prompt-shaped text.
	for _, candidate := range recorder.prompts {
		if strings.HasPrefix(system, candidate.system) {
			return candidate.roleID
		}
	}
	return "unknown"
}

func (recorder *recordingCompleter) Metrics() []CallMetric {
	recorder.mu.Lock()
	defer recorder.mu.Unlock()
	result := append([]CallMetric(nil), recorder.calls...)
	sort.Slice(result, func(i, j int) bool { return result[i].StartedAt.Before(result[j].StartedAt) })
	return result
}

func measureReport(report Report, elapsed time.Duration) Metrics {
	metrics := Metrics{DurationMS: float64(elapsed.Microseconds()) / 1000, ModelCalls: len(report.Calls), ContextPackets: len(report.Result.Packets), Critiques: len(report.Result.Critiques), MaxConcurrentContext: report.Result.Trace.MaxConcurrentContext, FailureSurfaced: report.Result.Failure != nil}
	for _, call := range report.Calls {
		metrics.PromptTokens += call.PromptTokens
		metrics.CompletionTokens += call.CompletionTokens
	}
	evidence, receipts := map[string]bool{}, map[string]bool{}
	for _, packet := range report.Result.Packets {
		for _, item := range packet.Evidence {
			evidence[item.EvidenceID] = true
		}
		for _, receipt := range packet.CalculationReceipts {
			receipts[receipt.ReceiptID] = true
			switch receipt.OperationID {
			case "valuation.fcff_dcf":
				metrics.DCFReceipts++
			case "scenario.sensitivity_matrix":
				metrics.SensitivityReceipts++
			case "valuation.peer_multiple":
				metrics.MultipleReceipts++
			}
		}
		for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
			metrics.Claims++
			if len(finding.EvidenceRefs)+len(finding.CalculationRefs)+len(finding.NumericalRefs) > 0 ||
				(finding.ClaimType == contracts.ClaimHypothesis && len(finding.AssumptionRefs) > 0) {
				metrics.SupportedClaims++
			}
		}
	}
	metrics.UniqueEvidenceRefs, metrics.UniqueCalculationRefs = len(evidence), len(receipts)
	if metrics.Claims > 0 {
		metrics.EvidenceCoverage = float64(metrics.SupportedClaims) / float64(metrics.Claims)
	}
	metrics.RequiredSections = len(report.Request.RequestedOutputs)
	if report.Result.Answer != nil {
		present := map[string]bool{}
		for _, section := range report.Result.Answer.Sections {
			present[section.SectionType] = true
		}
		for _, required := range report.Request.RequestedOutputs {
			if present[required] {
				metrics.PresentRequiredSections++
			}
		}
	}
	return metrics
}

func acceptance(report Report) Acceptance {
	contextRoles := map[string]bool{}
	for _, packet := range report.Result.Packets {
		contextRoles[packet.SpecialistRole] = true
	}
	reviewers := map[string]bool{}
	for _, critique := range report.Result.Critiques {
		if critique.Decision == contracts.CritiqueApprove {
			reviewers[critique.ReviewerRole] = true
		}
	}
	allSix := true
	for _, roleID := range []string{roles.BusinessStrategy, roles.AccountingReporting, roles.FinancialQuality, roles.EconomicsTransmission, roles.Valuation, roles.MarketBehavior} {
		allSix = allSix && contextRoles[roleID]
	}
	return Acceptance{
		CompleteLocalPath:     report.Result.Answer != nil && report.Result.Failure == nil,
		AllSixSpecialists:     allSix,
		BothCriticsApproved:   reviewers[roles.RiskContrarian] && reviewers[roles.EvidenceCritic],
		AllClaimsSupported:    report.Metrics.Claims > 0 && report.Metrics.Claims == report.Metrics.SupportedClaims,
		RequiredSectionsReady: report.Metrics.RequiredSections == report.Metrics.PresentRequiredSections,
		ScenarioReceiptsReady: report.Metrics.DCFReceipts >= 2 && report.Metrics.SensitivityReceipts >= 2,
		MarketInputsExplicit:  len(report.Request.Entities) == len(reportPriceTickers(report)),
	}
}

func reportPriceTickers(report Report) map[string]bool {
	result := map[string]bool{}
	for _, packet := range report.Result.Packets {
		for _, evidence := range packet.Evidence {
			if strings.HasPrefix(evidence.EvidenceID, "market-price:") {
				result[strings.TrimPrefix(evidence.EvidenceID, "market-price:")] = true
			}
		}
		for _, receipt := range packet.CalculationReceipts {
			for _, evidenceID := range receipt.EvidenceRefs {
				if strings.HasPrefix(evidenceID, "market-price:") {
					result[strings.TrimPrefix(evidenceID, "market-price:")] = true
				}
			}
		}
	}
	return result
}

var _ localagent.Completer = (*recordingCompleter)(nil)
