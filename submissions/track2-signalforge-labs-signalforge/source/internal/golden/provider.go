package golden

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/cockroachdb/apd/v3"
	"github.com/rvbernucci/signalforge/internal/capability"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/engine"
	"github.com/rvbernucci/signalforge/internal/localagent"
	"github.com/rvbernucci/signalforge/internal/numeric"
	"github.com/rvbernucci/signalforge/internal/numericalcontext"
	"github.com/rvbernucci/signalforge/internal/retrieval"
	"github.com/rvbernucci/signalforge/internal/roles"
)

type PriceInput struct {
	Ticker    string    `json:"ticker"`
	Value     string    `json:"value"`
	Currency  string    `json:"currency"`
	AsOf      time.Time `json:"as_of"`
	Source    string    `json:"source"`
	SourceSHA string    `json:"source_sha256,omitempty"`
}

type Provider struct {
	snapshot Snapshot
	index    *retrieval.LexicalIndex
	executor *engine.Executor
	registry capability.Registry
	prices   map[string]PriceInput
}

func NewProvider(snapshot Snapshot, chunks []retrieval.Chunk, codeCommit string, prices []PriceInput) (*Provider, error) {
	if err := ValidateSnapshot(snapshot); err != nil {
		return nil, err
	}
	index, err := retrieval.NewLexicalIndex(chunks)
	if err != nil {
		return nil, err
	}
	executor, err := engine.NewWithClock(codeCommit, func() time.Time { return snapshot.AsOf })
	if err != nil {
		return nil, err
	}
	provider := &Provider{
		snapshot: snapshot, index: index, executor: executor,
		registry: capability.Tier0Registry(), prices: make(map[string]PriceInput, len(prices)),
	}
	for _, price := range prices {
		price.Ticker = strings.ToUpper(strings.TrimSpace(price.Ticker))
		price.Currency = strings.ToUpper(strings.TrimSpace(price.Currency))
		if price.Ticker == "" || len(price.Currency) != 3 || price.AsOf.IsZero() || price.AsOf.After(snapshot.AsOf) || strings.TrimSpace(price.Source) == "" {
			return nil, fmt.Errorf("invalid runtime price input for %q", price.Ticker)
		}
		if price.SourceSHA != "" && !shaPattern.MatchString(price.SourceSHA) {
			return nil, fmt.Errorf("runtime price for %q has invalid source_sha256", price.Ticker)
		}
		value, err := numeric.ParseDecimal(price.Value)
		if err != nil || strings.HasPrefix(value.String(), "-") || value.String() == "0" {
			return nil, fmt.Errorf("runtime price for %q must be a positive decimal", price.Ticker)
		}
		price.Value = value.String()
		if provider.prices[price.Ticker].Ticker != "" {
			return nil, fmt.Errorf("duplicate runtime price for %q", price.Ticker)
		}
		provider.prices[price.Ticker] = price
	}
	return provider, nil
}

