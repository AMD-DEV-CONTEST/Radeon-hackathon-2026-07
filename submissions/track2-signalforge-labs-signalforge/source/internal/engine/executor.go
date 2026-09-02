package engine

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/capability"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/numeric"
)

const Version = "0.1.0"

type Result struct {
	Receipt *contracts.CalculationReceipt `json:"receipt,omitempty"`
	Failure *contracts.FailureReceipt     `json:"failure,omitempty"`
}

type Executor struct {
	registry   capability.Registry
	codeCommit string
	now        func() time.Time
}

func New(codeCommit string) (*Executor, error) {
	return NewWithClock(codeCommit, func() time.Time { return time.Now().UTC() })
}

func NewWithClock(codeCommit string, now func() time.Time) (*Executor, error) {
	if strings.TrimSpace(codeCommit) == "" {
		return nil, errors.New("code commit is required")
	}
	if now == nil {
		return nil, errors.New("clock is required")
	}
	return &Executor{registry: capability.RuntimeRegistry(), codeCommit: codeCommit, now: now}, nil
}

func (executor *Executor) Execute(request contracts.EngineRequest) Result {
	generatedAt := executor.now()
	outputs, invariants, warnings, err := executor.calculate(request)
	if err != nil {
		return Result{Failure: failure(request, classify(err), err.Error(), generatedAt)}
	}
	inputSHA, err := hashJSON(request)
	if err != nil {
		return Result{Failure: failure(request, "internal_error", err.Error(), generatedAt)}
	}
	receiptIDSeed := request.RequestID + "\n" + generatedAt.Format(time.RFC3339Nano)
	receipt := contracts.CalculationReceipt{
		SchemaVersion: contracts.SchemaVersionV1,
		ReceiptID:     "receipt-" + shortHash([]byte(receiptIDSeed)), RequestID: request.RequestID,
		EngineID: request.EngineID, EngineVersion: Version, OperationID: request.OperationID,
		FormulaVersion: request.FormulaVersion, Status: contracts.ReceiptSuccess,
		Scope:            request.Scope,
		NormalizedInputs: cloneInputs(request.Inputs), Assumptions: append([]string(nil), request.Assumptions...),
		Outputs: outputs, InvariantResults: invariants, TolerancePolicy: request.PrecisionPolicy,
		Warnings: warnings, EvidenceRefs: evidenceRefs(request.Inputs), SourceAsOf: request.Scope.AsOf,
		CodeCommit: executor.codeCommit, InputSHA: inputSHA, GeneratedAt: generatedAt,
	}
	receiptHash, err := receiptDigest(receipt)
	if err != nil {
		return Result{Failure: failure(request, "internal_error", err.Error(), generatedAt)}
	}
	receipt.ReceiptSHA = receiptHash
	if err := contracts.ValidateCalculationReceipt(receipt); err != nil {
		return Result{Failure: failure(request, "internal_error", err.Error(), generatedAt)}
	}
	return Result{Receipt: &receipt}
}

