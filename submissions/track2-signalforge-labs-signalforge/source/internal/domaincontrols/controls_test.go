package domaincontrols

import (
	"testing"
	"time"
)

func TestResolvePeriodPreservesFiscalIdentityAndRejectsFutureRange(t *testing.T) {
	asOf := time.Date(2026, 7, 23, 0, 0, 0, 0, time.UTC)
	period, decision := ResolvePeriod("Compare FY 2025 with the last fiscal year.", asOf)
	if !decision.Allowed || period.Kind != "fiscal_year" || len(period.FiscalYears) != 1 ||
		period.FiscalYears[0] != 2025 || period.Start != nil || period.End != nil {
		t.Fatalf("fiscal identity was not preserved: %+v %+v", period, decision)
	}
	_, decision = ResolvePeriod("From 2026-01-01 to 2027-01-01", asOf)
	if decision.Allowed || decision.Codes[0] != "future_information_unavailable" {
		t.Fatalf("future period was accepted: %+v", decision)
	}
}

func TestLanguageAndResponsibleScopeFailClosed(t *testing.T) {
	if !AssessLanguage("Compare Microsoft and NVIDIA.").Allowed {
		t.Fatal("English request was rejected")
	}
	if AssessLanguage("Qual empresa devo comprar?").Allowed {
		t.Fatal("non-English request was silently treated as English")
	}
	for _, text := range []string{
		"Tell me the exact price next week.",
		"What percentage should I invest?",
		"Give me a Bovespa trading signal.",
	} {
		if AssessResponsibleScope(text).Allowed {
			t.Fatalf("unsupported request was accepted: %q", text)
		}
	}
}

func TestAccountingFrameworkRequiresExplicitComparison(t *testing.T) {
	if err := ValidateAccountingFramework("IFRS", "Explain Microsoft's revenue recognition."); err == nil {
		t.Fatal("IFRS evidence was admitted into an unrequested US issuer conclusion")
	}
	if err := ValidateAccountingFramework("IFRS", "Compare the US-GAAP and IFRS differences."); err != nil {
		t.Fatal(err)
	}
}

func TestMarketLineageAndFeedIdentity(t *testing.T) {
	asOf := time.Date(2026, 7, 23, 12, 0, 0, 0, time.UTC)
	valid := MarketSeries{
		SeriesID: "bars-msft", Feed: "iex", Coverage: "iex_venue",
		AdjustmentMode: "split_adjusted", CorporateActionIDs: []string{"split-1"},
		ObservedAt: asOf.Add(-time.Hour), AvailableAt: asOf.Add(-30 * time.Minute),
		SessionTimezone: "America/New_York",
	}
	if err := ValidateMarketSeries(valid, asOf); err != nil {
		t.Fatal(err)
	}
	valid.CorporateActionIDs = nil
	if err := ValidateMarketSeries(valid, asOf); err == nil {
		t.Fatal("adjusted series without corporate-action lineage was accepted")
	}
	valid.CorporateActionIDs = []string{"split-1"}
	valid.Coverage = "consolidated SIP"
	if err := ValidateMarketSeries(valid, asOf); err == nil {
		t.Fatal("IEX series claimed SIP coverage")
	}
}

func TestNarrativeDiffFindsMaterialCandidatesWithoutMakingAConclusion(t *testing.T) {
	diff := DiffRiskNarrative(
		"We face ordinary competition and demand uncertainty.",
		"We face ordinary competition, customer concentration, and a regulatory investigation.",
	)
	if !diff.MaterialCandidate || len(diff.AddedMaterialTerms) != 2 {
		t.Fatalf("material change candidates were missed: %+v", diff)
	}
}

func TestMacroAndSanctionsCandidatesRemainReviewBounded(t *testing.T) {
	candidates, err := CandidateMacroVariables("semiconductor")
	if err != nil || len(candidates) == 0 || candidates[0].Confidence != "candidate" {
		t.Fatalf("unexpected macro candidates: %+v %v", candidates, err)
	}
	if _, err := CandidateMacroVariables("unknown"); err == nil {
		t.Fatal("unknown segment silently received macro variables")
	}
	aliases := map[string]string{"Example Holdings Ltd.": "ofac:123"}
	exact := ResolveSanctionsEntity("example holdings ltd.", aliases)
	if !exact.Exact || exact.RequiresReview {
		t.Fatalf("exact alias did not resolve: %+v", exact)
	}
	uncertain := ResolveSanctionsEntity("Example Holding", aliases)
	if uncertain.Exact || !uncertain.RequiresReview {
		t.Fatalf("fuzzy sanctions name was silently accepted: %+v", uncertain)
	}
}

func TestNarrativeLifecycleAndPromotionalClaimsRemainBounded(t *testing.T) {
	promotional := ClassifyIssuerNarrative("Management calls the platform world-leading.")
	if promotional.ClaimClass != "management_promotional_claim" || promotional.MayReleaseAsFact {
		t.Fatalf("promotional claim was treated as fact: %+v", promotional)
	}
	for text, expected := range map[string]string{
		"The product was discontinued.":                      "product_discontinued_candidate",
		"The company realigned its segments this quarter.":   "segment_reorganization_candidate",
		"The issuer completed the acquisition of ExampleCo.": "acquisition_candidate",
	} {
		classification := ClassifyIssuerNarrative(text)
		if classification.LifecycleEvent != expected || !classification.RequiresPrimaryEvidence {
			t.Fatalf("unexpected lifecycle classification for %q: %+v", text, classification)
		}
	}
}

func TestOrganicGrowthRequiresReceiptAndNonorganicReconciliation(t *testing.T) {
	value := GrowthAttribution{
		TotalGrowthReceiptID: "receipt-growth",
		OrganicEvidenceIDs:   []string{"evidence-organic"},
	}
	if err := ValidateOrganicGrowthAttribution(value); err == nil {
		t.Fatal("organic growth was accepted without nonorganic reconciliation")
	}
	value.AcquisitionEvidenceIDs = []string{"evidence-acquisition"}
	if err := ValidateOrganicGrowthAttribution(value); err != nil {
		t.Fatal(err)
	}
}

func TestMacroMetadataPreservesSeasonalityMethodologyAndVintage(t *testing.T) {
	asOf := time.Date(2026, 7, 23, 0, 0, 0, 0, time.UTC)
	value := MacroSeriesMetadata{
		SeriesID: "bls:CPI", SourceID: "bls-public-api", Frequency: "monthly",
		SeasonalAdjustment: "seasonally_adjusted", MethodologyVersion: "2025-reference",
		MethodologyBreaks: []time.Time{time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)},
		VintageDate:       time.Date(2026, 7, 15, 0, 0, 0, 0, time.UTC),
		AvailableAt:       time.Date(2026, 7, 15, 12, 0, 0, 0, time.UTC),
	}
	if err := ValidateMacroSeriesMetadata(value, asOf); err != nil {
		t.Fatal(err)
	}
	value.MethodologyBreaks = append(value.MethodologyBreaks, asOf.AddDate(0, 1, 0))
	if err := ValidateMacroSeriesMetadata(value, asOf); err == nil {
		t.Fatal("future methodology break was accepted")
	}
}