func (provider *Provider) Load(ctx context.Context, request contracts.ContextRequest) (localagent.Material, error) {
	select {
	case <-ctx.Done():
		return localagent.Material{}, ctx.Err()
	default:
	}
	companies, err := provider.companies(request.Scope.CompanyIDs)
	if err != nil {
		return localagent.Material{}, err
	}
	items, err := provider.qualitativeEvidence(request, companies)
	if err != nil {
		return localagent.Material{}, err
	}
	items = append(items, provider.metricEvidence(request.SpecialistRole, companies)...)
	items = append(items, provider.priceEvidence(request.SpecialistRole, companies)...)
	missing := []string{}
	if request.SpecialistRole == roles.AccountingReporting || request.SpecialistRole == roles.FinancialQuality || request.SpecialistRole == roles.Valuation {
		items = append(items, fiscalPeriodBoundary(request.Scope.AsOf, companies))
		missing = append(missing, "Microsoft FY2025 ended 2025-06-30 while NVIDIA FY2025 ended 2025-01-26; nominal fiscal-year comparisons are not concurrent calendar-period comparisons.")
	}
	if request.SpecialistRole == roles.Valuation || request.SpecialistRole == roles.MarketBehavior {
		for _, company := range companies {
			if _, ok := provider.prices[company.Ticker]; !ok {
				missing = append(missing, fmt.Sprintf("A point-in-time runtime market price for %s was not supplied, so price-implied multiples are unavailable.", company.Ticker))
			}
		}
	}
	if request.SpecialistRole == roles.EconomicsTransmission && contains(request.CapabilityIDs, "economics.yield_curve") {
		missing = append(missing, "No authoritative point-in-time yield-curve observation was supplied; higher-for-longer rates remain an explicit scenario rather than an observed causal estimate.")
	}
	receipts, err := provider.calculationReceipts(request, companies)
	if err != nil {
		return localagent.Material{}, err
	}
	bundle := contracts.EvidenceBundle{
		SchemaVersion: contracts.SchemaVersionV1,
		BundleID:      "bundle-" + request.ContextRequestID,
		RunID:         request.RunID,
		StepID:        request.StepID,
		AsOf:          request.Scope.AsOf,
		Items:         uniqueEvidence(items),
		Missing:       uniqueStrings(missing),
	}
	if err := contracts.ValidateEvidenceBundle(bundle); err != nil {
		return localagent.Material{}, err
	}
	material := localagent.Material{Evidence: bundle, CalculationReceipts: receipts}
	if numericalcontext.HasEligibleOutputs(receipts) {
		entityNames := make(map[string]string, len(companies))
		fiscalPeriods := make(map[string]numericalcontext.FiscalPeriod, len(companies))
		for _, company := range companies {
			entityNames[company.CompanyID] = company.Ticker
			fiscalPeriods[company.CompanyID] = numericalcontext.FiscalPeriod{Start: company.PeriodStart, End: company.PeriodEnd}
		}
		numerical, err := numericalcontext.Compile(numericalcontext.Options{
			ContextID: "numerical-" + request.ContextRequestID, RunID: request.RunID,
			AsOf: request.Scope.AsOf, EntityNames: entityNames, EntityFiscalPeriods: fiscalPeriods,
		}, receipts)
		if err != nil {
			return localagent.Material{}, fmt.Errorf("compile numerical context: %w", err)
		}
		material.NumericalContext = &numerical
	}
	return material, nil
}

func (provider *Provider) companies(ids []string) ([]Company, error) {
	if len(ids) == 0 {
		return nil, errors.New("golden material requires explicit company scope")
	}
	result := make([]Company, 0, len(ids))
	for _, id := range ids {
		company, ok := provider.snapshot.Company(id)
		if !ok {
			return nil, fmt.Errorf("company %q is outside the frozen golden snapshot", id)
		}
		result = append(result, company)
	}
	return result, nil
}

func (provider *Provider) qualitativeEvidence(request contracts.ContextRequest, companies []Company) ([]contracts.EvidenceItem, error) {
	profile := map[string]string{
		roles.BusinessStrategy:      "business model products customers segments revenue mechanisms demand competition history risk factors",
		roles.AccountingReporting:   "accounting comparability reporting classification margin capital expenditure commitments inventory disclosure",
		roles.FinancialQuality:      "revenue growth operating margin cash flow capital expenditure reinvestment customer concentration",
		roles.EconomicsTransmission: "interest rates currency demand infrastructure spending export controls supply chain transmission",
		roles.Valuation:             "cash flow growth margin capital expenditure commitments demand risk valuation assumptions",
		roles.MarketBehavior:        "market price demand management framing interest-rate risk export controls concentration",
	}[request.SpecialistRole]
	if profile == "" {
		return nil, fmt.Errorf("role %q has no golden retrieval profile", request.SpecialistRole)
	}
	seen := map[string]bool{}
	items := []contracts.EvidenceItem{}
	topK := 6
	if request.SpecialistRole == roles.FinancialQuality || request.SpecialistRole == roles.Valuation {
		topK = 4
	}
	for _, company := range companies {
		hits, err := provider.index.Search(retrieval.Query{
			Text: request.ResearchQuestion + " " + profile, AsOf: request.Scope.AsOf,
			CompanyIDs: []string{company.CompanyID}, AuthorityTiers: []string{"A", "B", "C", "D"}, TopK: topK,
		})
		if err != nil {
			return nil, err
		}
		for _, hit := range hits {
			if seen[hit.Chunk.ChunkID] {
				continue
			}
			seen[hit.Chunk.ChunkID] = true
			warnings := []string{"authority_tier=" + hit.Chunk.AuthorityTier}
			if hit.Chunk.ForwardLooking {
				warnings = append(warnings, "forward_looking")
			}
			if hit.Chunk.Promotional {
				warnings = append(warnings, "issuer_promotional_material")
			}
			items = append(items, contracts.EvidenceItem{
				EvidenceRef: contracts.EvidenceRef{
					EvidenceID: hit.Chunk.ChunkID, SourceType: hit.Chunk.EvidenceType,
					DocumentSection: hit.Chunk.Section,
					Locator:         hit.Chunk.SourceURI + "#" + hit.Chunk.Locator,
					ContentSHA:      hit.Chunk.ContentSHA256, AsOf: hit.Chunk.AvailableAt,
				},
				State: contracts.EvidenceAvailable, Statement: hit.Chunk.Text, Warnings: warnings,
			})
		}
	}
	if len(items) == 0 {
		return nil, errors.New("golden retrieval returned no authoritative qualitative evidence")
	}
	return items, nil
}

