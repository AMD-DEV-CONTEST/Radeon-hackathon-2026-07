package financialintelligence

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/capability"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/engine"
	"github.com/rvbernucci/signalforge/internal/metricregistry"
	"github.com/rvbernucci/signalforge/internal/numericalcontext"
	"github.com/rvbernucci/signalforge/internal/roles"
)

var packetTime = time.Date(2026, 7, 22, 18, 0, 0, 0, time.UTC)

func receiptFixture(t testing.TB) contracts.CalculationReceipt {
	t.Helper()
	operation, _ := capability.RuntimeRegistry().Get("financial.nopat")
	inputAsOf := packetTime.Add(-time.Hour)
	request := contracts.EngineRequest{
		SchemaVersion: contracts.SchemaVersionV1, RequestID: "request-nopat", RunID: "run-packet", StepID: "step-nopat",
		RequestedBy: roles.FinancialQuality, EngineID: operation.Engine, OperationID: operation.ID,
		FormulaVersion: operation.FormulaVersion, Scope: contracts.Scope{CompanyIDs: []string{"company-msft"}, Periods: []string{"FY2025"}, AsOf: packetTime},
		Inputs: []contracts.EngineInput{
			{InputID: "operating_income", Quantity: contracts.Quantity{Value: "100", Unit: "currency", Currency: "USD", Period: "FY2025", AsOf: &inputAsOf}, Status: "reported", EvidenceRefs: []string{"evidence-operating-income"}},
			{InputID: "tax_rate", Quantity: contracts.Quantity{Value: "0.25", Unit: "ratio", AsOf: &inputAsOf}, Status: "assumed"},
		},
		Assumptions: []string{"Analytical operating tax rate."}, PrecisionPolicy: operation.NumericalPolicy, RequestedOutputs: []string{"nopat"},
	}
	executor, err := engine.NewWithClock("sprint16b-test", func() time.Time { return packetTime })
	if err != nil {
		t.Fatal(err)
	}
	result := executor.Execute(request)
	if result.Failure != nil || result.Receipt == nil {
		t.Fatalf("receipt fixture failed: %+v", result.Failure)
	}
	return *result.Receipt
}

func packetOptions(profile metricregistry.CompanyProfile) Options {
	start := time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)
	end := time.Date(2025, 12, 31, 0, 0, 0, 0, time.UTC)
	return Options{
		PacketID: "financial-packet", ContextID: "numerical-context", RunID: "run-packet", AsOf: packetTime,
		EntityNames:         map[string]string{"company-msft": "Microsoft"},
		EntityFiscalPeriods: map[string]numericalcontext.FiscalPeriod{"company-msft": {Start: start, End: end}},
		CompanyProfiles:     map[string]metricregistry.CompanyProfile{"company-msft": profile}, Tolerance: "0",
	}
}

func TestBuildSeparatesModelViewFromAuthoritativeValues(t *testing.T) {
	packet, err := Build(packetOptions(metricregistry.ProfileOperatingCompany), []contracts.CalculationReceipt{receiptFixture(t)})
	if err != nil {
		t.Fatal(err)
	}
	if len(packet.Model.Metrics) != 1 || len(packet.Numerical.Variables) != 1 {
		t.Fatalf("unexpected packet %+v", packet)
	}
	encoded, err := json.Marshal(packet.Model)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(encoded), `"value":`) {
		t.Fatalf("model view leaked an authoritative value: %s", encoded)
	}
	reference := packet.Model.Metrics[0].ReferenceID
	rendered, err := RenderNumericalReferences(packet, []string{reference})
	if err != nil {
		t.Fatal(err)
	}
	if len(rendered) != 1 || !strings.Contains(rendered[0], "Microsoft") || !strings.Contains(rendered[0], "USD") {
		t.Fatalf("deterministic renderer did not release the value: %+v", rendered)
	}
}

func TestBuildEnforcesApplicabilityAndDefinitionVersion(t *testing.T) {
	receipt := receiptFixture(t)
	if _, err := Build(packetOptions(metricregistry.ProfileBank), []contracts.CalculationReceipt{receipt}); err == nil || !strings.Contains(err.Error(), "not_applicable") {
		t.Fatalf("bank applicability must fail, got %v", err)
	}
	receipt.FormulaVersion = "9.9.9"
	if _, err := Build(packetOptions(metricregistry.ProfileOperatingCompany), []contracts.CalculationReceipt{receipt}); err == nil || !strings.Contains(err.Error(), "definition_conflict") {
		t.Fatalf("formula-definition mismatch must fail, got %v", err)
	}
}

func BenchmarkBuildNumericallySilentPacket(b *testing.B) {
	receipt := receiptFixture(b)
	options := packetOptions(metricregistry.ProfileOperatingCompany)
	b.ReportAllocs()
	for range b.N {
		if _, err := Build(options, []contracts.CalculationReceipt{receipt}); err != nil {
			b.Fatal(err)
		}
	}
}
