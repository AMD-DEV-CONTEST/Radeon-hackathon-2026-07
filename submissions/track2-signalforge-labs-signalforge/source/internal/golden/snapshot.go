package golden

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/cockroachdb/apd/v3"
	"github.com/rvbernucci/signalforge/internal/numeric"
)

const SnapshotSchemaV1 = "signalforge/golden-financial-snapshot/v1"

type Snapshot struct {
	SchemaVersion                string    `json:"schema_version"`
	AsOf                         time.Time `json:"as_of"`
	NormalizationPolicy          string    `json:"normalization_policy"`
	MarketPricesAreRuntimeInputs bool      `json:"market_prices_are_runtime_inputs"`
	Companies                    []Company `json:"companies"`
}

type Company struct {
	CompanyID    string     `json:"company_id"`
	Ticker       string     `json:"ticker"`
	LegalName    string     `json:"legal_name"`
	FiscalPeriod string     `json:"fiscal_period"`
	PeriodStart  time.Time  `json:"period_start"`
	PeriodEnd    time.Time  `json:"period_end"`
	Metrics      []Metric   `json:"metrics"`
	Scenarios    []Scenario `json:"scenarios"`
}

type Metric struct {
	MetricID            string    `json:"metric_id"`
	Value               string    `json:"value"`
	Unit                string    `json:"unit"`
	Currency            string    `json:"currency,omitempty"`
	Period              string    `json:"period,omitempty"`
	EvidenceID          string    `json:"evidence_id"`
	SourceFactID        string    `json:"source_fact_id"`
	SourceAvailableAt   time.Time `json:"source_available_at"`
	ComparabilityStatus string    `json:"comparability_status"`
}

type Scenario struct {
	Name            string `json:"name"`
	AnnualFCFGrowth string `json:"annual_fcf_growth"`
	DiscountRate    string `json:"discount_rate"`
	TerminalGrowth  string `json:"terminal_growth"`
}

func LoadSnapshot(path string) (Snapshot, error) {
	payload, err := os.ReadFile(path)
	if err != nil {
		return Snapshot{}, err
	}
	var snapshot Snapshot
	if err := json.Unmarshal(payload, &snapshot); err != nil {
		return Snapshot{}, err
	}
	if err := ValidateSnapshot(snapshot); err != nil {
		return Snapshot{}, err
	}
	return snapshot, nil
}

func ValidateSnapshot(snapshot Snapshot) error {
	if snapshot.SchemaVersion != SnapshotSchemaV1 || snapshot.AsOf.IsZero() || strings.TrimSpace(snapshot.NormalizationPolicy) == "" {
		return errors.New("snapshot schema, as_of, and normalization policy are required")
	}
	if !snapshot.MarketPricesAreRuntimeInputs {
		return errors.New("golden snapshot must keep market prices outside the frozen fixture")
	}
	if len(snapshot.Companies) != 2 {
		return fmt.Errorf("golden snapshot requires exactly two companies, got %d", len(snapshot.Companies))
	}
	companyIDs, tickers := map[string]bool{}, map[string]bool{}
	for index, company := range snapshot.Companies {
		if company.CompanyID == "" || company.Ticker == "" || company.LegalName == "" || company.FiscalPeriod == "" || company.PeriodStart.IsZero() || company.PeriodEnd.IsZero() || !company.PeriodEnd.After(company.PeriodStart) {
			return fmt.Errorf("companies[%d] is incomplete", index)
		}
		if companyIDs[company.CompanyID] || tickers[company.Ticker] {
			return fmt.Errorf("companies[%d] duplicates company or ticker identity", index)
		}
		companyIDs[company.CompanyID], tickers[company.Ticker] = true, true
		metrics := map[string]bool{}
		for metricIndex, metric := range company.Metrics {
			if metric.MetricID == "" || metric.EvidenceID == "" || metric.SourceFactID == "" || metric.Unit == "" || metric.ComparabilityStatus == "" || metric.SourceAvailableAt.IsZero() {
				return fmt.Errorf("companies[%d].metrics[%d] is incomplete", index, metricIndex)
			}
			if metric.SourceAvailableAt.After(snapshot.AsOf) {
				return fmt.Errorf("metric %q was unavailable at snapshot as_of", metric.EvidenceID)
			}
			if _, err := numeric.ParseDecimal(metric.Value); err != nil {
				return fmt.Errorf("metric %q: %w", metric.EvidenceID, err)
			}
			if (metric.Unit == "currency" || metric.Unit == "currency_per_share") != (len(metric.Currency) == 3) {
				return fmt.Errorf("metric %q has inconsistent monetary metadata", metric.EvidenceID)
			}
			if metrics[metric.MetricID] {
				return fmt.Errorf("company %q duplicates metric %q", company.Ticker, metric.MetricID)
			}
			metrics[metric.MetricID] = true
		}
		for _, required := range []string{"revenue", "revenue_prior", "operating_income", "net_income", "operating_cash_flow", "capital_expenditure", "diluted_eps", "diluted_shares"} {
			if !metrics[required] {
				return fmt.Errorf("company %q is missing metric %q", company.Ticker, required)
			}
		}
		scenarioNames := map[string]bool{}
		for scenarioIndex, scenario := range company.Scenarios {
			if scenario.Name == "" || scenarioNames[scenario.Name] {
				return fmt.Errorf("companies[%d].scenarios[%d] has invalid identity", index, scenarioIndex)
			}
			scenarioNames[scenario.Name] = true
			for _, value := range []string{scenario.AnnualFCFGrowth, scenario.DiscountRate, scenario.TerminalGrowth} {
				if _, err := numeric.ParseDecimal(value); err != nil {
					return fmt.Errorf("company %q scenario %q: %w", company.Ticker, scenario.Name, err)
				}
			}
			if compareDecimal(scenario.DiscountRate, scenario.TerminalGrowth) <= 0 {
				return fmt.Errorf("company %q scenario %q requires discount rate above terminal growth", company.Ticker, scenario.Name)
			}
		}
		for _, required := range []string{"bear", "base", "bull"} {
			if !scenarioNames[required] {
				return fmt.Errorf("company %q is missing scenario %q", company.Ticker, required)
			}
		}
	}
	return nil
}

func (snapshot Snapshot) Company(companyID string) (Company, bool) {
	for _, company := range snapshot.Companies {
		if company.CompanyID == companyID {
			return company, true
		}
	}
	return Company{}, false
}

func (company Company) Metric(metricID string) (Metric, bool) {
	for _, metric := range company.Metrics {
		if metric.MetricID == metricID {
			if metric.Period == "" {
				metric.Period = company.FiscalPeriod
			}
			return metric, true
		}
	}
	return Metric{}, false
}

func (company Company) OrderedScenarios() []Scenario {
	result := append([]Scenario(nil), company.Scenarios...)
	order := map[string]int{"bear": 0, "base": 1, "bull": 2}
	sort.Slice(result, func(i, j int) bool { return order[result[i].Name] < order[result[j].Name] })
	return result
}

func compareDecimal(left, right string) int {
	a, _, _ := apd.NewFromString(numeric.MustDecimal(left).String())
	b, _, _ := apd.NewFromString(numeric.MustDecimal(right).String())
	return a.Cmp(b)
}
