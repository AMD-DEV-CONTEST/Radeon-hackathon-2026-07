package productscope

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/capability"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/data"
	"github.com/rvbernucci/signalforge/internal/engine"
	"github.com/rvbernucci/signalforge/internal/roles"
)

const CompanyFinancialActivationSchemaV1 = "signalforge/technology20-financial-activation/v1"
const FinancialMetricFreshnessPolicy = "period-end-age-760d/v1"
const FinancialConsolidationPolicy = "dimensionless-consolidated-facts-only/v1"
const CapexPerimeterPolicy = "us-gaap-payments-to-acquire-ppe-only/v1"

type CompanyFinancialActivation struct {
	SchemaVersion        string                         `json:"schema_version"`
	UniverseID           string                         `json:"universe_id"`
	CompanyID            string                         `json:"company_id"`
	AsOf                 time.Time                      `json:"as_of"`
	CodeCommit           string                         `json:"code_commit"`
	FreshnessPolicy      string                         `json:"freshness_policy"`
	ConsolidationPolicy  string                         `json:"consolidation_policy"`
	CapexPerimeterPolicy string                         `json:"capex_perimeter_policy"`
	Receipts             []contracts.CalculationReceipt `json:"receipts"`
	Abstentions          []contracts.TypedAbstention    `json:"abstentions"`
	Excluded             map[string]int                 `json:"excluded_records"`
	SourceConcepts       map[string][]string            `json:"source_concepts"`
	SourceForms          map[string][]string            `json:"source_forms"`
	ReportSHA256         string                         `json:"report_sha256"`
}

type operationSpec struct {
	OperationID string
	Inputs      map[string]string
	PeriodType  string
	Annual      bool
	Role        string
}

var companyOperationSpecs = []operationSpec{
	{
		OperationID: "accounting.balance_sheet_identity", PeriodType: "instant",
		Inputs: map[string]string{"assets": "total_assets", "liabilities": "total_liabilities", "equity": "stockholders_equity"},
		Role:   roles.AccountingReporting,
	},
	{
		OperationID: "financial.revenue_growth", PeriodType: "duration", Annual: true,
		Inputs: map[string]string{"revenue_current": "revenue", "revenue_prior": "revenue"},
		Role:   roles.FinancialQuality,
	},
	{
		OperationID: "financial.operating_margin", PeriodType: "duration", Annual: true,
		Inputs: map[string]string{"operating_income": "operating_income", "revenue": "revenue"},
		Role:   roles.FinancialQuality,
	},
	{
		OperationID: "financial.free_cash_flow", PeriodType: "duration", Annual: true,
		Inputs: map[string]string{"operating_cash_flow": "operating_cash_flow", "capital_expenditure": "capital_expenditure"},
		Role:   roles.FinancialQuality,
	},
	{
		OperationID: "financial.cash_conversion", PeriodType: "duration", Annual: true,
		Inputs: map[string]string{"operating_cash_flow": "operating_cash_flow", "net_income": "net_income"},
		Role:   roles.FinancialQuality,
	},
	{
		OperationID: "financial.capex_intensity", PeriodType: "duration", Annual: true,
		Inputs: map[string]string{"capital_expenditure": "capital_expenditure", "revenue": "revenue"},
		Role:   roles.FinancialQuality,
	},
	{
		OperationID: "financial.quality_of_earnings", PeriodType: "duration", Annual: true,
		Inputs: map[string]string{"operating_cash_flow": "operating_cash_flow", "net_income": "net_income"},
		Role:   roles.FinancialQuality,
	},
}

var unavailableCompanyOperations = []string{
	"financial.dilution",
	"financial.net_debt",
	"financial.current_ratio",
	"financial.debt_to_equity",
	"financial.earnings_per_share",
	"financial.roic",
	"valuation.fcff_dcf",
	"valuation.peer_multiple",
}

