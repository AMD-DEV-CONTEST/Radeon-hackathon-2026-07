package comparability

import (
	"strings"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

const hash = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

func TestEvaluateComparableWithVisibleFilingDateCaveat(t *testing.T) {
	now := time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC)
	request := request(t, now)
	request.Operands[1].FilingDate = request.Operands[1].FilingDate.Add(-24 * time.Hour)
	request, _ = contracts.PopulateMetricComparabilityRequestHash(request)
	receipt, err := Evaluate(request, now.Add(time.Minute), DefaultPolicy())
	if err != nil {
		t.Fatal(err)
	}
	if receipt.Disposition != contracts.ComparisonComparableWithCaveat ||
		len(receipt.RequiredCaveatIDs) != 1 || receipt.RequiredCaveatIDs[0] != "different_filing_dates" {
		t.Fatalf("filing date caveat was not preserved: %+v", receipt)
	}
	if err := contracts.ValidateMetricComparabilityReceipt(receipt); err != nil {
		t.Fatalf("generated receipt is invalid: %v", err)
	}
}

func TestEvaluateRejectsPeriodMismatch(t *testing.T) {
	now := time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC)
	request := request(t, now)
	request.Operands[1].FiscalEnd = request.Operands[1].FiscalEnd.AddDate(0, 0, -1)
	request, _ = contracts.PopulateMetricComparabilityRequestHash(request)
	receipt, err := Evaluate(request, now.Add(time.Minute), DefaultPolicy())
	if err != nil {
		t.Fatal(err)
	}
	if receipt.Disposition != contracts.ComparisonNotComparable || IsReleasable(receipt.Disposition) {
		t.Fatalf("period mismatch was released: %+v", receipt)
	}
	if !strings.Contains(ExplainRefusal(receipt), "same_fiscal_end") {
		t.Fatalf("refusal is not useful: %q", ExplainRefusal(receipt))
	}
}

func TestEvaluateAllowsOnlyReviewedTaxonomyMapping(t *testing.T) {
	now := time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC)
	request := request(t, now)
	request.Operands[1].TaxonomyConcept = "issuer:CustomRevenue"
	request, _ = contracts.PopulateMetricComparabilityRequestHash(request)
	receipt, err := Evaluate(request, now.Add(time.Minute), DefaultPolicy())
	if err != nil {
		t.Fatal(err)
	}
	if receipt.Disposition != contracts.ComparisonNotComparable {
		t.Fatal("unreviewed taxonomy mapping was accepted")
	}

	request.Operands[0].ExtensionMappingID = "mapping-revenue-v1"
	request.Operands[1].ExtensionMappingID = "mapping-revenue-v1"
	request, _ = contracts.PopulateMetricComparabilityRequestHash(request)
	receipt, err = Evaluate(request, now.Add(time.Minute), DefaultPolicy())
	if err != nil {
		t.Fatal(err)
	}
	if receipt.Disposition != contracts.ComparisonComparableWithCaveat {
		t.Fatalf("reviewed taxonomy mapping was not qualified correctly: %+v", receipt)
	}
}

func TestAnnualDurationPolicyAllowsDifferentFiscalCalendarsWithCaveat(t *testing.T) {
	now := time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC)
	item := request(t, now)
	item.ReviewerPolicyVersion = AnnualPolicyVersionV1
	start := item.Operands[1].FiscalStart.AddDate(0, -3, 0)
	item.Operands[1].FiscalStart = &start
	item.Operands[1].FiscalEnd = item.Operands[1].FiscalEnd.AddDate(0, -3, 0)
	item, _ = contracts.PopulateMetricComparabilityRequestHash(item)
	receipt, err := Evaluate(item, now.Add(time.Minute), AnnualDurationPolicy())
	if err != nil {
		t.Fatal(err)
	}
	if receipt.Disposition != contracts.ComparisonComparableWithCaveat ||
		len(receipt.RequiredCaveatIDs) != 1 ||
		receipt.RequiredCaveatIDs[0] != "different_fiscal_periods" {
		t.Fatalf("annual period caveat was not preserved: %+v", receipt)
	}
}

func request(t *testing.T, now time.Time) contracts.MetricComparabilityRequest {
	t.Helper()
	start := time.Date(2025, 7, 1, 0, 0, 0, 0, time.UTC)
	end := time.Date(2026, 6, 30, 0, 0, 0, 0, time.UTC)
	operand := func(company, security string) contracts.MetricComparisonOperand {
		return contracts.MetricComparisonOperand{
			CompanyID: company, SecurityID: security,
			SourceObservationIDs: []string{"observation-" + company}, SourceHashes: []string{hash},
			AvailableAt: now.Add(-time.Hour), RetrievedAt: now,
			CanonicalMetricID: "revenue", MetricVersion: "canonical-metrics/v1",
			TaxonomyConcept: "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
			Value:           "100", Unit: "USD", Currency: "USD", Scale: 0, SignPolicy: "as_reported",
			DimensionalIdentity: "consolidated", PeriodType: "duration",
			FiscalStart: &start, FiscalEnd: end, FilingDate: now.Add(-2 * time.Hour),
			AccountingPerimeter: "consolidated", DefinitionID: "revenue/v1",
			RestatementState: "not_restated", SupersessionState: "active",
		}
	}
	result, err := contracts.PopulateMetricComparabilityRequestHash(contracts.MetricComparabilityRequest{
		SchemaVersion: contracts.ComparabilityRequestSchemaV1,
		RequestID:     "request-1", RunID: "run-1", LaneID: "microsoft-alphabet", AsOf: now,
		ReviewerPolicyVersion: PolicyVersionV1,
		Operands: []contracts.MetricComparisonOperand{
			operand("sec-cik:0000789019", "nasdaq:MSFT"),
			operand("sec-cik:0001652044", "nasdaq:GOOGL"),
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	return result
}