func (provider *Provider) metricEvidence(roleID string, companies []Company) []contracts.EvidenceItem {
	wanted := map[string]bool{}
	switch roleID {
	case roles.BusinessStrategy:
		wanted["revenue"], wanted["revenue_prior"] = true, true
	case roles.FinancialQuality, roles.Valuation:
		// Their deterministic receipt views already carry normalized inputs, outputs, evidence
		// references, and hashes. Repeating every raw metric here bloats local-model context without
		// adding authority or reproducibility.
		return nil
	case roles.EconomicsTransmission:
		wanted["revenue"], wanted["capital_expenditure"] = true, true
	case roles.MarketBehavior:
		wanted["diluted_eps"] = true
	default:
		for _, metricID := range []string{"revenue", "revenue_prior", "operating_income", "net_income", "operating_cash_flow", "capital_expenditure", "diluted_eps", "diluted_shares"} {
			wanted[metricID] = true
		}
	}
	items := []contracts.EvidenceItem{}
	for _, company := range companies {
		for _, metric := range company.Metrics {
			if !wanted[metric.MetricID] {
				continue
			}
			period := metric.Period
			if period == "" {
				period = company.FiscalPeriod
			}
			statement := fmt.Sprintf("%s %s %s was %s %s", company.LegalName, period, strings.ReplaceAll(metric.MetricID, "_", " "), metric.Value, displayUnit(metric))
			warnings := []string{"comparability=" + metric.ComparabilityStatus, "normalization=" + provider.snapshot.NormalizationPolicy}
			items = append(items, contracts.EvidenceItem{
				EvidenceRef: contracts.EvidenceRef{
					EvidenceID: metric.EvidenceID, SourceType: "sec_xbrl_companyfacts",
					Locator:    companyFactsURI(company.CompanyID) + "#" + metric.SourceFactID,
					ContentSHA: hashText(statement), AsOf: metric.SourceAvailableAt,
				},
				State: contracts.EvidenceAvailable, Statement: statement, Warnings: warnings,
			})
		}
	}
	return items
}

func (provider *Provider) priceEvidence(roleID string, companies []Company) []contracts.EvidenceItem {
	if roleID != roles.Valuation && roleID != roles.MarketBehavior {
		return nil
	}
	items := []contracts.EvidenceItem{}
	for _, company := range companies {
		price, ok := provider.prices[company.Ticker]
		if !ok {
			continue
		}
		statement := fmt.Sprintf("Point-in-time %s official close was %s %s per share as of %s", company.Ticker, price.Value, price.Currency, price.AsOf.Format(time.RFC3339))
		contentSHA := price.SourceSHA
		warnings := []string{"runtime_input_not_embedded_market_data"}
		if contentSHA == "" {
			contentSHA = hashText(statement)
			warnings = append(warnings, "source_response_hash_unavailable")
		}
		items = append(items, contracts.EvidenceItem{
			EvidenceRef: contracts.EvidenceRef{EvidenceID: priceEvidenceID(company.Ticker), SourceType: "official_exchange_close", Locator: price.Source, ContentSHA: contentSHA, AsOf: price.AsOf},
			State:       contracts.EvidenceAvailable, Statement: statement, Warnings: warnings,
		})
	}
	return items
}