func BuildCompanyFinancialActivation(
	companyID string,
	metrics []data.NormalizedMetric,
	facts map[string]data.ReportedFact,
	asOf time.Time,
	codeCommit string,
) (CompanyFinancialActivation, error) {
	if companyID == "" || asOf.IsZero() || strings.TrimSpace(codeCommit) == "" {
		return CompanyFinancialActivation{}, errors.New("company, as_of, and code commit are required")
	}
	if !technologyCompany(companyID) {
		return CompanyFinancialActivation{}, errors.New("company is outside the Technology 20 authority")
	}
	report := CompanyFinancialActivation{
		SchemaVersion: CompanyFinancialActivationSchemaV1, UniverseID: UniverseID,
		CompanyID: companyID, AsOf: asOf.UTC(), CodeCommit: codeCommit,
		FreshnessPolicy:      FinancialMetricFreshnessPolicy,
		ConsolidationPolicy:  FinancialConsolidationPolicy,
		CapexPerimeterPolicy: CapexPerimeterPolicy, Excluded: map[string]int{},
		SourceConcepts: map[string][]string{}, SourceForms: map[string][]string{},
	}
	eligible := make([]data.NormalizedMetric, 0, len(metrics))
	for _, metric := range metrics {
		if metric.CompanyID != companyID {
			continue
		}
		if err := data.ValidateNormalizedMetric(metric); err != nil {
			report.Excluded["invalid_metric_contract"]++
			continue
		}
		if metric.SourceAvailableAt.After(asOf) {
			report.Excluded["look_ahead"]++
			continue
		}
		if asOf.Sub(metric.PeriodEnd) > 760*24*time.Hour {
			report.Excluded["stale_metric_period"]++
			continue
		}
		if metric.ComparabilityStatus != "standardized" {
			report.Excluded["unreviewed_semantic_mapping"]++
			continue
		}
		fact, authorized := periodicFactAuthority(metric, facts)
		if !authorized {
			report.Excluded["periodic_fact_authority_missing"]++
			continue
		}
		if metric.CanonicalMetric == "capital_expenditure" &&
			fact.Concept != "PaymentsToAcquirePropertyPlantAndEquipment" {
			report.Excluded["capex_perimeter_not_approved"]++
			continue
		}
		if metric.Unit != "USD" || metric.Currency != "USD" {
			report.Excluded["unit_or_currency_mismatch"]++
			continue
		}
		report.SourceConcepts[metric.CanonicalMetric] = appendUniqueSorted(
			report.SourceConcepts[metric.CanonicalMetric], fact.Concept,
		)
		report.SourceForms[metric.CanonicalMetric] = appendUniqueSorted(
			report.SourceForms[metric.CanonicalMetric], fact.FormType,
		)
		eligible = append(eligible, metric)
	}
	executor, err := engine.NewWithClock(codeCommit, func() time.Time { return asOf.UTC() })
	if err != nil {
		return CompanyFinancialActivation{}, err
	}
	runID := "run-activation-" + strings.TrimPrefix(companyID, "sec-cik:")
	for _, spec := range companyOperationSpecs {
		inputs, reason := selectOperationInputs(eligible, spec)
		if reason != "" {
			report.Abstentions = append(report.Abstentions, operationAbstention(
				runID, companyID, spec.OperationID, reason, asOf,
			))
			continue
		}
		request, requestErr := operationRequest(runID, companyID, spec, inputs)
		if requestErr != nil {
			return CompanyFinancialActivation{}, requestErr
		}
		result := executor.Execute(request)
		if result.Failure != nil {
			report.Abstentions = append(report.Abstentions, operationAbstention(
				runID, companyID, spec.OperationID, result.Failure.FailureCode, asOf,
			))
			continue
		}
		report.Receipts = append(report.Receipts, *result.Receipt)
	}
	for _, operationID := range unavailableCompanyOperations {
		report.Abstentions = append(report.Abstentions, operationAbstention(
			runID, companyID, operationID, "required_normalized_inputs_unavailable", asOf,
		))
	}
	sort.Slice(report.Receipts, func(i, j int) bool {
		return report.Receipts[i].OperationID < report.Receipts[j].OperationID
	})
	sort.Slice(report.Abstentions, func(i, j int) bool {
		return report.Abstentions[i].MetricIDs[0] < report.Abstentions[j].MetricIDs[0]
	})
	hash, err := companyFinancialActivationHash(report)
	if err != nil {
		return CompanyFinancialActivation{}, err
	}
	report.ReportSHA256 = hash
	return report, ValidateCompanyFinancialActivation(report)
}

