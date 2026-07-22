package golden

import (
	"context"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/capability"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
	"github.com/rvbernucci/signalforge/internal/retrieval"
	"github.com/rvbernucci/signalforge/internal/roles"
)

func TestFrozenSnapshotIsCompleteAndPointInTime(t *testing.T) {
	snapshot, err := LoadSnapshot(filepath.Join("..", "..", "fixtures", "golden", "financial-snapshot.json"))
	if err != nil {
		t.Fatal(err)
	}
	if len(snapshot.Companies) != 2 || !snapshot.MarketPricesAreRuntimeInputs {
		t.Fatalf("unexpected golden snapshot: %+v", snapshot)
	}
	msft, ok := snapshot.Company("sec-cik:0000789019")
	if !ok {
		t.Fatal("Microsoft is missing")
	}
	capex, ok := msft.Metric("capital_expenditure")
	if !ok || capex.Value != "64551000000" {
		t.Fatalf("unexpected Microsoft capex: %+v", capex)
	}
}

func TestGoldenProviderCreatesAuditableSpecialistMaterial(t *testing.T) {
	provider := testProvider(t)
	financial, err := provider.Load(context.Background(), contextRequest(roles.FinancialQuality))
	if err != nil {
		t.Fatal(err)
	}
	counts := receiptCounts(financial.CalculationReceipts)
	for _, operationID := range []string{"financial.revenue_growth", "financial.margin", "financial.free_cash_flow", "financial.cash_conversion", "financial.capex_intensity"} {
		if counts[operationID] != 2 {
			t.Fatalf("expected two %s receipts, got %+v", operationID, counts)
		}
	}
	if len(financial.Evidence.Items) < 8 || len(financial.Evidence.Items) > 10 || len(financial.Evidence.Missing) == 0 {
		t.Fatalf("financial material is incomplete or not compact: evidence=%d missing=%+v", len(financial.Evidence.Items), financial.Evidence.Missing)
	}

	valuation, err := provider.Load(context.Background(), contextRequest(roles.Valuation))
	if err != nil {
		t.Fatal(err)
	}
	counts = receiptCounts(valuation.CalculationReceipts)
	if counts["valuation.fcff_dcf"] != 2 || counts["scenario.sensitivity_matrix"] != 2 || counts["valuation.peer_multiple"] != 2 {
		t.Fatalf("valuation material omitted scenario or multiple receipts: %+v", counts)
	}
	for _, receipt := range valuation.CalculationReceipts {
		if receipt.ReceiptSHA == "" || receipt.CodeCommit != "test-tree" {
			t.Fatalf("receipt is not reproducible: %+v", receipt)
		}
	}

	accounting, err := provider.Load(context.Background(), contextRequest(roles.AccountingReporting))
	if err != nil {
		t.Fatal(err)
	}
	foundBoundary := false
	for _, item := range accounting.Evidence.Items {
		if item.EvidenceRef.EvidenceID == "comparison:fiscal-period-boundary" && item.State == contracts.EvidenceIncomparable {
			foundBoundary = true
		}
	}
	if !foundBoundary {
		t.Fatal("accounting material omitted the fiscal-period comparability boundary")
	}
}

func TestCompoundForecastUsesDeterministicDecimalArithmetic(t *testing.T) {
	forecast, err := compoundForecast("71611000000", "0.08", 5)
	if err != nil {
		t.Fatal(err)
	}
	if len(forecast) != 5 || forecast[0] != "77339880000" || forecast[4] != "105220052907.7248" {
		t.Fatalf("unexpected forecast: %+v", forecast)
	}
}

func TestRunConfigRejectsRemoteCoreInference(t *testing.T) {
	err := validateRunConfig(RunConfig{
		SnapshotPath: "snapshot", RetrievalPath: "retrieval", TraceDir: "trace",
		BaseURL: "https://example.com/v1", Model: "model", CodeCommit: "tree",
		Question: DefaultQuestion, RunID: "run", RequestID: "request", Timeout: time.Minute,
		ContextConcurrency: 2,
	})
	if err == nil {
		t.Fatal("core inference must remain loopback-local")
	}
}

