package domaincontrols

import (
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
	"unicode"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

type Decision struct {
	Allowed bool
	Codes   []string
}

var (
	isoDateRange = regexp.MustCompile(`(?i)\b(?:from\s+)?(\d{4}-\d{2}-\d{2})\s+(?:to|through|until)\s+(\d{4}-\d{2}-\d{2})\b`)
	fiscalYear   = regexp.MustCompile(`(?i)\b(?:fiscal\s+year|fy)\s*[-:]?\s*(20\d{2})\b`)
)

// ResolvePeriod preserves fiscal identity rather than converting a fiscal year to calendar dates.
func ResolvePeriod(text string, asOf time.Time) (contracts.PeriodScope, Decision) {
	lower := strings.ToLower(strings.TrimSpace(text))
	result := contracts.PeriodScope{Kind: "latest_available"}
	decision := Decision{Allowed: true}
	if match := isoDateRange.FindStringSubmatch(lower); len(match) == 3 {
		start, startErr := time.Parse("2006-01-02", match[1])
		end, endErr := time.Parse("2006-01-02", match[2])
		if startErr != nil || endErr != nil || end.Before(start) {
			return result, Decision{Codes: []string{"invalid_explicit_date_range"}}
		}
		start, end = start.UTC(), end.UTC()
		result = contracts.PeriodScope{Kind: "explicit_calendar_range", Start: &start, End: &end}
		if end.After(asOf.UTC()) {
			decision.Allowed = false
			decision.Codes = append(decision.Codes, "future_information_unavailable")
		}
		return result, decision
	}
	if match := fiscalYear.FindStringSubmatch(lower); len(match) == 2 {
		year := 0
		_, _ = fmt.Sscanf(match[1], "%d", &year)
		result = contracts.PeriodScope{Kind: "fiscal_year", FiscalYears: []int{year}}
		if year > asOf.UTC().Year()+1 {
			decision.Allowed = false
			decision.Codes = append(decision.Codes, "future_fiscal_period_unavailable")
		}
		return result, decision
	}
	switch {
	case strings.Contains(lower, "last fiscal year") || strings.Contains(lower, "previous fiscal year"):
		result.Kind = "previous_fiscal_year"
	case strings.Contains(lower, "five years") || strings.Contains(lower, "five fiscal years"):
		result.Kind, result.LookbackYears = "trailing_fiscal_years", 5
	case strings.Contains(lower, "three years") || strings.Contains(lower, "three fiscal years"):
		result.Kind, result.LookbackYears = "trailing_fiscal_years", 3
	case strings.Contains(lower, "latest 10-q") || strings.Contains(lower, "latest quarter"):
		result.Kind = "latest_fiscal_quarter"
	case strings.Contains(lower, "current price") || strings.Contains(lower, "today"):
		result.Kind = "current_and_latest_reported"
	}
	return result, decision
}

func AssessLanguage(text string) Decision {
	lower := " " + strings.ToLower(strings.TrimSpace(text)) + " "
	nonEnglishMarkers := []string{
		" qual ", " quais ", " explique ", " empresa ", " ação ", " ações ", " comprar ", " vender ",
		" cuál ", " cuáles ", " empresa ", " comprar ", " vender ", " analysez ", " entreprise ",
	}
	for _, marker := range nonEnglishMarkers {
		if strings.Contains(lower, marker) {
			return Decision{Allowed: false, Codes: []string{"non_english_input"}}
		}
	}
	for _, value := range text {
		if unicode.IsLetter(value) && value > unicode.MaxASCII {
			return Decision{Allowed: false, Codes: []string{"language_requires_review"}}
		}
	}
	return Decision{Allowed: true, Codes: []string{"english_compatible_input"}}
}

func AssessResponsibleScope(text string) Decision {
	lower := strings.ToLower(text)
	codes := []string{}
	for _, item := range []struct {
		code  string
		terms []string
	}{
		{"guaranteed_return_request", []string{"guarantee a return", "guaranteed return", "risk-free profit"}},
		{"personalized_trade_instruction", []string{"must buy", "tell me to sell", "should i buy", "should i sell"}},
		{"personalized_allocation_request", []string{"allocate my portfolio", "all my savings", "what percentage should i invest"}},
		{"short_term_price_prediction", []string{"exact price next week", "price tomorrow", "predict the stock price"}},
		{"unsupported_market", []string{"b3:", "bovespa", "cryptocurrency", "bitcoin", "forex signal"}},
	} {
		for _, term := range item.terms {
			if strings.Contains(lower, term) {
				codes = append(codes, item.code)
				break
			}
		}
	}
	return Decision{Allowed: len(codes) == 0, Codes: unique(codes)}
}

func ValidateAccountingFramework(evidenceFramework string, userText string) error {
	framework := strings.ToUpper(strings.TrimSpace(evidenceFramework))
	explicitComparison := strings.Contains(strings.ToLower(userText), "ifrs") &&
		(strings.Contains(strings.ToLower(userText), "compare") ||
			strings.Contains(strings.ToLower(userText), "difference") ||
			strings.Contains(strings.ToLower(userText), "versus"))
	switch framework {
	case "US-GAAP", "SEC":
		return nil
	case "IFRS":
		if !explicitComparison {
			return errors.New("ifrs_evidence_not_authorized_for_us_issuer_conclusion")
		}
		return nil
	default:
		return fmt.Errorf("unsupported_accounting_framework:%s", framework)
	}
}

type MarketSeries struct {
	SeriesID           string
	Feed               string
	Coverage           string
	AdjustmentMode     string
	CorporateActionIDs []string
	ObservedAt         time.Time
	AvailableAt        time.Time
	SessionTimezone    string
}

func ValidateMarketSeries(series MarketSeries, asOf time.Time) error {
	if series.SeriesID == "" || series.Feed == "" || series.Coverage == "" ||
		series.AdjustmentMode == "" || series.ObservedAt.IsZero() ||
		series.AvailableAt.IsZero() || series.SessionTimezone == "" {
		return errors.New("market_series_lineage_incomplete")
	}
	if series.AvailableAt.After(asOf) || series.AvailableAt.Before(series.ObservedAt) {
		return errors.New("market_series_temporal_boundary_invalid")
	}
	switch series.AdjustmentMode {
	case "raw":
		if len(series.CorporateActionIDs) > 0 {
			return errors.New("raw_series_cannot_claim_applied_corporate_actions")
		}
	case "split_adjusted", "fully_adjusted":
		if len(series.CorporateActionIDs) == 0 {
			return errors.New("adjusted_series_requires_corporate_action_lineage")
		}
	default:
		return errors.New("unsupported_market_adjustment_mode")
	}
	if strings.EqualFold(series.Feed, "iex") && strings.Contains(strings.ToLower(series.Coverage), "sip") {
		return errors.New("iex_cannot_claim_consolidated_sip_coverage")
	}
	return nil
}

type NarrativeDiff struct {
	Similarity           float64
	AddedMaterialTerms   []string
	RemovedMaterialTerms []string
	MaterialCandidate    bool
}

type NarrativeClassification struct {
	ClaimClass              string
	LifecycleEvent          string
	RequiresPrimaryEvidence bool
	MayReleaseAsFact        bool
}

func ClassifyIssuerNarrative(text string) NarrativeClassification {
	lower := strings.ToLower(text)
	result := NarrativeClassification{
		ClaimClass: "reported_description", RequiresPrimaryEvidence: true, MayReleaseAsFact: true,
	}
	if containsAny(lower, "world-leading", "best-in-class", "unmatched", "industry-leading") {
		result.ClaimClass = "management_promotional_claim"
		result.MayReleaseAsFact = false
	}
	switch {
	case containsAny(lower, "discontinued", "end-of-life", "no longer offers"):
		result.LifecycleEvent = "product_discontinued_candidate"
	case containsAny(lower, "reorganized", "realigned its segments", "segment reorganization"):
		result.LifecycleEvent = "segment_reorganization_candidate"
	case containsAny(lower, "acquired", "acquisition of", "business combination"):
		result.LifecycleEvent = "acquisition_candidate"
	}
	return result
}

var materialRiskTerms = []string{
	"customer concentration", "cybersecurity", "export control", "going concern",
	"liquidity", "material weakness", "regulatory investigation", "supply constraint",
}

func DiffRiskNarrative(previous, current string) NarrativeDiff {
	left, right := tokens(previous), tokens(current)
	intersection := 0
	for token := range left {
		if right[token] {
			intersection++
		}
	}
	union := len(left) + len(right) - intersection
	similarity := 1.0
	if union > 0 {
		similarity = float64(intersection) / float64(union)
	}
	added, removed := []string{}, []string{}
	previousLower, currentLower := strings.ToLower(previous), strings.ToLower(current)
	for _, term := range materialRiskTerms {
		if !strings.Contains(previousLower, term) && strings.Contains(currentLower, term) {
			added = append(added, term)
		}
		if strings.Contains(previousLower, term) && !strings.Contains(currentLower, term) {
			removed = append(removed, term)
		}
	}
	return NarrativeDiff{
		Similarity: similarity, AddedMaterialTerms: added, RemovedMaterialTerms: removed,
		MaterialCandidate: len(added)+len(removed) > 0 || similarity < 0.65,
	}
}

type MacroCandidate struct {
	VariableID  string
	Mechanism   string
	Confidence  string
	SourceClass string
}

var segmentMacroCandidates = map[string][]MacroCandidate{
	"semiconductor": {
		{VariableID: "fred:DGS10", Mechanism: "discount_rate_and_capital_cost", Confidence: "candidate", SourceClass: "official_macro"},
		{VariableID: "census:manufacturers_shipments", Mechanism: "end_market_demand", Confidence: "candidate", SourceClass: "official_industry"},
	},
	"enterprise_software": {
		{VariableID: "bls:CES0500000003", Mechanism: "enterprise_labor_and_spending", Confidence: "candidate", SourceClass: "official_macro"},
		{VariableID: "fred:BAMLC0A0CM", Mechanism: "customer_financing_conditions", Confidence: "candidate", SourceClass: "official_macro"},
	},
	"consumer_hardware": {
		{VariableID: "bls:CUUR0000SA0", Mechanism: "household_purchasing_power", Confidence: "candidate", SourceClass: "official_macro"},
		{VariableID: "fred:DTWEXBGS", Mechanism: "fx_translation_and_affordability", Confidence: "candidate", SourceClass: "official_macro"},
	},
}

func CandidateMacroVariables(segmentClass string) ([]MacroCandidate, error) {
	result := append([]MacroCandidate(nil), segmentMacroCandidates[strings.ToLower(strings.TrimSpace(segmentClass))]...)
	if len(result) == 0 {
		return nil, errors.New("no_reviewed_segment_macro_mapping")
	}
	return result, nil
}

type SanctionsCandidate struct {
	EntityID       string
	MatchedAlias   string
	Exact          bool
	RequiresReview bool
}

func ResolveSanctionsEntity(name string, aliases map[string]string) SanctionsCandidate {
	normalized := normalize(name)
	for alias, entityID := range aliases {
		if normalize(alias) == normalized {
			return SanctionsCandidate{EntityID: entityID, MatchedAlias: alias, Exact: true}
		}
	}
	return SanctionsCandidate{RequiresReview: true}
}

type GrowthAttribution struct {
	TotalGrowthReceiptID   string
	OrganicEvidenceIDs     []string
	AcquisitionEvidenceIDs []string
	FXEvidenceIDs          []string
	AccountingEvidenceIDs  []string
}

func ValidateOrganicGrowthAttribution(value GrowthAttribution) error {
	if strings.TrimSpace(value.TotalGrowthReceiptID) == "" {
		return errors.New("total_growth_receipt_required")
	}
	if len(value.OrganicEvidenceIDs) == 0 {
		return errors.New("organic_growth_requires_primary_evidence")
	}
	if len(value.AcquisitionEvidenceIDs) == 0 && len(value.FXEvidenceIDs) == 0 &&
		len(value.AccountingEvidenceIDs) == 0 {
		return errors.New("organic_growth_requires_nonorganic_reconciliation")
	}
	return nil
}

type MacroSeriesMetadata struct {
	SeriesID           string
	SourceID           string
	Frequency          string
	SeasonalAdjustment string
	MethodologyVersion string
	MethodologyBreaks  []time.Time
	VintageDate        time.Time
	AvailableAt        time.Time
}

func ValidateMacroSeriesMetadata(value MacroSeriesMetadata, asOf time.Time) error {
	if value.SeriesID == "" || value.SourceID == "" || value.Frequency == "" ||
		value.SeasonalAdjustment == "" || value.MethodologyVersion == "" ||
		value.VintageDate.IsZero() || value.AvailableAt.IsZero() {
		return errors.New("macro_series_metadata_incomplete")
	}
	if value.AvailableAt.After(asOf) || value.VintageDate.After(asOf) {
		return errors.New("macro_series_future_vintage")
	}
	for _, observed := range value.MethodologyBreaks {
		if observed.After(asOf) {
			return errors.New("macro_series_future_methodology_break")
		}
	}
	return nil
}

func tokens(value string) map[string]bool {
	result := map[string]bool{}
	for _, field := range strings.FieldsFunc(strings.ToLower(value), func(r rune) bool {
		return !unicode.IsLetter(r) && !unicode.IsDigit(r)
	}) {
		if len(field) > 2 {
			result[field] = true
		}
	}
	return result
}

func normalize(value string) string {
	return strings.Join(strings.Fields(strings.ToLower(strings.TrimSpace(value))), " ")
}

func containsAny(value string, candidates ...string) bool {
	for _, candidate := range candidates {
		if strings.Contains(value, candidate) {
			return true
		}
	}
	return false
}

func unique(values []string) []string {
	set := map[string]bool{}
	for _, value := range values {
		set[value] = true
	}
	result := make([]string, 0, len(set))
	for value := range set {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}
