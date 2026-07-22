package normalize

import (
	"crypto/sha256"
	"encoding/hex"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/data"
)

const PolicyVersion = "sec-companyfacts-point-in-time/v1"

type mapping struct {
	Metric string
	Rank   int
}

var canonicalConcepts = map[string]mapping{
	"RevenueFromContractWithCustomerExcludingAssessedTax": {Metric: "revenue", Rank: 1},
	"Revenues":                              {Metric: "revenue", Rank: 2},
	"SalesRevenueNet":                       {Metric: "revenue", Rank: 3},
	"NetIncomeLoss":                         {Metric: "net_income", Rank: 1},
	"OperatingIncomeLoss":                   {Metric: "operating_income", Rank: 1},
	"Assets":                                {Metric: "total_assets", Rank: 1},
	"Liabilities":                           {Metric: "total_liabilities", Rank: 1},
	"StockholdersEquity":                    {Metric: "stockholders_equity", Rank: 1},
	"CashAndCashEquivalentsAtCarryingValue": {Metric: "cash_and_equivalents", Rank: 1},
	"NetCashProvidedByUsedInOperatingActivities": {Metric: "operating_cash_flow", Rank: 1},
	"PaymentsToAcquirePropertyPlantAndEquipment": {Metric: "capital_expenditure", Rank: 1},
	"PaymentsToAcquireProductiveAssets":          {Metric: "capital_expenditure", Rank: 2},
	"ResearchAndDevelopmentExpense":              {Metric: "research_and_development", Rank: 1},
	"ShareBasedCompensation":                     {Metric: "share_based_compensation", Rank: 1},
}

type candidate struct {
	fact    data.ReportedFact
	mapping mapping
}

func AsOf(facts []data.ReportedFact, asOf, computedAt time.Time) []data.NormalizedMetric {
	groups := map[string][]candidate{}
	for _, fact := range facts {
		mapped, ok := canonicalConcepts[fact.Concept]
		if !ok || fact.Taxonomy != "us-gaap" || !data.IsAvailableAsOf(data.Availability{AvailableAt: fact.AvailableAt}, asOf) {
			continue
		}
		start, end, periodType := period(fact)
		key := strings.Join([]string{fact.CompanyID, mapped.Metric, start.Format(time.RFC3339), end.Format(time.RFC3339), periodType, fact.Unit}, "\x1f")
		groups[key] = append(groups[key], candidate{fact: fact, mapping: mapped})
	}
	metrics := make([]data.NormalizedMetric, 0, len(groups))
	for _, candidates := range groups {
		sort.SliceStable(candidates, func(i, j int) bool {
			if candidates[i].fact.AvailableAt.Equal(candidates[j].fact.AvailableAt) {
				if candidates[i].mapping.Rank == candidates[j].mapping.Rank {
					return candidates[i].fact.FactID < candidates[j].fact.FactID
				}
				return candidates[i].mapping.Rank > candidates[j].mapping.Rank
			}
			return candidates[i].fact.AvailableAt.Before(candidates[j].fact.AvailableAt)
		})
		selected := candidates[len(candidates)-1]
		start, end, periodType := period(selected.fact)
		flags := qualityFlags(candidates, selected)
		sourceFactIDs := make([]string, 0, len(candidates))
		for _, item := range candidates {
			sourceFactIDs = append(sourceFactIDs, item.fact.FactID)
		}
		metric := data.NormalizedMetric{
			MetricID:  "metric:" + stableID(selected.fact.CompanyID, selected.mapping.Metric, start.Format(time.RFC3339), end.Format(time.RFC3339), selected.fact.Unit, selected.fact.FactID),
			CompanyID: selected.fact.CompanyID, CanonicalMetric: selected.mapping.Metric,
			PeriodStart: start, PeriodEnd: end, PeriodType: periodType, Value: selected.fact.Value,
			Unit: selected.fact.Unit, SourceFactIDs: sourceFactIDs,
			TransformationID: "normalize.sec-companyfacts/v1", NormalizationPolicy: PolicyVersion,
			ComparabilityStatus: comparability(selected.mapping), QualityFlags: flags,
			SourceAvailableAt: selected.fact.AvailableAt, ComputedAt: computedAt.UTC(),
		}
		if selected.fact.Unit == "USD" {
			metric.Currency = "USD"
		}
		if data.ValidateNormalizedMetric(metric) == nil {
			metrics = append(metrics, metric)
		}
	}
	sort.Slice(metrics, func(i, j int) bool { return metrics[i].MetricID < metrics[j].MetricID })
	return metrics
}

func period(fact data.ReportedFact) (time.Time, time.Time, string) {
	if fact.InstantDate != nil {
		return *fact.InstantDate, *fact.InstantDate, "instant"
	}
	return *fact.StartDate, *fact.EndDate, "duration"
}

func comparability(mapped mapping) string {
	if mapped.Rank == 1 {
		return "standardized"
	}
	return "concept_alias"
}

func qualityFlags(candidates []candidate, selected candidate) []string {
	flags := []string{}
	values := map[string]bool{}
	for _, item := range candidates {
		values[item.fact.Value] = true
	}
	if len(values) > 1 {
		flags = append(flags, "later_filing_changed_value")
	}
	if strings.HasSuffix(selected.fact.FormType, "/A") {
		flags = append(flags, "selected_from_amendment")
	}
	if selected.mapping.Rank > 1 {
		flags = append(flags, "canonical_concept_alias")
	}
	return flags
}

func stableID(parts ...string) string {
	digest := sha256.Sum256([]byte(strings.Join(parts, "\x1f")))
	return hex.EncodeToString(digest[:])
}