func (provider *Provider) calculationReceipts(request contracts.ContextRequest, companies []Company) ([]contracts.CalculationReceipt, error) {
	allowed := stringSet(request.CapabilityIDs)
	operations := []string{}
	switch request.SpecialistRole {
	case roles.FinancialQuality:
		operations = []string{"financial.revenue_growth", "financial.margin", "financial.free_cash_flow", "financial.cash_conversion", "financial.capex_intensity"}
	case roles.Valuation:
		operations = []string{"financial.free_cash_flow"}
	default:
		return nil, nil
	}
	receipts := []contracts.CalculationReceipt{}
	baseFCF := map[string]string{}
	for _, company := range companies {
		for _, operationID := range operations {
			if !allowed[operationID] {
				continue
			}
			inputs, err := companyInputs(company, operationID)
			if err != nil {
				return nil, err
			}
			receipt, err := provider.execute(request, company, operationID, company.Ticker, inputs, nil)
			if err != nil {
				return nil, err
			}
			receipts = append(receipts, receipt)
			if operationID == "financial.free_cash_flow" {
				baseFCF[company.CompanyID] = receipt.Outputs[0].Quantity.Value
			}
		}
	}
	if request.SpecialistRole != roles.Valuation {
		return receipts, nil
	}
	for _, company := range companies {
		base := baseFCF[company.CompanyID]
		if base == "" {
			base = subtractMetric(company, "operating_cash_flow", "capital_expenditure")
		}
		if allowed["valuation.fcff_dcf"] {
			scenario := scenarioByName(company, "base")
			forecast, err := compoundForecast(base, scenario.AnnualFCFGrowth, 5)
			if err != nil {
				return nil, err
			}
			assumption := scenarioAssumption(company, scenario, base)
			inputs := forecastInputs(company, forecast, scenario.DiscountRate, scenario.TerminalGrowth)
			receipt, err := provider.execute(request, company, "valuation.fcff_dcf", company.Ticker+"-"+scenario.Name, inputs, []string{assumption})
			if err != nil {
				return nil, err
			}
			receipts = append(receipts, receipt)
		}
		if allowed["scenario.sensitivity_matrix"] {
			baseScenario := scenarioByName(company, "base")
			forecast, err := compoundForecast(base, baseScenario.AnnualFCFGrowth, 5)
			if err != nil {
				return nil, err
			}
			inputs := sensitivityInputs(company, forecast)
			assumption := "Illustrative sensitivity grid using the disclosed bear, base, and bull discount-rate and terminal-growth axes; it is not a price forecast or investment recommendation."
			receipt, err := provider.execute(request, company, "scenario.sensitivity_matrix", company.Ticker+"-grid", inputs, []string{assumption})
			if err != nil {
				return nil, err
			}
			receipts = append(receipts, receipt)
		}
		if allowed["valuation.peer_multiple"] {
			price, priceOK := provider.prices[company.Ticker]
			eps, epsOK := company.Metric("diluted_eps")
			if priceOK && epsOK {
				inputs := []contracts.EngineInput{
					input("market_value", price.Value, "currency_per_share", price.Currency, price.AsOf.Format("2006-01-02"), "reported", []string{priceEvidenceID(company.Ticker)}, &price.AsOf),
					metricInput("metric_value", eps, company.FiscalPeriod),
				}
				receipt, err := provider.execute(request, company, "valuation.peer_multiple", company.Ticker+"-pe", inputs, nil)
				if err != nil {
					return nil, err
				}
				receipts = append(receipts, receipt)
			}
		}
	}
	return receipts, nil
}

func (provider *Provider) execute(request contracts.ContextRequest, company Company, operationID, suffix string, inputs []contracts.EngineInput, assumptions []string) (contracts.CalculationReceipt, error) {
	operation, ok := provider.registry.Get(operationID)
	if !ok || !provider.registry.Authorizes(request.SpecialistRole, operationID) {
		return contracts.CalculationReceipt{}, fmt.Errorf("operation %q is not authorized for %q", operationID, request.SpecialistRole)
	}
	engineRequest := contracts.EngineRequest{
		SchemaVersion: contracts.SchemaVersionV1,
		RequestID:     "calc-" + request.ContextRequestID + "-" + strings.ToLower(strings.ReplaceAll(suffix, "_", "-")) + "-" + strings.ReplaceAll(operationID, ".", "-"),
		RunID:         request.RunID, StepID: request.StepID, RequestedBy: request.SpecialistRole,
		EngineID: operation.Engine, OperationID: operation.ID, FormulaVersion: operation.FormulaVersion,
		Scope:  contracts.Scope{CompanyIDs: []string{company.CompanyID}, AsOf: request.Scope.AsOf},
		Inputs: inputs, Assumptions: assumptions, PrecisionPolicy: operation.NumericalPolicy,
		RequestedOutputs: append([]string(nil), operation.Outputs...),
	}
	result := provider.executor.Execute(engineRequest)
	if result.Failure != nil {
		return contracts.CalculationReceipt{}, fmt.Errorf("%s for %s failed: %s", operationID, company.Ticker, result.Failure.Message)
	}
	return *result.Receipt, nil
}