func TestGoldenRequestRequiresTransmissionAndMarketSections(t *testing.T) {
	snapshot, err := LoadSnapshot(filepath.Join("..", "..", "fixtures", "golden", "financial-snapshot.json"))
	if err != nil {
		t.Fatal(err)
	}
	request, err := goldenRequest(RunConfig{
		Question: DefaultQuestion, RunID: "run", RequestID: "request",
	}, snapshot.AsOf)
	if err != nil {
		t.Fatal(err)
	}
	wanted := map[string]bool{"transmission_mechanisms": false, "market_measurement": false, "scenarios": false}
	for _, output := range request.RequestedOutputs {
		if _, ok := wanted[output]; ok {
			wanted[output] = true
		}
	}
	for output, present := range wanted {
		if !present {
			t.Fatalf("golden request omitted %s: %+v", output, request.RequestedOutputs)
		}
	}
}

func TestGoldenRequestUsesExplicitWorkspaceScenarioAssumptions(t *testing.T) {
	now := time.Date(2026, 7, 21, 16, 0, 0, 0, time.UTC)
	want := []string{
		"Easing interest rates are an explicit scenario, not a forecast.",
		"Resilient AI infrastructure spending is an explicit scenario, not a forecast.",
	}
	request, err := goldenRequest(RunConfig{
		Question: "Compare Microsoft and NVIDIA under easing rates and resilient AI spending.",
		RunID: "run", RequestID: "request", UseAssumptions: true, Assumptions: want,
	}, now)
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(request.Assumptions, want) {
		t.Fatalf("workspace scenario assumptions were not authoritative: %+v", request.Assumptions)
	}
}

func TestSemanticRubricAndOfficialPriceSetWereFrozenBeforeEvaluation(t *testing.T) {
	rubric, rubricSHA, err := LoadSemanticRubric(filepath.Join("..", "..", "fixtures", "golden", "semantic-rubric.json"))
	if err != nil {
		t.Fatal(err)
	}
	if rubric.RubricID != "golden-msft-nvda-decision-v1" || len(rubricSHA) != 64 {
		t.Fatalf("unexpected semantic rubric identity: %s %s", rubric.RubricID, rubricSHA)
	}
	prices, err := LoadPriceSet(filepath.Join("..", "..", "fixtures", "golden", "market-price-inputs.json"))
	if err != nil {
		t.Fatal(err)
	}
	if len(prices.Prices) != 2 || !rubric.FrozenAt.Before(prices.RetrievedAt) {
		t.Fatalf("rubric must be frozen before the price-backed evaluation input: rubric=%s prices=%s", rubric.FrozenAt, prices.RetrievedAt)
	}
	snapshot, err := LoadSnapshot(filepath.Join("..", "..", "fixtures", "golden", "financial-snapshot.json"))
	if err != nil {
		t.Fatal(err)
	}
	for _, price := range prices.Prices {
		if price.AsOf.After(snapshot.AsOf) {
			t.Fatalf("price %s leaks beyond the frozen analysis boundary", price.Ticker)
		}
	}
}

func TestSemanticEvaluationFailsClosedWithoutReleasedAnswer(t *testing.T) {
	rubric, rubricSHA, err := LoadSemanticRubric(filepath.Join("..", "..", "fixtures", "golden", "semantic-rubric.json"))
	if err != nil {
		t.Fatal(err)
	}
	report := Report{Question: DefaultQuestion, Request: contracts.ResearchRequest{RunID: "run-no-answer"}}
	evaluation := EvaluateSemantics(report, rubric, rubricSHA, time.Date(2026, 7, 22, 2, 10, 0, 0, time.UTC))
	if evaluation.Passed || evaluation.TotalChecks != 2 || evaluation.PassedChecks != 1 {
		t.Fatalf("missing answer did not fail closed: %+v", evaluation)
	}
}