func ValidateCompanyFinancialActivation(report CompanyFinancialActivation) error {
	if report.SchemaVersion != CompanyFinancialActivationSchemaV1 || report.UniverseID != UniverseID ||
		report.CompanyID == "" || report.AsOf.IsZero() || report.CodeCommit == "" || report.ReportSHA256 == "" {
		return errors.New("company financial activation envelope is invalid")
	}
	if report.FreshnessPolicy != FinancialMetricFreshnessPolicy {
		return errors.New("company financial activation freshness policy is invalid")
	}
	if report.ConsolidationPolicy != FinancialConsolidationPolicy ||
		report.CapexPerimeterPolicy != CapexPerimeterPolicy {
		return errors.New("company financial activation perimeter policy is invalid")
	}
	for metricID, concepts := range report.SourceConcepts {
		if metricID == "capital_expenditure" {
			for _, concept := range concepts {
				if concept != "PaymentsToAcquirePropertyPlantAndEquipment" {
					return errors.New("company financial activation contains an unauthorized capex concept")
				}
			}
		}
	}
	for _, forms := range report.SourceForms {
		for _, form := range forms {
			switch form {
			case "10-K", "10-K/A", "10-Q", "10-Q/A":
			default:
				return errors.New("company financial activation contains a non-periodic source form")
			}
		}
	}
	operations := map[string]bool{}
	for _, receipt := range report.Receipts {
		if err := contracts.ValidateCalculationReceipt(receipt); err != nil {
			return err
		}
		if operations[receipt.OperationID] || len(receipt.Scope.CompanyIDs) != 1 ||
			receipt.Scope.CompanyIDs[0] != report.CompanyID {
			return errors.New("company financial activation contains duplicate or cross-company receipt")
		}
		operations[receipt.OperationID] = true
	}
	for _, abstention := range report.Abstentions {
		if len(abstention.MetricIDs) != 1 || len(abstention.CompanyIDs) != 1 ||
			abstention.CompanyIDs[0] != report.CompanyID || operations[abstention.MetricIDs[0]] {
			return errors.New("company financial activation contains invalid abstention")
		}
		operations[abstention.MetricIDs[0]] = true
	}
	if len(operations) != len(companyOperationSpecs)+len(unavailableCompanyOperations) {
		return errors.New("company financial activation has incomplete operation coverage")
	}
	expected, err := companyFinancialActivationHash(report)
	if err != nil {
		return err
	}
	if expected != report.ReportSHA256 {
		return errors.New("company financial activation hash mismatch")
	}
	return nil
}

func selectOperationInputs(metrics []data.NormalizedMetric, spec operationSpec) (map[string]data.NormalizedMetric, string) {
	if spec.OperationID == "financial.revenue_growth" {
		return selectGrowthInputs(metrics)
	}
	required := make(map[string]bool)
	for _, canonical := range spec.Inputs {
		required[canonical] = true
	}
	type period struct {
		start time.Time
		end   time.Time
	}
	sets := map[period]map[string]data.NormalizedMetric{}
	for _, metric := range metrics {
		if !required[metric.CanonicalMetric] || metric.PeriodType != spec.PeriodType ||
			(spec.Annual && !annualDuration(metric.PeriodStart, metric.PeriodEnd)) {
			continue
		}
		key := period{start: metric.PeriodStart, end: metric.PeriodEnd}
		if sets[key] == nil {
			sets[key] = map[string]data.NormalizedMetric{}
		}
		prior, exists := sets[key][metric.CanonicalMetric]
		if !exists || prior.SourceAvailableAt.Before(metric.SourceAvailableAt) {
			sets[key][metric.CanonicalMetric] = metric
		}
	}
	var selected map[string]data.NormalizedMetric
	var selectedEnd time.Time
	for key, values := range sets {
		if len(values) != len(required) || (!selectedEnd.IsZero() && !key.end.After(selectedEnd)) {
			continue
		}
		selected, selectedEnd = values, key.end
	}
	if len(selected) != len(required) {
		return nil, "aligned_standardized_inputs_unavailable"
	}
	result := map[string]data.NormalizedMetric{}
	for inputID, canonical := range spec.Inputs {
		result[inputID] = selected[canonical]
	}
	return result, ""
}

func selectGrowthInputs(metrics []data.NormalizedMetric) (map[string]data.NormalizedMetric, string) {
	byPeriod := map[string]data.NormalizedMetric{}
	for _, metric := range metrics {
		if metric.CanonicalMetric != "revenue" || metric.PeriodType != "duration" ||
			!annualDuration(metric.PeriodStart, metric.PeriodEnd) {
			continue
		}
		key := periodLabel(metric)
		prior, exists := byPeriod[key]
		if !exists || prior.SourceAvailableAt.Before(metric.SourceAvailableAt) {
			byPeriod[key] = metric
		}
	}
	values := make([]data.NormalizedMetric, 0, len(byPeriod))
	for _, metric := range byPeriod {
		values = append(values, metric)
	}
	sort.Slice(values, func(i, j int) bool { return values[i].PeriodEnd.After(values[j].PeriodEnd) })
	if len(values) < 2 {
		return nil, "two_annual_standardized_revenue_periods_unavailable"
	}
	return map[string]data.NormalizedMetric{"revenue_current": values[0], "revenue_prior": values[1]}, ""
}