func companyInputs(company Company, operationID string) ([]contracts.EngineInput, error) {
	metric := func(name string) (Metric, error) {
		value, ok := company.Metric(name)
		if !ok {
			return Metric{}, fmt.Errorf("%s is missing %s", company.Ticker, name)
		}
		return value, nil
	}
	mapInputs := func(pairs ...string) ([]contracts.EngineInput, error) {
		result := make([]contracts.EngineInput, 0, len(pairs)/2)
		for index := 0; index < len(pairs); index += 2 {
			value, err := metric(pairs[index+1])
			if err != nil {
				return nil, err
			}
			result = append(result, metricInput(pairs[index], value, value.Period))
		}
		return result, nil
	}
	switch operationID {
	case "financial.revenue_growth":
		return mapInputs("revenue_current", "revenue", "revenue_prior", "revenue_prior")
	case "financial.margin":
		return mapInputs("numerator", "operating_income", "revenue", "revenue")
	case "financial.free_cash_flow":
		return mapInputs("operating_cash_flow", "operating_cash_flow", "capital_expenditure", "capital_expenditure")
	case "financial.cash_conversion":
		return mapInputs("operating_cash_flow", "operating_cash_flow", "net_income", "net_income")
	case "financial.capex_intensity":
		return mapInputs("capital_expenditure", "capital_expenditure", "revenue", "revenue")
	default:
		return nil, fmt.Errorf("no golden input map for %q", operationID)
	}
}

func metricInput(inputID string, metric Metric, fallbackPeriod string) contracts.EngineInput {
	period := metric.Period
	if period == "" {
		period = fallbackPeriod
	}
	asOf := metric.SourceAvailableAt
	return input(inputID, metric.Value, metric.Unit, metric.Currency, period, "normalized", []string{metric.EvidenceID}, &asOf)
}

func input(inputID, value, unit, currency, period, status string, evidence []string, asOf *time.Time) contracts.EngineInput {
	return contracts.EngineInput{InputID: inputID, Quantity: contracts.Quantity{Value: value, Unit: unit, Currency: currency, Period: period, AsOf: asOf}, Status: status, EvidenceRefs: evidence}
}

func forecastInputs(company Company, forecast []string, discountRate, terminalGrowth string) []contracts.EngineInput {
	ocf, _ := company.Metric("operating_cash_flow")
	capex, _ := company.Metric("capital_expenditure")
	refs := []string{ocf.EvidenceID, capex.EvidenceID}
	inputs := make([]contracts.EngineInput, 0, len(forecast)+2)
	for index, value := range forecast {
		inputs = append(inputs, input(fmt.Sprintf("fcff_forecast.%d", index), value, "currency", "USD", fmt.Sprintf("FY%d", 2026+index), "assumed", refs, nil))
	}
	inputs = append(inputs,
		input("discount_rate", discountRate, "ratio", "", "", "assumed", nil, nil),
		input("terminal_growth", terminalGrowth, "ratio", "", "", "assumed", nil, nil),
	)
	return inputs
}

func sensitivityInputs(company Company, forecast []string) []contracts.EngineInput {
	base := forecastInputs(company, forecast, "0.1", "0.03")[:len(forecast)]
	for index := range base {
		base[index].InputID = fmt.Sprintf("fcff_forecast.%d", index)
	}
	for index, scenario := range company.OrderedScenarios() {
		base = append(base,
			input(fmt.Sprintf("discount_rates.%d", index), scenario.DiscountRate, "ratio", "", "", "assumed", nil, nil),
			input(fmt.Sprintf("terminal_growth_rates.%d", index), scenario.TerminalGrowth, "ratio", "", "", "assumed", nil, nil),
		)
	}
	return base
}