func TestSemanticRubricV5DetectsPresentationDefects(t *testing.T) {
	rubric, rubricSHA, err := LoadSemanticRubric(filepath.Join("..", "..", "fixtures", "golden", "semantic-rubric-v5.json"))
	if err != nil {
		t.Fatal(err)
	}
	answer := contracts.FinalAnswer{Sections: []contracts.AnswerSection{
		{SectionType: "scenarios", Content: "Microsoft's DCF enterprise value is lower than NVIDIA's. MSFT multiple was 2949.34%, lower than NVDA."},
		{SectionType: "limitations", Content: "DCF valuation ranges and multiples are not provided."},
	}}
	report := Report{
		Question: DefaultQuestion,
		Request:  contracts.ResearchRequest{RunID: "run-defective-presentation"},
		Result:   orchestrator.Result{Answer: &answer},
	}
	evaluation := EvaluateSemantics(report, rubric, rubricSHA, time.Date(2026, 7, 22, 4, 0, 0, 0, time.UTC))
	checks := map[string]bool{}
	for _, check := range evaluation.Checks {
		checks[check.CheckID] = check.Passed
	}
	for _, checkID := range []string{
		"section_pattern:required:scenarios:1",
		"section_pattern:required:scenarios:2",
		"section_pattern:forbidden:scenarios:1",
		"section_pattern:forbidden:scenarios:2",
		"section_pattern:forbidden:limitations:1",
	} {
		if checks[checkID] {
			t.Fatalf("defective presentation unexpectedly passed %s: %+v", checkID, evaluation.Checks)
		}
	}

	answer.Sections[0].Content = "NVIDIA's peer multiple is greater than Microsoft's peer multiple."
	report.Result.Answer = &answer
	evaluation = EvaluateSemantics(report, rubric, rubricSHA, time.Date(2026, 7, 22, 4, 17, 0, 0, time.UTC))
	for _, check := range evaluation.Checks {
		if check.CheckID == "section_pattern:forbidden:scenarios:3" && check.Passed {
			t.Fatal("model-authored multiple direction unexpectedly passed the frozen rubric")
		}
	}

	answer.Sections = []contracts.AnswerSection{answerSection("limitations", "Fiscal year endSS differ.")}
	report.Result.Answer = &answer
	evaluation = EvaluateSemantics(report, rubric, rubricSHA, time.Date(2026, 7, 22, 4, 24, 0, 0, time.UTC))
	for _, check := range evaluation.Checks {
		if check.CheckID == "section_pattern:forbidden:limitations:2" && check.Passed {
			t.Fatal("malformed mixed-case token unexpectedly passed the frozen rubric")
		}
	}
}

func answerSection(sectionType, content string) contracts.AnswerSection {
	return contracts.AnswerSection{SectionType: sectionType, Content: content}
}

func testProvider(t *testing.T) *Provider {
	t.Helper()
	snapshot, err := LoadSnapshot(filepath.Join("..", "..", "fixtures", "golden", "financial-snapshot.json"))
	if err != nil {
		t.Fatal(err)
	}
	_, chunks, err := retrieval.LoadEvalSet(filepath.Join("..", "..", "fixtures", "retrieval", "golden-eval.json"))
	if err != nil {
		t.Fatal(err)
	}
	provider, err := NewProvider(snapshot, chunks, "test-tree", []PriceInput{
		{Ticker: "MSFT", Value: "398.10", Currency: "USD", AsOf: snapshot.AsOf, Source: "runtime://test"},
		{Ticker: "NVDA", Value: "206.83", Currency: "USD", AsOf: snapshot.AsOf, Source: "runtime://test"},
	})
	if err != nil {
		t.Fatal(err)
	}
	return provider
}

func contextRequest(roleID string) contracts.ContextRequest {
	registry := capability.Tier0Registry()
	capabilities := []string{}
	for _, operation := range registry.List() {
		if registry.Authorizes(roleID, operation.ID) {
			capabilities = append(capabilities, operation.ID)
		}
	}
	return contracts.ContextRequest{
		SchemaVersion: contracts.SchemaVersionV1, ContextRequestID: "golden-test-" + roleID,
		RunID: "golden-test", StepID: "context-test", SpecialistRole: roleID,
		Objective: "Evaluate the golden comparison.", ResearchQuestion: DefaultQuestion,
		Scope:         contracts.Scope{CompanyIDs: []string{"sec-cik:0000789019", "sec-cik:0001045810"}, AsOf: time.Date(2026, 7, 21, 16, 0, 0, 0, time.UTC)},
		CapabilityIDs: capabilities, TokenBudget: 5000,
	}
}

func receiptCounts(receipts []contracts.CalculationReceipt) map[string]int {
	result := map[string]int{}
	for _, receipt := range receipts {
		result[receipt.OperationID]++
	}
	return result
}
