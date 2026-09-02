package producteval

import (
	"strings"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/productscope"
	"github.com/rvbernucci/signalforge/internal/roles"
)

func TestFinancialAuthorityUsesMarginAliasAndPreservesAbstention(t *testing.T) {
	report := productscope.CompanyFinancialActivation{
		Receipts: []contracts.CalculationReceipt{
			{OperationID: "financial.operating_margin"},
			{OperationID: "financial.free_cash_flow"},
		},
		Abstentions: []contracts.TypedAbstention{
			{MetricIDs: []string{"valuation.fcff_dcf"}, Message: "DCF unavailable."},
		},
	}
	selected, missing := selectFinancialAuthority(report, contracts.ContextRequest{
		CapabilityIDs: []string{"financial.margin", "valuation.fcff_dcf"},
	})
	if len(selected) != 1 || selected[0].OperationID != "financial.operating_margin" {
		t.Fatalf("selected = %+v", selected)
	}
	if len(missing) != 1 || missing[0] != "DCF unavailable." {
		t.Fatalf("missing = %+v", missing)
	}
}

func TestReceiptEvidenceNeverExposesExactValue(t *testing.T) {
	asOf := time.Date(2026, 4, 29, 20, 6, 24, 0, time.UTC)
	receipts := []contracts.CalculationReceipt{{
		ReceiptID:   "receipt-margin",
		OperationID: "financial.operating_margin",
		SourceAsOf:  asOf,
		NormalizedInputs: []contracts.EngineInput{{
			InputID: "revenue",
			Quantity: contracts.Quantity{
				Value: "123456789", Unit: "currency", Currency: "USD",
				Period: "2025-01-01/2025-12-31",
			},
			EvidenceRefs: []string{"sec-companyfacts:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
		}},
	}}
	items := receiptEvidence(productscope.PublicCompany{
		CompanyID: "sec-cik:0000000001", DisplayName: "Example",
	}, receipts)
	if len(items) != 1 {
		t.Fatalf("items = %d", len(items))
	}
	if strings.Contains(items[0].Statement, "123456789") {
		t.Fatalf("model-visible statement leaked an exact value: %q", items[0].Statement)
	}
	if !strings.Contains(items[0].Statement, "receipt-margin") {
		t.Fatalf("statement lacks receipt authority: %q", items[0].Statement)
	}
}

func TestAccountingAuthoritySurfacesTypedPeriodTaxonomyAndPerimeterMetadata(t *testing.T) {
	asOf := time.Date(2026, 7, 24, 0, 0, 0, 0, time.UTC)
	item := accountingAuthorityEvidence(
		productscope.PublicCompany{
			CompanyID: "sec-cik:0000789019", DisplayName: "Microsoft",
		},
		productscope.CompanyFinancialActivation{
			ConsolidationPolicy:  productscope.FinancialConsolidationPolicy,
			CapexPerimeterPolicy: productscope.CapexPerimeterPolicy,
			SourceConcepts: map[string][]string{
				"revenue": {"RevenueFromContractWithCustomerExcludingAssessedTax"},
			},
		},
		[]contracts.CalculationReceipt{{
			Scope: contracts.Scope{Periods: []string{"2025-07-01/2026-06-30"}},
		}},
		asOf,
	)
	if item.State != contracts.EvidenceAvailable ||
		item.EvidenceRef.SourceType != "accounting_authority_policy" ||
		item.EvidenceRef.DocumentSection != "period-taxonomy-perimeter-comparability" ||
		!item.EvidenceRef.AsOf.Equal(asOf) {
		t.Fatalf("accounting authority envelope = %+v", item)
	}
	joined := strings.Join(item.Warnings, " ")
	for _, required := range []string{
		"accounting_perimeter:",
		"capex_perimeter:",
		"authorized_periods:2025-07-01/2026-06-30",
		"authorized_taxonomy_concepts:RevenueFromContractWithCustomerExcludingAssessedTax",
		"comparability_requires_metric_receipt",
	} {
		if !strings.Contains(joined, required) {
			t.Fatalf("accounting authority omitted %q: %+v", required, item.Warnings)
		}
	}
}

func TestFiscalPeriodsSelectLatestDuration(t *testing.T) {
	receipts := []contracts.CalculationReceipt{
		{Scope: contracts.Scope{CompanyIDs: []string{"company-a"}, Periods: []string{"2024-01-01/2024-12-31"}}},
		{Scope: contracts.Scope{CompanyIDs: []string{"company-a"}, Periods: []string{"2025-01-01/2025-12-31"}}},
	}
	periods := fiscalPeriods(receipts)
	if got := periods["company-a"].End.Format("2006-01-02"); got != "2025-12-31" {
		t.Fatalf("latest fiscal end = %s", got)
	}
}

func TestRoleBoundariesRemainExplicit(t *testing.T) {
	for _, roleID := range []string{
		roles.BusinessStrategy, roles.EconomicsTransmission, roles.Valuation, roles.MarketBehavior,
	} {
		if len(roleMissingEvidence(roleID)) == 0 {
			t.Fatalf("role %s lacks a fail-closed evidence boundary", roleID)
		}
	}
	if len(roleMissingEvidence(roles.AccountingReporting)) != 0 {
		t.Fatal("accounting received an unrelated narrative boundary")
	}
}

func TestRoleScopePolicyIsAvailableBoundaryEvidenceNotCompanyEvidence(t *testing.T) {
	now := time.Date(2026, 7, 24, 0, 0, 0, 0, time.UTC)
	items := roleScopePolicyEvidence(contracts.ContextRequest{
		SpecialistRole: roles.BusinessStrategy,
		Scope:          contracts.Scope{AsOf: now},
	}, roleMissingEvidence(roles.BusinessStrategy))
	if len(items) != 1 || items[0].State != contracts.EvidenceAvailable ||
		items[0].EvidenceRef.SourceType != "product_scope_policy" ||
		!strings.Contains(items[0].Warnings[1], "not_company_evidence") {
		t.Fatalf("scope policy evidence = %+v", items)
	}
	if strings.Contains(strings.ToLower(items[0].Statement), "nvidia") {
		t.Fatalf("scope policy improperly became company evidence: %q", items[0].Statement)
	}
}

func TestGovernedMissingEvidenceTurnsOnlyProductScopeStateIntoAuthority(t *testing.T) {
	now := time.Date(2026, 7, 24, 0, 0, 0, 0, time.UTC)
	items := governedMissingEvidence(contracts.ContextRequest{
		SpecialistRole: roles.AccountingReporting,
		Scope:          contracts.Scope{AsOf: now},
	}, []string{
		"SignalForge withheld accounting.balance_sheet_identity because aligned standardized inputs unavailable.",
		"SignalForge withheld accounting.balance_sheet_identity because aligned standardized inputs unavailable.",
	})
	if len(items) != 1 {
		t.Fatalf("deduplicated scope evidence = %+v", items)
	}
	item := items[0]
	if item.State != contracts.EvidenceAvailable ||
		item.EvidenceRef.SourceType != "product_scope_policy" ||
		item.EvidenceRef.AsOf != now ||
		!strings.Contains(item.Statement, "SignalForge withheld") {
		t.Fatalf("governed missing evidence = %+v", item)
	}
	if len(item.Warnings) != 2 || item.Warnings[1] != "not_company_evidence" {
		t.Fatalf("missing non-company boundary: %+v", item.Warnings)
	}
}

func TestNotComparableReceiptCarriesBothOperands(t *testing.T) {
	refs := comparisonConflictRefs(contracts.MetricComparabilityReceipt{
		Disposition: contracts.ComparisonNotComparable,
		Operands: []contracts.MetricComparisonOperand{
			{CompanyID: "left", CanonicalMetricID: "financial.margin"},
			{CompanyID: "right", CanonicalMetricID: "financial.margin"},
		},
	})
	if len(refs) != 2 || refs[0] != "left:financial.margin" || refs[1] != "right:financial.margin" {
		t.Fatalf("conflict refs = %+v", refs)
	}
}

func TestPeerPolicyAllowsOnlyComparableMetricsIntoNumericalContext(t *testing.T) {
	provider := Provider{peers: productscope.PeerEvaluationSuite{
		Lanes: []productscope.PeerEvaluationResult{{
			CompanyIDs: []string{"company-a", "company-b"},
			Receipts: []contracts.MetricComparabilityReceipt{
				{
					Disposition: contracts.ComparisonComparableWithCaveat,
					Operands: []contracts.MetricComparisonOperand{{
						CanonicalMetricID: "financial.operating_margin",
					}},
				},
				{
					Disposition: contracts.ComparisonNotComparable,
					Operands: []contracts.MetricComparisonOperand{{
						CanonicalMetricID: "financial.revenue_growth",
					}},
				},
			},
		}},
	}}
	allowed, scoped := provider.comparisonOperationPolicy([]string{"company-b", "company-a"})
	if !scoped || !allowed["financial.operating_margin"] ||
		allowed["financial.revenue_growth"] {
		t.Fatalf("peer operation policy = %+v scoped=%t", allowed, scoped)
	}
	filtered, missing := filterComparisonReceipts([]contracts.CalculationReceipt{
		{OperationID: "financial.operating_margin"},
		{OperationID: "financial.revenue_growth"},
		{OperationID: "financial.free_cash_flow"},
	}, nil, allowed)
	if len(filtered) != 1 || filtered[0].OperationID != "financial.operating_margin" {
		t.Fatalf("filtered receipts = %+v", filtered)
	}
	if len(missing) != 2 ||
		!strings.Contains(strings.Join(missing, " "), "did not authorize") {
		t.Fatalf("comparison abstentions = %+v", missing)
	}
}

func TestComparisonMaterialUsesReceiptAsOfInsteadOfGenerationTime(t *testing.T) {
	asOf := time.Date(2026, 7, 24, 10, 32, 53, 0, time.UTC)
	generatedAt := asOf.Add(30 * time.Minute)
	provider := Provider{peers: productscope.PeerEvaluationSuite{
		Lanes: []productscope.PeerEvaluationResult{{
			LaneID:     "microsoft-alphabet",
			CompanyIDs: []string{"company-a", "company-b"},
			Receipts: []contracts.MetricComparabilityReceipt{{
				ReceiptID:             "receipt-fcf",
				AsOf:                  asOf,
				GeneratedAt:           generatedAt,
				Disposition:           contracts.ComparisonComparableWithCaveat,
				ReceiptSHA256:         strings.Repeat("a", 64),
				ReviewerPolicyVersion: "comparability/v1",
				Operands: []contracts.MetricComparisonOperand{{
					CanonicalMetricID: "financial.free_cash_flow",
				}},
			}},
		}},
	}}
	items, missing := provider.comparisonMaterial(contracts.ContextRequest{
		Scope: contracts.Scope{
			CompanyIDs: []string{"company-a", "company-b"},
			AsOf:       asOf,
		},
	})
	if len(missing) != 1 || !strings.Contains(missing[0], "not been promoted") {
		t.Fatalf("missing = %+v", missing)
	}
	if len(items) != 1 || !items[0].EvidenceRef.AsOf.Equal(asOf) {
		t.Fatalf("comparison evidence = %+v", items)
	}
	if items[0].EvidenceRef.AsOf.Equal(generatedAt) {
		t.Fatal("processing time became factual evidence time")
	}
}

func TestComparisonMaterialRejectsAuthorityAfterRequestedAsOf(t *testing.T) {
	asOf := time.Date(2026, 7, 24, 10, 32, 53, 0, time.UTC)
	provider := Provider{peers: productscope.PeerEvaluationSuite{
		Lanes: []productscope.PeerEvaluationResult{{
			LaneID:     "microsoft-alphabet",
			CompanyIDs: []string{"company-a", "company-b"},
			Receipts: []contracts.MetricComparabilityReceipt{{
				ReceiptID:             "receipt-fcf",
				AsOf:                  asOf.Add(time.Second),
				GeneratedAt:           asOf.Add(time.Minute),
				Disposition:           contracts.ComparisonComparable,
				ReceiptSHA256:         strings.Repeat("a", 64),
				ReviewerPolicyVersion: "comparability/v1",
				Operands: []contracts.MetricComparisonOperand{{
					CanonicalMetricID: "financial.free_cash_flow",
				}},
			}},
		}},
	}}
	items, missing := provider.comparisonMaterial(contracts.ContextRequest{
		Scope: contracts.Scope{
			CompanyIDs: []string{"company-a", "company-b"},
			AsOf:       asOf,
		},
	})
	if len(items) != 0 {
		t.Fatalf("future comparison evidence escaped: %+v", items)
	}
	if !strings.Contains(strings.Join(missing, " "), "later than the requested as-of boundary") {
		t.Fatalf("future comparison authority was not disclosed: %+v", missing)
	}
}

func TestModelVisibleMissingEvidenceRemovesBoundedCardinalWording(t *testing.T) {
	values := normalizeModelVisibleMissing([]string{
		"SignalForge withheld financial.revenue_growth because two annual standardized revenue periods unavailable.",
		"SignalForge withheld financial.free_cash_flow because one or both authorized operands are unavailable.",
	})
	joined := strings.Join(values, " ")
	if strings.Contains(joined, "two annual") || strings.Contains(joined, "one or both") {
		t.Fatalf("model-visible missing evidence retained cardinal wording: %q", joined)
	}
	if !strings.Contains(joined, "required annual standardized revenue history") ||
		!strings.Contains(joined, "required authorized operands") {
		t.Fatalf("normalized boundaries lost their governed meaning: %q", joined)
	}
}