func compoundForecast(baseValue, growth string, years int) ([]string, error) {
	base, _, err := apd.NewFromString(baseValue)
	if err != nil {
		return nil, err
	}
	growthValue, _, err := apd.NewFromString(growth)
	if err != nil {
		return nil, err
	}
	one := apd.New(1, 0)
	factor := new(apd.Decimal)
	if _, err := numeric.DecimalContext.Add(factor, one, growthValue); err != nil {
		return nil, err
	}
	current := new(apd.Decimal).Set(base)
	result := make([]string, years)
	for index := 0; index < years; index++ {
		next := new(apd.Decimal)
		if _, err := numeric.DecimalContext.Mul(next, current, factor); err != nil {
			return nil, err
		}
		current = next
		canonical, err := numeric.ParseDecimal(current.String())
		if err != nil {
			return nil, err
		}
		result[index] = canonical.String()
	}
	return result, nil
}

func subtractMetric(company Company, leftID, rightID string) string {
	left, _ := company.Metric(leftID)
	right, _ := company.Metric(rightID)
	a, _, _ := apd.NewFromString(left.Value)
	b, _, _ := apd.NewFromString(right.Value)
	result := new(apd.Decimal)
	_, _ = numeric.DecimalContext.Sub(result, a, b)
	canonical, _ := numeric.ParseDecimal(result.String())
	return canonical.String()
}

func scenarioAssumption(company Company, scenario Scenario, baseFCF string) string {
	return fmt.Sprintf("Illustrative %s scenario for %s: the FY2025 simple free-cash-flow proxy of %s USD (operating cash flow less capital expenditure) grows at %s annually for five years, with a %s discount rate and %s terminal growth; this is not a forecast or investment recommendation.", scenario.Name, company.Ticker, baseFCF, scenario.AnnualFCFGrowth, scenario.DiscountRate, scenario.TerminalGrowth)
}

func scenarioByName(company Company, name string) Scenario {
	for _, scenario := range company.Scenarios {
		if scenario.Name == name {
			return scenario
		}
	}
	return Scenario{}
}

func fiscalPeriodBoundary(asOf time.Time, companies []Company) contracts.EvidenceItem {
	parts := make([]string, 0, len(companies))
	for _, company := range companies {
		parts = append(parts, fmt.Sprintf("%s %s ended %s", company.Ticker, company.FiscalPeriod, company.PeriodEnd.Format("2006-01-02")))
	}
	sort.Strings(parts)
	statement := strings.Join(parts, "; ") + ". Exact concurrent calendar-period comparability is unavailable."
	return contracts.EvidenceItem{
		EvidenceRef: contracts.EvidenceRef{EvidenceID: "comparison:fiscal-period-boundary", SourceType: "deterministic_scope_check", Locator: "fixture:golden/financial-snapshot.json", ContentSHA: hashText(statement), AsOf: asOf},
		State:       contracts.EvidenceIncomparable, Statement: statement, Warnings: []string{"nominal_fiscal_years_are_not_concurrent"},
	}
}

func companyFactsURI(companyID string) string {
	cik := strings.TrimPrefix(companyID, "sec-cik:")
	return "https://data.sec.gov/api/xbrl/companyfacts/CIK" + cik + ".json"
}

func displayUnit(metric Metric) string {
	if metric.Currency != "" {
		return metric.Currency + " " + metric.Unit
	}
	return metric.Unit
}

func priceEvidenceID(ticker string) string { return "market-price:" + strings.ToLower(ticker) }

func hashText(value string) string {
	digest := sha256.Sum256([]byte(value))
	return hex.EncodeToString(digest[:])
}

func uniqueEvidence(items []contracts.EvidenceItem) []contracts.EvidenceItem {
	seen := map[string]bool{}
	result := make([]contracts.EvidenceItem, 0, len(items))
	for _, item := range items {
		if seen[item.EvidenceRef.EvidenceID] {
			continue
		}
		seen[item.EvidenceRef.EvidenceID] = true
		result = append(result, item)
	}
	return result
}

func uniqueStrings(values []string) []string {
	seen := map[string]bool{}
	result := []string{}
	for _, value := range values {
		if value != "" && !seen[value] {
			seen[value] = true
			result = append(result, value)
		}
	}
	return result
}

func contains(values []string, value string) bool { return stringSet(values)[value] }

func stringSet(values []string) map[string]bool {
	result := make(map[string]bool, len(values))
	for _, value := range values {
		result[value] = true
	}
	return result
}

var _ localagent.MaterialProvider = (*Provider)(nil)