func (executor *Executor) calculate(request contracts.EngineRequest) ([]contracts.ReceiptOutput, []contracts.InvariantResult, []string, error) {
	if err := contracts.ValidateEngineRequest(request); err != nil {
		return nil, nil, nil, fmt.Errorf("invalid_request: %w", err)
	}
	operation, ok := executor.registry.Get(request.OperationID)
	if !ok {
		return nil, nil, nil, errors.New("unauthorized_capability: operation is not registered")
	}
	if !executor.registry.Authorizes(request.RequestedBy, request.OperationID) {
		return nil, nil, nil, errors.New("unauthorized_capability: role cannot execute operation")
	}
	if request.EngineID != operation.Engine || request.FormulaVersion != operation.FormulaVersion || request.PrecisionPolicy != operation.NumericalPolicy {
		return nil, nil, nil, errors.New("invalid_request: engine, formula version, or numerical policy differs from registry")
	}
	if !operation.AssumptionsAllowed {
		if len(request.Assumptions) > 0 {
			return nil, nil, nil, errors.New("invalid_request: operation does not allow assumptions")
		}
		for _, input := range request.Inputs {
			if input.Status == "assumed" {
				return nil, nil, nil, errors.New("invalid_request: operation does not allow assumed inputs")
			}
		}
	} else {
		for _, input := range request.Inputs {
			if input.Status == "assumed" && len(request.Assumptions) == 0 {
				return nil, nil, nil, errors.New("invalid_request: assumed input requires an explicit assumption")
			}
		}
	}
	for _, requestedOutput := range request.RequestedOutputs {
		if !contains(operation.Outputs, requestedOutput) {
			return nil, nil, nil, fmt.Errorf("invalid_request: output %q is not registered", requestedOutput)
		}
	}
	inputs, err := newInputSet(request.Inputs)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("invalid_request: %w", err)
	}
	for _, required := range operation.RequiredInputs {
		if !inputs.has(required) {
			return nil, nil, nil, fmt.Errorf("invalid_request: missing required input %q", required)
		}
	}
	optionalInputs := map[string]bool{"ddof": true}
	for inputID := range inputs.byID {
		base := inputBase(inputID)
		if !contains(operation.RequiredInputs, base) && !optionalInputs[base] {
			return nil, nil, nil, fmt.Errorf("invalid_request: unexpected input %q", inputID)
		}
	}
	if err := inputs.validateMetadata(request.OperationID); err != nil {
		return nil, nil, nil, err
	}
	if err := inputs.validateUnits(request.OperationID); err != nil {
		return nil, nil, nil, err
	}
	for _, input := range request.Inputs {
		if input.Quantity.AsOf != nil && input.Quantity.AsOf.After(request.Scope.AsOf) {
			return nil, nil, nil, errors.New("invalid_request: input is not available at request as_of")
		}
	}

	outputs, invariants, warnings, err := dispatch(request.OperationID, inputs)
	if err != nil {
		if isCodedError(err) {
			return nil, nil, nil, err
		}
		return nil, nil, nil, fmt.Errorf("invalid_request: %w", err)
	}
	invariants = append([]contracts.InvariantResult{{InvariantID: "tier0_registry_match", Passed: true}}, invariants...)
	return outputs, invariants, warnings, nil
}