func operationRequest(
	runID, companyID string,
	spec operationSpec,
	selected map[string]data.NormalizedMetric,
) (contracts.EngineRequest, error) {
	operation, exists := capability.RuntimeRegistry().Get(spec.OperationID)
	if !exists {
		return contracts.EngineRequest{}, fmt.Errorf("operation %q is not registered", spec.OperationID)
	}
	inputIDs := make([]string, 0, len(selected))
	for inputID := range selected {
		inputIDs = append(inputIDs, inputID)
	}
	sort.Strings(inputIDs)
	inputs := make([]contracts.EngineInput, 0, len(inputIDs))
	periods := make([]string, 0, len(inputIDs))
	sourceAsOf := time.Time{}
	for _, inputID := range inputIDs {
		metric := selected[inputID]
		period := periodLabel(metric)
		available := metric.SourceAvailableAt
		inputs = append(inputs, contracts.EngineInput{
			InputID: inputID,
			Quantity: contracts.Quantity{
				Value: metric.Value, Unit: "currency", Currency: metric.Currency,
				Period: period, AsOf: &available,
			},
			Status: "normalized", EvidenceRefs: append([]string(nil), metric.SourceFactIDs...),
		})
		periods = append(periods, period)
		if sourceAsOf.IsZero() || available.After(sourceAsOf) {
			sourceAsOf = available
		}
	}
	sort.Strings(periods)
	periods = uniqueStrings(periods)
	return contracts.EngineRequest{
		SchemaVersion: contracts.SchemaVersionV1,
		RequestID:     "request-" + strings.TrimPrefix(companyID, "sec-cik:") + "-" + strings.ReplaceAll(spec.OperationID, ".", "-"),
		RunID:         runID, StepID: "engine-" + strings.ReplaceAll(spec.OperationID, ".", "-"),
		RequestedBy: spec.Role, EngineID: operation.Engine, OperationID: operation.ID,
		FormulaVersion: operation.FormulaVersion,
		Scope: contracts.Scope{
			CompanyIDs: []string{companyID}, Periods: periods, AsOf: sourceAsOf,
		},
		Inputs: inputs, PrecisionPolicy: operation.NumericalPolicy,
		RequestedOutputs: append([]string(nil), operation.Outputs...),
	}, nil
}

func operationAbstention(runID, companyID, operationID, reason string, at time.Time) contracts.TypedAbstention {
	digest := sha256.Sum256([]byte(runID + "\n" + operationID + "\n" + reason))
	return contracts.TypedAbstention{
		SchemaVersion: contracts.TypedAbstentionSchemaV1,
		AbstentionID:  "abstention-" + hex.EncodeToString(digest[:10]),
		RequestID:     "request-" + strings.TrimPrefix(companyID, "sec-cik:") + "-financial-activation",
		RunID:         runID, Code: reason,
		Message:    "SignalForge withheld " + operationID + " because " + strings.ReplaceAll(reason, "_", " ") + ".",
		CompanyIDs: []string{companyID}, MetricIDs: []string{operationID}, GeneratedAt: at.UTC(),
	}
}

func annualDuration(start, end time.Time) bool {
	days := int(end.Sub(start).Hours() / 24)
	return days >= 300 && days <= 380
}

func periodLabel(metric data.NormalizedMetric) string {
	return metric.PeriodStart.Format("2006-01-02") + "/" + metric.PeriodEnd.Format("2006-01-02")
}

func technologyCompany(companyID string) bool {
	for _, company := range Companies() {
		if company.CompanyID == companyID {
			return true
		}
	}
	return false
}

func periodicFactAuthority(metric data.NormalizedMetric, facts map[string]data.ReportedFact) (data.ReportedFact, bool) {
	for _, factID := range metric.SourceFactIDs {
		fact, exists := facts[factID]
		if !exists || fact.CompanyID != metric.CompanyID || fact.Unit != metric.Unit ||
			fact.Value != metric.Value || fact.AvailableAt.After(metric.SourceAvailableAt) ||
			len(fact.Dimensions) != 0 {
			continue
		}
		switch fact.FormType {
		case "10-K", "10-K/A", "10-Q", "10-Q/A":
		default:
			continue
		}
		if metric.PeriodType == "instant" && fact.InstantDate != nil &&
			fact.InstantDate.Equal(metric.PeriodEnd) {
			return fact, true
		}
		if metric.PeriodType == "duration" && fact.StartDate != nil && fact.EndDate != nil &&
			fact.StartDate.Equal(metric.PeriodStart) && fact.EndDate.Equal(metric.PeriodEnd) {
			return fact, true
		}
	}
	return data.ReportedFact{}, false
}

func uniqueStrings(values []string) []string {
	if len(values) == 0 {
		return nil
	}
	result := values[:1]
	for _, value := range values[1:] {
		if value != result[len(result)-1] {
			result = append(result, value)
		}
	}
	return result
}

func appendUniqueSorted(values []string, value string) []string {
	for _, current := range values {
		if current == value {
			return values
		}
	}
	values = append(values, value)
	sort.Strings(values)
	return values
}

func companyFinancialActivationHash(report CompanyFinancialActivation) (string, error) {
	report.ReportSHA256 = ""
	payload, err := json.Marshal(report)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(payload)
	return hex.EncodeToString(digest[:]), nil
}