func isCodedError(err error) bool {
	message := err.Error()
	for _, code := range []string{"incomparable_inputs", "non_convergent", "invariant_failed"} {
		if strings.HasPrefix(message, code+":") {
			return true
		}
	}
	return false
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func inputBase(inputID string) string {
	if separator := strings.LastIndex(inputID, "."); separator >= 0 {
		if _, err := strconv.Atoi(inputID[separator+1:]); err == nil {
			return inputID[:separator]
		}
	}
	return inputID
}

func classify(err error) string {
	message := err.Error()
	for _, code := range []string{"unauthorized_capability", "unit_mismatch", "currency_mismatch", "period_mismatch", "incomparable_inputs", "non_convergent", "invariant_failed", "invalid_request"} {
		if strings.HasPrefix(message, code+":") {
			return code
		}
	}
	return "invalid_request"
}

func failure(request contracts.EngineRequest, code, message string, at time.Time) *contracts.FailureReceipt {
	seed := request.RequestID + "\n" + code + "\n" + message + "\n" + at.Format(time.RFC3339Nano)
	return &contracts.FailureReceipt{
		SchemaVersion: contracts.SchemaVersionV1, FailureID: "failure-" + shortHash([]byte(seed)),
		RunID: request.RunID, StepID: request.StepID, ComponentID: "deterministic-engine/" + Version,
		FailureCode: code, Message: message, Retryable: false, EvidenceRefs: evidenceRefs(request.Inputs), CreatedAt: at,
	}
}

func cloneInputs(inputs []contracts.EngineInput) []contracts.EngineInput {
	result := append([]contracts.EngineInput(nil), inputs...)
	for index := range result {
		result[index].EvidenceRefs = append([]string(nil), result[index].EvidenceRefs...)
	}
	return result
}

func evidenceRefs(inputs []contracts.EngineInput) []string {
	set := make(map[string]struct{})
	for _, input := range inputs {
		for _, reference := range input.EvidenceRefs {
			set[reference] = struct{}{}
		}
	}
	result := make([]string, 0, len(set))
	for reference := range set {
		result = append(result, reference)
	}
	sort.Strings(result)
	return result
}

func hashJSON(value any) (string, error) {
	encoded, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(encoded)
	return hex.EncodeToString(digest[:]), nil
}

func shortHash(value []byte) string {
	digest := sha256.Sum256(value)
	return hex.EncodeToString(digest[:10])
}

func receiptDigest(receipt contracts.CalculationReceipt) (string, error) {
	receipt.ReceiptSHA = ""
	return hashJSON(receipt)
}

type inputSet struct {
	byID map[string]contracts.EngineInput
}

func newInputSet(inputs []contracts.EngineInput) (inputSet, error) {
	result := inputSet{byID: make(map[string]contracts.EngineInput, len(inputs))}
	for _, input := range inputs {
		if _, exists := result.byID[input.InputID]; exists {
			return inputSet{}, fmt.Errorf("duplicate input %q", input.InputID)
		}
		if _, err := numeric.ParseDecimal(input.Quantity.Value); err != nil {
			return inputSet{}, fmt.Errorf("input %q is not canonical decimal data: %w", input.InputID, err)
		}
		result.byID[input.InputID] = input
	}
	return result, nil
}

func (inputs inputSet) has(name string) bool {
	if _, ok := inputs.byID[name]; ok {
		return true
	}
	prefix := name + "."
	for inputID := range inputs.byID {
		if strings.HasPrefix(inputID, prefix) {
			return true
		}
	}
	return false
}

func (inputs inputSet) input(name string) (contracts.EngineInput, error) {
	input, ok := inputs.byID[name]
	if !ok {
		return contracts.EngineInput{}, fmt.Errorf("missing input %q", name)
	}
	return input, nil
}

func (inputs inputSet) decimal(name string) (numeric.Decimal, error) {
	input, err := inputs.input(name)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return numeric.ParseDecimal(input.Quantity.Value)
}

func (inputs inputSet) float(name string) (float64, error) {
	input, err := inputs.input(name)
	if err != nil {
		return 0, err
	}
	value, err := strconv.ParseFloat(input.Quantity.Value, 64)
	if err != nil {
		return 0, fmt.Errorf("parse %q as float64: %w", name, err)
	}
	return value, nil
}

func (inputs inputSet) integer(name string) (int, error) {
	input, err := inputs.input(name)
	if err != nil {
		return 0, err
	}
	value, err := strconv.Atoi(input.Quantity.Value)
	if err != nil {
		return 0, fmt.Errorf("parse %q as integer: %w", name, err)
	}
	return value, nil
}

func (inputs inputSet) series(name string) ([]contracts.EngineInput, error) {
	type indexed struct {
		index int
		input contracts.EngineInput
	}
	values := make([]indexed, 0)
	prefix := name + "."
	for inputID, input := range inputs.byID {
		if !strings.HasPrefix(inputID, prefix) {
			continue
		}
		index, err := strconv.Atoi(strings.TrimPrefix(inputID, prefix))
		if err != nil || index < 0 {
			return nil, fmt.Errorf("series %q has invalid index %q", name, inputID)
		}
		values = append(values, indexed{index: index, input: input})
	}
	if len(values) == 0 {
		return nil, fmt.Errorf("series %q is empty", name)
	}
	sort.Slice(values, func(left, right int) bool { return values[left].index < values[right].index })
	result := make([]contracts.EngineInput, len(values))
	for expected, value := range values {
		if value.index != expected {
			return nil, fmt.Errorf("series %q must use contiguous zero-based indices", name)
		}
		result[expected] = value.input
	}
	return result, nil
}

func (inputs inputSet) decimalSeries(name string) ([]numeric.Decimal, error) {
	series, err := inputs.series(name)
	if err != nil {
		return nil, err
	}
	result := make([]numeric.Decimal, len(series))
	for index, input := range series {
		result[index], err = numeric.ParseDecimal(input.Quantity.Value)
		if err != nil {
			return nil, err
		}
	}
	return result, nil
}

func (inputs inputSet) floatSeries(name string) ([]float64, error) {
	series, err := inputs.series(name)
	if err != nil {
		return nil, err
	}
	result := make([]float64, len(series))
	for index, input := range series {
		result[index], err = strconv.ParseFloat(input.Quantity.Value, 64)
		if err != nil {
			return nil, err
		}
	}
	return result, nil
}

func (inputs inputSet) validateMetadata(operationID string) error {
	monetaryCurrency := ""
	for _, input := range inputs.byID {
		quantity := input.Quantity
		if quantity.Unit == "currency" || quantity.Unit == "currency_per_share" {
			if len(quantity.Currency) != 3 {
				return errors.New("currency_mismatch: monetary input requires a three-letter currency")
			}
			if monetaryCurrency == "" {
				monetaryCurrency = quantity.Currency
			} else if monetaryCurrency != quantity.Currency {
				return errors.New("currency_mismatch: monetary inputs use different currencies")
			}
		} else if quantity.Currency != "" {
			return errors.New("currency_mismatch: non-monetary input declares a currency")
		}
	}
	periodAligned := map[string]bool{
		"accounting.balance_sheet_identity": true, "financial.margin": true,
		"financial.free_cash_flow": true, "financial.cash_conversion": true,
		"financial.capex_intensity": true, "financial.roic_proxy": true,
		"financial.net_debt": true, "financial.current_ratio": true, "financial.debt_to_equity": true,
		"financial.earnings_per_share": true, "financial.quality_of_earnings": true,
		"financial.invested_capital":          true,
		"financial.operating_working_capital": true, "financial.net_capex": true,
		"financial.reinvestment": true, "financial.fcff_from_nopat": true,
		"financial.fcfe": true, "financial.operating_margin": true,
		"financial.accrual_intensity": true, "financial.cash_conversion_cycle": true,
		"financial.quick_ratio": true, "financial.cash_ratio": true,
		"financial.cash_conversion_ebitda": true, "financial.cash_conversion_operating_profit": true,
		"financial.reinvestment_rate": true, "financial.interest_coverage": true,
		"financial.capital_allocation_bridge":     true,
		"valuation.enterprise_to_equity_detailed": true, "valuation.price_to_book": true,
	}
	if !periodAligned[operationID] {
		return nil
	}
	period := ""
	for _, input := range inputs.byID {
		if input.Quantity.Period == "" {
			return errors.New("period_mismatch: aligned operation requires an input period")
		}
		if period == "" {
			period = input.Quantity.Period
		} else if period != input.Quantity.Period {
			return errors.New("period_mismatch: aligned operation received different periods")
		}
	}
	return nil
}

type unitRule map[string][]string

func governedUnitRules() map[string]unitRule {
	return map[string]unitRule{
		"accounting.balance_sheet_identity":   {"assets": {"currency"}, "liabilities": {"currency"}, "equity": {"currency"}},
		"financial.revenue_growth":            {"revenue_current": {"currency"}, "revenue_prior": {"currency"}},
		"financial.cagr":                      {"value_start": {"currency", "count", "index_point"}, "value_end": {"currency", "count", "index_point"}, "years": {"years"}},
		"financial.margin":                    {"numerator": {"currency"}, "revenue": {"currency"}},
		"financial.free_cash_flow":            {"operating_cash_flow": {"currency"}, "capital_expenditure": {"currency"}},
		"financial.cash_conversion":           {"operating_cash_flow": {"currency"}, "net_income": {"currency"}},
		"financial.capex_intensity":           {"capital_expenditure": {"currency"}, "revenue": {"currency"}},
		"financial.net_debt":                  {"debt": {"currency"}, "cash_and_equivalents": {"currency"}},
		"financial.dilution":                  {"shares_current": {"shares"}, "shares_prior": {"shares"}},
		"financial.roic_proxy":                {"nopat": {"currency"}, "invested_capital": {"currency"}},
		"financial.current_ratio":             {"current_assets": {"currency"}, "current_liabilities": {"currency"}},
		"financial.debt_to_equity":            {"debt": {"currency"}, "equity": {"currency"}},
		"financial.earnings_per_share":        {"net_income": {"currency"}, "diluted_shares": {"shares"}},
		"financial.quality_of_earnings":       {"operating_cash_flow": {"currency"}, "net_income": {"currency"}},
		"valuation.fcff_dcf":                  {"fcff_forecast": {"currency"}, "discount_rate": {"ratio"}, "terminal_growth": {"ratio"}},
		"valuation.reverse_dcf":               {"enterprise_value": {"currency"}, "base_fcff": {"currency"}, "discount_rate": {"ratio"}, "years": {"years"}},
		"valuation.enterprise_to_equity":      {"enterprise_value": {"currency"}, "net_debt": {"currency"}, "non_operating_assets": {"currency"}, "diluted_shares": {"shares"}},
		"valuation.peer_multiple":             {"market_value": {"currency", "currency_per_share"}, "metric_value": {"currency", "currency_per_share"}},
		"valuation.wacc":                      {"equity_value": {"currency"}, "debt_value": {"currency"}, "cost_of_equity": {"ratio"}, "pre_tax_cost_of_debt": {"ratio"}, "tax_rate": {"ratio"}},
		"economics.real_rate":                 {"nominal_rate": {"ratio"}, "inflation_measure": {"ratio"}},
		"economics.yield_curve":               {"long_yield": {"ratio"}, "short_yield": {"ratio"}},
		"market.total_return":                 {"start_price": {"currency"}, "end_price": {"currency"}, "distributions": {"currency"}},
		"market.volatility":                   {"returns": {"ratio"}, "periods_per_year": {"count"}, "ddof": {"count"}},
		"market.drawdown":                     {"wealth_index": {"index_point"}},
		"market.beta":                         {"security_returns": {"ratio"}, "benchmark_returns": {"ratio"}, "ddof": {"count"}},
		"market.rolling_correlation":          {"series_x": {"ratio", "index_point"}, "series_y": {"ratio", "index_point"}, "window": {"count"}},
		"comparison.period_aligned":           {"company_metrics": {"currency"}},
		"scenario.sensitivity_matrix":         {"fcff_forecast": {"currency"}, "discount_rates": {"ratio"}, "terminal_growth_rates": {"ratio"}},
		"financial.nopat":                     {"operating_income": {"currency"}, "tax_rate": {"ratio"}},
		"financial.invested_capital":          {"operating_assets": {"currency"}, "non_interest_bearing_operating_liabilities": {"currency"}, "debt": {"currency"}, "equity": {"currency"}, "cash_and_equivalents": {"currency"}, "non_operating_assets": {"currency"}},
		"financial.average_invested_capital":  {"invested_capital_beginning": {"currency"}, "invested_capital_ending": {"currency"}},
		"financial.operating_working_capital": {"accounts_receivable": {"currency"}, "inventory": {"currency"}, "other_operating_current_assets": {"currency"}, "accounts_payable": {"currency"}, "other_operating_current_liabilities": {"currency"}},
		"financial.change_in_working_capital": {"operating_working_capital_ending": {"currency"}, "operating_working_capital_beginning": {"currency"}},
		"financial.net_capex":                 {"capital_expenditure": {"currency"}, "depreciation_and_amortization": {"currency"}},
		"financial.reinvestment":              {"net_capex": {"currency"}, "change_in_working_capital": {"currency"}, "acquisitions": {"currency"}},
		"financial.fcff_from_nopat":           {"nopat": {"currency"}, "reinvestment": {"currency"}},
		"financial.fcfe":                      {"net_income": {"currency"}, "capital_expenditure": {"currency"}, "depreciation_and_amortization": {"currency"}, "change_in_working_capital": {"currency"}, "net_borrowing": {"currency"}},
		"financial.roic":                      {"nopat": {"currency"}, "average_invested_capital": {"currency"}},
		"financial.incremental_roic":          {"change_in_nopat": {"currency"}, "change_in_invested_capital": {"currency"}},
		"financial.roce":                      {"ebit": {"currency"}, "total_assets": {"currency"}, "current_liabilities": {"currency"}},
		"financial.value_creation_spread":     {"roic": {"ratio"}, "wacc": {"ratio"}},
		"financial.reinvestment_rate":         {"reinvestment": {"currency"}, "nopat": {"currency"}},
		"financial.fundamental_growth":        {"return_on_capital": {"ratio"}, "reinvestment_rate": {"ratio"}},
		"financial.operating_margin":          {"operating_income": {"currency"}, "revenue": {"currency"}},
		"financial.incremental_margin":        {"operating_income_current": {"currency"}, "operating_income_prior": {"currency"}, "revenue_current": {"currency"}, "revenue_prior": {"currency"}},
		"financial.accrual_intensity":         {"net_income": {"currency"}, "operating_cash_flow": {"currency"}, "average_assets": {"currency"}},
		"financial.cash_conversion_cycle":     {"days_sales_outstanding": {"days"}, "days_inventory_outstanding": {"days"}, "days_payables_outstanding": {"days"}},
		"financial.quick_ratio":               {"cash_and_equivalents": {"currency"}, "marketable_securities": {"currency"}, "accounts_receivable": {"currency"}, "current_liabilities": {"currency"}},
		"financial.cash_ratio":                {"cash_and_equivalents": {"currency"}, "marketable_securities": {"currency"}, "current_liabilities": {"currency"}},
		"financial.interest_coverage":         {"ebit": {"currency"}, "interest_expense": {"currency"}},
		"financial.net_debt_to_ebitda":        {"net_debt": {"currency"}, "ebitda": {"currency"}},
		"financial.cash_conversion_ebitda":    {"operating_cash_flow": {"currency"}, "ebitda": {"currency"}},
		"financial.cash_conversion_operating_profit": {
			"operating_cash_flow": {"currency"}, "operating_profit": {"currency"},
		},
		"financial.buyback_yield":             {"net_repurchases": {"currency"}, "market_capitalization": {"currency"}},
		"financial.dividend_yield":            {"dividends_paid": {"currency"}, "market_capitalization": {"currency"}},
		"financial.net_payout_yield":          {"net_repurchases": {"currency"}, "dividends_paid": {"currency"}, "market_capitalization": {"currency"}},
		"financial.shareholder_yield":         {"net_repurchases": {"currency"}, "dividends_paid": {"currency"}, "net_debt_reduction": {"currency"}, "market_capitalization": {"currency"}},
		"financial.capital_allocation_bridge": {"operating_cash_flow": {"currency"}, "debt_issuance": {"currency"}, "equity_issuance": {"currency"}, "asset_sales": {"currency"}, "capital_expenditure": {"currency"}, "acquisitions": {"currency"}, "debt_repayment": {"currency"}, "dividends": {"currency"}, "repurchases": {"currency"}, "reported_change_in_cash": {"currency"}, "tolerance": {"currency"}},
		"valuation.capm":                      {"risk_free_rate": {"ratio"}, "beta": {"ratio"}, "equity_risk_premium": {"ratio"}},
		"valuation.unlever_beta":              {"levered_beta": {"ratio"}, "debt": {"currency"}, "equity": {"currency"}, "tax_rate": {"ratio"}},
		"valuation.relever_beta":              {"unlevered_beta": {"ratio"}, "debt": {"currency"}, "equity": {"currency"}, "tax_rate": {"ratio"}},
		"valuation.multistage_dcf_perpetuity": {"fcff_forecast": {"currency"}, "discount_rate": {"ratio"}, "terminal_growth": {"ratio"}, "mid_year": {"boolean"}},
		"valuation.multistage_dcf_exit":       {"fcff_forecast": {"currency"}, "discount_rate": {"ratio"}, "exit_metric": {"currency"}, "exit_multiple": {"ratio"}, "mid_year": {"boolean"}},
		"valuation.dividend_discount":         {"dividend_forecast": {"currency"}, "cost_of_equity": {"ratio"}, "terminal_growth": {"ratio"}, "mid_year": {"boolean"}},
		"valuation.reverse_revenue_growth":    {"enterprise_value": {"currency"}, "base_revenue": {"currency"}, "operating_margin": {"ratio"}, "tax_rate": {"ratio"}, "reinvestment_rate": {"ratio"}, "discount_rate": {"ratio"}, "terminal_growth": {"ratio"}, "years": {"years"}},
		"valuation.reverse_operating_margin":  {"enterprise_value": {"currency"}, "base_revenue": {"currency"}, "revenue_growth": {"ratio"}, "tax_rate": {"ratio"}, "reinvestment_rate": {"ratio"}, "discount_rate": {"ratio"}, "terminal_growth": {"ratio"}, "years": {"years"}},
		"valuation.reverse_reinvestment_rate": {"enterprise_value": {"currency"}, "base_revenue": {"currency"}, "revenue_growth": {"ratio"}, "operating_margin": {"ratio"}, "tax_rate": {"ratio"}, "discount_rate": {"ratio"}, "terminal_growth": {"ratio"}, "years": {"years"}},
		"valuation.implied_roic":              {"growth_rate": {"ratio"}, "reinvestment_rate": {"ratio"}},
		"valuation.enterprise_to_equity_detailed": {
			"enterprise_value": {"currency"}, "debt": {"currency"}, "cash": {"currency"},
			"investments": {"currency"}, "minority_interest": {"currency"}, "option_value": {"currency"},
			"diluted_shares": {"shares"},
		},
		"valuation.ev_to_ebitda":       {"enterprise_value": {"currency"}, "ebitda": {"currency"}},
		"valuation.ev_to_revenue":      {"enterprise_value": {"currency"}, "revenue": {"currency"}},
		"valuation.ev_to_ebit":         {"enterprise_value": {"currency"}, "ebit": {"currency"}},
		"valuation.price_to_earnings":  {"equity_market_value": {"currency"}, "net_income": {"currency"}},
		"valuation.price_to_book":      {"equity_market_value": {"currency"}, "book_equity": {"currency"}},
		"valuation.price_to_fcf":       {"equity_market_value": {"currency"}, "free_cash_flow_to_equity": {"currency"}},
		"valuation.fcf_yield":          {"free_cash_flow_to_equity": {"currency"}, "equity_market_value": {"currency"}},
		"valuation.earnings_yield":     {"net_income": {"currency"}, "equity_market_value": {"currency"}},
		"comparison.dupont":            {"net_income": {"currency"}, "revenue": {"currency"}, "average_assets": {"currency"}, "average_equity": {"currency"}},
		"comparison.peer_statistics":   {"peer_values": {"ratio"}, "subject_value": {"ratio"}, "minimum_sample": {"count"}},
		"economics.lagged_association": {"driver_series": {"ratio", "index_point"}, "outcome_series": {"ratio", "index_point"}, "lag": {"count"}, "minimum_sample": {"count"}},
	}
}

func (inputs inputSet) validateUnits(operationID string) error {
	operationRules, ok := governedUnitRules()[operationID]
	if !ok {
		return nil
	}
	for inputID, input := range inputs.byID {
		base := inputBase(inputID)
		allowed, exists := operationRules[base]
		if !exists {
			continue
		}
		if !contains(allowed, input.Quantity.Unit) {
			return fmt.Errorf("unit_mismatch: input %q requires one of %v, got %q", inputID, allowed, input.Quantity.Unit)
		}
	}
	return nil
}

func decimalOutput(id string, value numeric.Decimal, unit, currency string) contracts.ReceiptOutput {
	return contracts.ReceiptOutput{OutputID: id, Quantity: contracts.Quantity{Value: value.String(), Unit: unit, Currency: currency}, Status: "derived"}
}

func floatOutput(id string, value float64, unit string) contracts.ReceiptOutput {
	return contracts.ReceiptOutput{OutputID: id, Quantity: contracts.Quantity{Value: strconv.FormatFloat(value, 'g', 17, 64), Unit: unit}, Status: "derived"}
}

func intOutput(id string, value int, unit string) contracts.ReceiptOutput {
	return contracts.ReceiptOutput{OutputID: id, Quantity: contracts.Quantity{Value: strconv.Itoa(value), Unit: unit}, Status: "derived"}
}

func boolOutput(id string, value bool) contracts.ReceiptOutput {
	encoded := "0"
	if value {
		encoded = "1"
	}
	return contracts.ReceiptOutput{OutputID: id, Quantity: contracts.Quantity{Value: encoded, Unit: "boolean"}, Status: "derived"}
}

func firstCurrency(inputs inputSet) string {
	ids := make([]string, 0, len(inputs.byID))
	for id := range inputs.byID {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		if inputs.byID[id].Quantity.Currency != "" {
			return inputs.byID[id].Quantity.Currency
		}
	}
	return ""
}
