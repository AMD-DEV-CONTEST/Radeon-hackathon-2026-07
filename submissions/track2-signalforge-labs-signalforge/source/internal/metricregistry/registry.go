package metricregistry

import (
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"sort"
	"strings"

	"github.com/rvbernucci/signalforge/internal/capability"
)

type Lifecycle string

const (
	LifecycleDraft      Lifecycle = "draft"
	LifecycleReviewed   Lifecycle = "reviewed"
	LifecycleActive     Lifecycle = "active"
	LifecycleDeprecated Lifecycle = "deprecated"
	LifecycleSuperseded Lifecycle = "superseded"
)

type CompanyProfile string

const (
	ProfileOperatingCompany CompanyProfile = "operating_company"
	ProfileBank             CompanyProfile = "bank"
	ProfileInsurer          CompanyProfile = "insurer"
	ProfileREIT             CompanyProfile = "reit"
	ProfileUtility          CompanyProfile = "regulated_utility"
	ProfilePreRevenue       CompanyProfile = "pre_revenue"
)

type GAAPStatus string

const (
	GAAPReported    GAAPStatus = "gaap_reported"
	GAAPDerived     GAAPStatus = "derived_from_gaap"
	IssuerNonGAAP   GAAPStatus = "issuer_non_gaap"
	Analytical      GAAPStatus = "analytical"
	MixedDefinition GAAPStatus = "mixed"
)

type PeriodBasis string

const (
	PeriodInstant          PeriodBasis = "instant"
	PeriodDuration         PeriodBasis = "duration"
	PeriodAverageBalance   PeriodBasis = "average_balance"
	PeriodBeginningBalance PeriodBasis = "beginning_balance"
	PeriodSeries           PeriodBasis = "series"
	PeriodMixed            PeriodBasis = "mixed"
)

type InputDefinition struct {
	Name             string
	QuantityKind     string
	SignPolicy       string
	Required         bool
	AcceptedConcepts []string
}

type OutputDefinition struct {
	QuantityKind    string
	UnitPolicy      string
	PrecisionPolicy string
}

type PeriodPolicy struct {
	Basis               PeriodBasis
	AlignmentRequired   bool
	LookAheadProhibited bool
}

type Applicability struct {
	DefaultProfile      CompanyProfile
	ExcludedProfiles    []CompanyProfile
	NegativeValuePolicy string
}

type Definition struct {
	MetricID               string
	Version                string
	Status                 Lifecycle
	Name                   string
	EconomicMeaning        string
	FormulaExpression      string
	Convention             string
	ImplementationOwner    string
	Inputs                 []InputDefinition
	Output                 OutputDefinition
	PeriodPolicy           PeriodPolicy
	Applicability          Applicability
	GAAPStatus             GAAPStatus
	ReconciliationRequired bool
	DefinitionSources      []string
	ReviewOwner            string
	FailureDispositions    []string
	Supersedes             string
}

type Registry struct {
	versions map[string]map[string]Definition
	active   map[string]string
}

var (
	metricIDPattern = regexp.MustCompile(`^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`)
	versionPattern  = regexp.MustCompile(`^[0-9]+\.[0-9]+\.[0-9]+$`)
)

func New(definitions []Definition) (Registry, error) {
	registry := Registry{
		versions: make(map[string]map[string]Definition),
		active:   make(map[string]string),
	}
	for _, definition := range definitions {
		if err := validateDefinition(definition); err != nil {
			return Registry{}, fmt.Errorf("metric %q: %w", definition.MetricID, err)
		}
		if registry.versions[definition.MetricID] == nil {
			registry.versions[definition.MetricID] = make(map[string]Definition)
		}
		if _, exists := registry.versions[definition.MetricID][definition.Version]; exists {
			return Registry{}, fmt.Errorf("duplicate metric version %q@%s", definition.MetricID, definition.Version)
		}
		if definition.Status == LifecycleActive {
			if prior, exists := registry.active[definition.MetricID]; exists {
				return Registry{}, fmt.Errorf("multiple active versions for %q: %s and %s", definition.MetricID, prior, definition.Version)
			}
			registry.active[definition.MetricID] = definition.Version
		}
		registry.versions[definition.MetricID][definition.Version] = cloneDefinition(definition)
	}
	return registry, nil
}

func Default() Registry {
	registry, err := New(defaultDefinitions())
	if err != nil {
		panic(err)
	}
	return registry
}

func (registry Registry) Get(metricID, version string) (Definition, bool) {
	versions, exists := registry.versions[metricID]
	if !exists {
		return Definition{}, false
	}
	definition, exists := versions[version]
	return cloneDefinition(definition), exists
}

func (registry Registry) Active(metricID string) (Definition, bool) {
	version, exists := registry.active[metricID]
	if !exists {
		return Definition{}, false
	}
	return registry.Get(metricID, version)
}

func (registry Registry) ListActive() []Definition {
	ids := make([]string, 0, len(registry.active))
	for id := range registry.active {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	result := make([]Definition, 0, len(ids))
	for _, id := range ids {
		definition, _ := registry.Active(id)
		result = append(result, definition)
	}
	return result
}

func (registry Registry) Applies(metricID string, profile CompanyProfile) (bool, string) {
	definition, exists := registry.Active(metricID)
	if !exists {
		return false, "definition_missing"
	}
	for _, excluded := range definition.Applicability.ExcludedProfiles {
		if excluded == profile {
			return false, "not_applicable"
		}
	}
	return true, "applicable"
}

func validateDefinition(definition Definition) error {
	if !metricIDPattern.MatchString(definition.MetricID) || !versionPattern.MatchString(definition.Version) {
		return errors.New("metric ID or semantic version is invalid")
	}
	switch definition.Status {
	case LifecycleDraft, LifecycleReviewed, LifecycleActive, LifecycleDeprecated, LifecycleSuperseded:
	default:
		return errors.New("unsupported lifecycle status")
	}
	if definition.Name == "" || definition.EconomicMeaning == "" || definition.FormulaExpression == "" || definition.Convention == "" {
		return errors.New("name, meaning, formula, and convention are required")
	}
	if definition.ImplementationOwner != "deterministic_go" {
		return errors.New("implementation owner must be deterministic_go")
	}
	if len(definition.Inputs) == 0 || definition.Output.QuantityKind == "" || definition.Output.UnitPolicy == "" || definition.Output.PrecisionPolicy == "" {
		return errors.New("typed inputs and output policy are required")
	}
	seenInputs := make(map[string]bool)
	for _, input := range definition.Inputs {
		if strings.TrimSpace(input.Name) == "" || strings.TrimSpace(input.QuantityKind) == "" || strings.TrimSpace(input.SignPolicy) == "" {
			return errors.New("input name, quantity kind, and sign policy are required")
		}
		if seenInputs[input.Name] {
			return fmt.Errorf("duplicate input %q", input.Name)
		}
		seenInputs[input.Name] = true
	}
	switch definition.PeriodPolicy.Basis {
	case PeriodInstant, PeriodDuration, PeriodAverageBalance, PeriodBeginningBalance, PeriodSeries, PeriodMixed:
	default:
		return errors.New("unsupported period basis")
	}
	if !definition.PeriodPolicy.LookAheadProhibited {
		return errors.New("look-ahead must be prohibited")
	}
	if definition.Applicability.DefaultProfile == "" || definition.Applicability.NegativeValuePolicy == "" {
		return errors.New("applicability profile and negative-value policy are required")
	}
	if definition.GAAPStatus == IssuerNonGAAP && !definition.ReconciliationRequired {
		return errors.New("issuer non-GAAP metrics require reconciliation")
	}
	if len(definition.DefinitionSources) == 0 || definition.ReviewOwner == "" {
		return errors.New("definition sources and review owner are required")
	}
	for _, raw := range definition.DefinitionSources {
		parsed, err := url.ParseRequestURI(raw)
		if err != nil || parsed.Scheme == "" {
			return fmt.Errorf("invalid definition source %q", raw)
		}
	}
	if len(definition.FailureDispositions) == 0 {
		return errors.New("failure dispositions are required")
	}
	return nil
}

func cloneDefinition(definition Definition) Definition {
	definition.Inputs = append([]InputDefinition(nil), definition.Inputs...)
	for index := range definition.Inputs {
		definition.Inputs[index].AcceptedConcepts = append([]string(nil), definition.Inputs[index].AcceptedConcepts...)
	}
	definition.Applicability.ExcludedProfiles = append([]CompanyProfile(nil), definition.Applicability.ExcludedProfiles...)
	definition.DefinitionSources = append([]string(nil), definition.DefinitionSources...)
	definition.FailureDispositions = append([]string(nil), definition.FailureDispositions...)
	return definition
}

type metadata struct {
	name       string
	meaning    string
	formula    string
	convention string
	period     PeriodBasis
	aligned    bool
	gaap       GAAPStatus
	excluded   []CompanyProfile
	negative   string
}

func defaultDefinitions() []Definition {
	operations := capability.RuntimeRegistry().List()
	meta := baselineMetadata()
	definitions := make([]Definition, 0, len(operations))
	for _, operation := range operations {
		item, exists := meta[operation.ID]
		if !exists {
			panic("canonical metric metadata missing for " + operation.ID)
		}
		inputs := make([]InputDefinition, 0, len(operation.RequiredInputs))
		for _, name := range operation.RequiredInputs {
			inputs = append(inputs, InputDefinition{
				Name: name, QuantityKind: quantityKind(name), SignPolicy: signPolicy(name), Required: true,
				AcceptedConcepts: acceptedConcepts(name),
			})
		}
		definitions = append(definitions, Definition{
			MetricID: operation.ID, Version: operation.FormulaVersion, Status: LifecycleActive,
			Name: item.name, EconomicMeaning: item.meaning,
			FormulaExpression: item.formula, Convention: item.convention,
			ImplementationOwner: "deterministic_go", Inputs: inputs,
			Output:        OutputDefinition{QuantityKind: outputKind(operation.NumericalPolicy), UnitPolicy: operation.NumericalPolicy, PrecisionPolicy: operation.NumericalPolicy},
			PeriodPolicy:  PeriodPolicy{Basis: item.period, AlignmentRequired: item.aligned, LookAheadProhibited: true},
			Applicability: Applicability{DefaultProfile: ProfileOperatingCompany, ExcludedProfiles: item.excluded, NegativeValuePolicy: item.negative},
			GAAPStatus:    item.gaap, ReconciliationRequired: item.gaap == IssuerNonGAAP,
			DefinitionSources: definitionSources(operation.ID), ReviewOwner: reviewOwner(operation.ID),
			FailureDispositions: []string{"not_applicable", "insufficient_evidence", "period_mismatch", "unit_mismatch", "currency_mismatch", "invalid_denominator", "definition_conflict", "look_ahead_detected"},
		})
	}
	return definitions
}

func baselineMetadata() map[string]metadata {
	operatingExclusions := []CompanyProfile{ProfileBank, ProfileInsurer, ProfileREIT}
	definitions := map[string]metadata{
		"accounting.balance_sheet_identity": {"Balance-sheet identity", "Tests whether reported assets reconcile with liabilities and equity.", "assets - (liabilities + equity)", "Exact statement-date identity with an explicit tolerance.", PeriodInstant, true, GAAPDerived, nil, "signed difference is valid"},
		"financial.revenue_growth":          {"Revenue growth", "Measures period-aligned change in revenue.", "(revenue_current - revenue_prior) / revenue_prior", "Periods, currency, scale, and definition must match.", PeriodDuration, false, GAAPDerived, nil, "prior revenue must be non-zero"},
		"financial.cagr":                    {"Compound annual growth", "Annualizes change between positive endpoints.", "(value_end / value_start)^(1 / years) - 1", "Positive starting value and positive duration.", PeriodMixed, false, Analytical, nil, "negative endpoints are outside this convention"},
		"financial.margin":                  {"Named margin", "Measures a registered profit or cash-flow numerator relative to revenue.", "numerator / revenue", "The requested numerator definition must be named outside this generic primitive.", PeriodDuration, true, GAAPDerived, nil, "revenue must be non-zero"},
		"financial.free_cash_flow":          {"Operating-cash-flow free cash flow", "Measures operating cash retained after registered capital expenditure.", "operating_cash_flow - capital_expenditure", "Capital expenditure is supplied as a positive use of cash.", PeriodDuration, true, Analytical, operatingExclusions, "negative free cash flow remains meaningful"},
		"financial.cash_conversion":         {"Cash conversion", "Compares operating cash flow with aligned net income.", "operating_cash_flow / net_income", "Net income denominator; interpretation is bounded when earnings are non-positive.", PeriodDuration, true, Analytical, operatingExclusions, "non-positive earnings require warning or refusal"},
		"financial.capex_intensity":         {"Capital-expenditure intensity", "Measures capital expenditure relative to revenue.", "capital_expenditure / revenue", "Capital expenditure is supplied as a positive use of cash.", PeriodDuration, true, Analytical, operatingExclusions, "revenue must be positive"},
		"financial.net_debt":                {"Net debt", "Measures debt after cash and cash-equivalent resources.", "debt - cash_and_equivalents", "Debt and cash must share date, currency, and perimeter.", PeriodInstant, true, Analytical, nil, "negative output denotes net cash"},
		"financial.dilution":                {"Diluted-share change", "Measures period-aligned change in diluted shares.", "(shares_current - shares_prior) / shares_prior", "Uses weighted-average diluted shares for duration comparisons.", PeriodDuration, false, GAAPDerived, nil, "prior shares must be positive"},
		"financial.roic_proxy":              {"ROIC proxy", "Compares supplied NOPAT with supplied invested capital.", "nopat / invested_capital", "Proxy remains distinct from a fully governed ROIC definition.", PeriodMixed, true, Analytical, operatingExclusions, "non-positive capital is not economically interpretable"},
		"financial.current_ratio":           {"Current ratio", "Measures current assets relative to current liabilities.", "current_assets / current_liabilities", "Statement-date liquidity measure.", PeriodInstant, true, GAAPDerived, operatingExclusions, "current liabilities must be positive"},
		"financial.debt_to_equity":          {"Debt to equity", "Measures registered debt relative to book equity.", "debt / equity", "Statement-date leverage measure using the registered debt perimeter.", PeriodInstant, true, Analytical, nil, "non-positive equity requires warning or refusal"},
		"financial.earnings_per_share":      {"Derived diluted EPS", "Calculates earnings per diluted weighted-average share.", "net_income / diluted_shares", "Net income and shares must cover the same duration.", PeriodDuration, true, GAAPDerived, nil, "diluted shares must be positive"},
		"financial.quality_of_earnings":     {"Cash-to-earnings bridge", "Compares operating cash flow and net income through gap and conversion.", "{operating_cash_flow - net_income, operating_cash_flow / net_income}", "Aligned duration and accounting perimeter.", PeriodDuration, true, Analytical, operatingExclusions, "non-positive income limits ratio interpretation"},
		"valuation.fcff_dcf":                {"FCFF discounted cash flow", "Values operating assets from explicit FCFF and terminal assumptions.", "sum(FCFF_t/(1+WACC)^t) + terminal_value/(1+WACC)^n", "End-of-period discounting and perpetuity-growth terminal value.", PeriodMixed, false, Analytical, operatingExclusions, "discount rate must exceed terminal growth"},
		"valuation.reverse_dcf":             {"Reverse DCF terminal growth", "Solves the terminal-growth assumption implied by enterprise value under a fixed FCFF path.", "solve(FCFF_DCF(g) = enterprise_value)", "Bisection under the registered DCF convention.", PeriodMixed, false, Analytical, operatingExclusions, "non-convergence fails closed"},
		"valuation.enterprise_to_equity":    {"Enterprise-to-equity bridge", "Bridges enterprise value to equity value and value per diluted share.", "enterprise_value - net_debt + non_operating_assets", "Registered bridge with explicit diluted shares.", PeriodInstant, true, Analytical, nil, "diluted shares must be positive"},
		"valuation.peer_multiple":           {"Registered peer multiple", "Relates a market-value numerator to a compatible financial denominator.", "market_value / metric_value", "Value level and denominator definition must be declared by the caller.", PeriodMixed, false, Analytical, nil, "non-positive denominators require explicit policy"},
		"valuation.wacc":                    {"Weighted average cost of capital", "Weights cost of equity and after-tax debt cost by market capital.", "E/(D+E)*Ke + D/(D+E)*Kd*(1-T)", "Market-value weights and explicit marginal tax assumption.", PeriodInstant, false, Analytical, operatingExclusions, "capital values cannot be negative"},
		"economics.real_rate":               {"Exact real rate", "Deflates a nominal rate by an inflation measure.", "(1 + nominal_rate)/(1 + inflation_measure) - 1", "Exact Fisher transform.", PeriodDuration, true, Analytical, nil, "inflation measure must exceed -100 percent"},
		"economics.yield_curve":             {"Yield-curve spread", "Measures a named long yield less a named short yield.", "long_yield - short_yield", "Maturities, timestamps, and source conventions must be explicit.", PeriodInstant, true, Analytical, nil, "signed spread is valid"},
		"market.total_return":               {"Point-to-point total return", "Measures price change plus distributions relative to start price.", "(end_price + distributions - start_price) / start_price", "Aligned security, adjustment, and date convention.", PeriodSeries, false, Analytical, nil, "start price must be positive"},
		"market.volatility":                 {"Annualized volatility", "Annualizes sample dispersion of aligned periodic returns.", "stdev(returns) * sqrt(periods_per_year)", "Sample standard deviation unless ddof is explicitly changed.", PeriodSeries, false, Analytical, nil, "minimum sample and finite values required"},
		"market.drawdown":                   {"Drawdown", "Measures decline from each prior wealth-index peak.", "wealth_index/current_running_peak - 1", "Positive aligned wealth-index series.", PeriodSeries, false, Analytical, nil, "wealth index must remain positive"},
		"market.beta":                       {"Market beta", "Measures covariance with a benchmark relative to benchmark variance.", "cov(security, benchmark) / var(benchmark)", "Aligned return observations and explicit ddof.", PeriodSeries, false, Analytical, nil, "benchmark variance must be positive"},
		"market.rolling_correlation":        {"Rolling correlation", "Measures windowed linear association between aligned series.", "corr(series_x_window, series_y_window)", "Association only; no causal interpretation.", PeriodSeries, false, Analytical, nil, "window and sample variance must be valid"},
		"comparison.period_aligned":         {"Exact-period comparability", "Determines whether company metrics share period, unit, and currency.", "all(period, unit, currency compatible)", "No numerical ranking is released for incompatible observations.", PeriodMixed, true, Analytical, nil, "incomparability is a valid disposition"},
		"scenario.sensitivity_matrix":       {"DCF sensitivity matrix", "Evaluates enterprise value across explicit discount-rate and terminal-growth axes.", "FCFF_DCF for each (discount_rate, terminal_growth)", "Each cell uses the same FCFF path and registered DCF convention.", PeriodMixed, false, Analytical, operatingExclusions, "invalid cells fail instead of extrapolating"},
	}
	for id, definition := range advancedMetadata(operatingExclusions) {
		definitions[id] = definition
	}
	return definitions
}

func advancedMetadata(operatingExclusions []CompanyProfile) map[string]metadata {
	return map[string]metadata{
		"financial.nopat":                            {"Net operating profit after tax", "Measures after-tax operating profit independent of financing.", "operating_income * (1 - tax_rate)", "Explicit analytical tax rate; no implied tax substitution.", PeriodDuration, true, Analytical, operatingExclusions, "negative operating profit produces negative NOPAT"},
		"financial.invested_capital":                 {"Invested capital reconciliation", "Reconciles operating assets less operating liabilities with financing capital less non-operating resources.", "{operating_assets - NIBOL, debt + equity - cash - non_operating_assets}", "Both approaches must use the same perimeter and statement date.", PeriodInstant, true, Analytical, operatingExclusions, "non-positive capital limits return interpretation"},
		"financial.average_invested_capital":         {"Average invested capital", "Averages beginning and ending invested capital for a duration return.", "(invested_capital_beginning + invested_capital_ending) / 2", "Both balances must be positive and bracket the measured duration.", PeriodAverageBalance, false, Analytical, operatingExclusions, "both balances must be positive"},
		"financial.operating_working_capital":        {"Operating working capital", "Measures non-cash operating current assets less non-interest-bearing operating current liabilities.", "AR + inventory + other_operating_current_assets - AP - other_operating_current_liabilities", "Cash, debt, and financing balances are excluded.", PeriodInstant, true, Analytical, operatingExclusions, "signed operating working capital is valid"},
		"financial.change_in_working_capital":        {"Change in operating working capital", "Measures incremental cash committed to operating working capital.", "operating_working_capital_ending - operating_working_capital_beginning", "Positive change is a use of cash.", PeriodMixed, false, Analytical, operatingExclusions, "signed change is valid"},
		"financial.net_capex":                        {"Net capital expenditure", "Measures capital expenditure after depreciation and amortization.", "capital_expenditure - depreciation_and_amortization", "Capital expenditure is supplied as a positive use of cash.", PeriodDuration, true, Analytical, operatingExclusions, "negative net capex is retained and disclosed"},
		"financial.reinvestment":                     {"Operating reinvestment", "Aggregates net capex, working-capital investment, and acquisitions.", "net_capex + change_in_working_capital + acquisitions", "Acquisitions are included only under the registered analytical convention.", PeriodDuration, true, Analytical, operatingExclusions, "signed components remain visible"},
		"financial.fcff_from_nopat":                  {"FCFF from NOPAT", "Measures after-tax operating profit remaining after reinvestment.", "nopat - reinvestment", "NOPAT and reinvestment share period and perimeter.", PeriodDuration, true, Analytical, operatingExclusions, "negative FCFF is valid"},
		"financial.fcfe":                             {"Free cash flow to equity", "Measures cash available to equity after reinvestment and net borrowing.", "net_income - capex + D&A - change_in_working_capital + net_borrowing", "All components share period, currency, and equity perimeter.", PeriodDuration, true, Analytical, operatingExclusions, "negative FCFE is valid"},
		"financial.roic":                             {"Return on invested capital", "Measures NOPAT relative to average invested capital.", "nopat / average_invested_capital", "Average invested capital and NOPAT must use the same operating perimeter.", PeriodMixed, false, Analytical, operatingExclusions, "average invested capital must be positive"},
		"financial.incremental_roic":                 {"Incremental ROIC", "Measures change in NOPAT relative to positive incremental invested capital.", "change_in_nopat / change_in_invested_capital", "Aligned multi-period analytical measure.", PeriodMixed, false, Analytical, operatingExclusions, "incremental capital must be positive"},
		"financial.roce":                             {"Return on capital employed", "Measures EBIT relative to total assets less current liabilities.", "ebit / (total_assets - current_liabilities)", "Operating-company capital-employed convention.", PeriodMixed, false, Analytical, operatingExclusions, "capital employed must be positive"},
		"financial.value_creation_spread":            {"ROIC-WACC spread", "Measures operating return above or below the registered capital cost.", "roic - wacc", "ROIC and WACC must share currency, perimeter, and assumptions.", PeriodMixed, false, Analytical, operatingExclusions, "signed spread is valid"},
		"financial.reinvestment_rate":                {"Reinvestment rate", "Measures reinvestment relative to positive NOPAT.", "reinvestment / nopat", "Only released with positive NOPAT.", PeriodDuration, true, Analytical, operatingExclusions, "NOPAT must be positive"},
		"financial.fundamental_growth":               {"Fundamental growth", "Relates return on capital and reinvestment under explicit assumptions.", "return_on_capital * reinvestment_rate", "Identity is an analytical scenario, not a forecast.", PeriodMixed, false, Analytical, operatingExclusions, "signed return remains explicit"},
		"financial.operating_margin":                 {"Operating margin", "Measures operating income relative to revenue.", "operating_income / revenue", "Typed operating numerator and aligned revenue.", PeriodDuration, true, GAAPDerived, operatingExclusions, "revenue must be positive"},
		"financial.incremental_margin":               {"Incremental operating margin", "Measures incremental operating income per incremental revenue.", "delta_operating_income / delta_revenue", "Current and prior periods must be comparable.", PeriodMixed, false, Analytical, operatingExclusions, "incremental revenue must be positive"},
		"financial.accrual_intensity":                {"Accrual intensity", "Measures earnings less operating cash flow relative to average assets.", "(net_income - operating_cash_flow) / average_assets", "Aligned duration and average balance.", PeriodMixed, true, Analytical, operatingExclusions, "average assets must be positive"},
		"financial.cash_conversion_cycle":            {"Cash conversion cycle", "Combines receivable, inventory, and payable days.", "DSO + DIO - DPO", "All component days use the same period convention.", PeriodDuration, true, Analytical, operatingExclusions, "signed cycle is valid"},
		"financial.quick_ratio":                      {"Quick ratio", "Measures cash, marketable securities, and receivables relative to current liabilities.", "(cash + marketable_securities + accounts_receivable) / current_liabilities", "Statement-date liquidity measure.", PeriodInstant, true, Analytical, operatingExclusions, "current liabilities must be positive"},
		"financial.cash_ratio":                       {"Cash ratio", "Measures cash and marketable securities relative to current liabilities.", "(cash + marketable_securities) / current_liabilities", "Statement-date liquidity measure.", PeriodInstant, true, Analytical, operatingExclusions, "current liabilities must be positive"},
		"financial.interest_coverage":                {"Interest coverage", "Measures EBIT relative to positive interest expense.", "ebit / interest_expense", "Aligned duration and gross interest-expense convention.", PeriodDuration, true, Analytical, operatingExclusions, "interest expense must be positive"},
		"financial.net_debt_to_ebitda":               {"Net debt to EBITDA", "Measures net debt relative to positive EBITDA.", "net_debt / ebitda", "Debt date and EBITDA period are explicitly bridged.", PeriodMixed, false, Analytical, operatingExclusions, "EBITDA must be positive; net cash is valid"},
		"financial.cash_conversion_ebitda":           {"EBITDA cash conversion", "Measures operating cash flow relative to positive EBITDA.", "operating_cash_flow / ebitda", "Aligned duration and EBITDA definition.", PeriodDuration, true, Analytical, operatingExclusions, "EBITDA must be positive"},
		"financial.cash_conversion_operating_profit": {"Operating-profit cash conversion", "Measures operating cash flow relative to positive operating profit.", "operating_cash_flow / operating_profit", "Aligned duration and operating-profit definition.", PeriodDuration, true, Analytical, operatingExclusions, "operating profit must be positive"},
		"financial.buyback_yield":                    {"Buyback yield", "Measures net repurchases relative to equity market value.", "net_repurchases / market_capitalization", "Signed net repurchases and point-in-time market capitalization.", PeriodMixed, false, Analytical, nil, "market capitalization must be positive"},
		"financial.dividend_yield":                   {"Dividend yield", "Measures dividends paid relative to equity market value.", "dividends_paid / market_capitalization", "Aligned dividends and point-in-time market capitalization.", PeriodMixed, false, Analytical, nil, "market capitalization must be positive"},
		"financial.net_payout_yield":                 {"Net payout yield", "Measures dividends plus net repurchases relative to equity market value.", "(dividends_paid + net_repurchases) / market_capitalization", "Signed capital returns and point-in-time market capitalization.", PeriodMixed, false, Analytical, nil, "market capitalization must be positive"},
		"financial.shareholder_yield":                {"Shareholder yield", "Measures net repurchases, dividends, and net debt reduction relative to equity market value.", "(net_repurchases + dividends_paid + net_debt_reduction) / market_capitalization", "Signed capital returns and point-in-time market capitalization.", PeriodMixed, false, Analytical, nil, "market capitalization must be positive"},
		"financial.capital_allocation_bridge":        {"Capital allocation bridge", "Reconciles registered cash sources and uses to reported cash change.", "sources - uses = implied_change_in_cash", "Every component is a positive source or use under the registered sign convention.", PeriodDuration, true, Analytical, operatingExclusions, "reconciliation gap must remain visible"},
		"valuation.capm":                             {"CAPM cost of equity", "Calculates required equity return from risk-free rate, beta, and equity risk premium.", "risk_free_rate + beta * equity_risk_premium", "All market inputs share as-of and frequency policy.", PeriodInstant, true, Analytical, nil, "signed beta remains explicit"},
		"valuation.unlever_beta":                     {"Unlevered beta", "Removes registered financial leverage from observed beta.", "levered_beta / (1 + (1-tax_rate)*debt/equity)", "Debt, equity, and tax conventions are explicit.", PeriodInstant, true, Analytical, operatingExclusions, "equity must be positive"},
		"valuation.relever_beta":                     {"Relevered beta", "Applies a target leverage and tax convention to an unlevered beta.", "unlevered_beta * (1 + (1-tax_rate)*debt/equity)", "Target debt, equity, and tax conventions are assumptions.", PeriodInstant, true, Analytical, operatingExclusions, "equity must be positive"},
		"valuation.multistage_dcf_perpetuity":        {"Multi-stage FCFF DCF - perpetuity", "Values operating assets with explicit FCFF and a perpetuity-growth terminal value.", "PV(explicit_FCFF) + PV(FCFF_n*(1+g)/(WACC-g))", "End-of-period terminal discounting; optional explicit mid-year convention for forecast flows.", PeriodMixed, false, Analytical, operatingExclusions, "WACC must exceed terminal growth"},
		"valuation.multistage_dcf_exit":              {"Multi-stage FCFF DCF - exit multiple", "Values operating assets with explicit FCFF and an exit-multiple terminal value.", "PV(explicit_FCFF) + PV(exit_metric*exit_multiple)", "Exit metric and multiple are explicit assumptions.", PeriodMixed, false, Analytical, operatingExclusions, "exit metric non-negative and multiple positive"},
		"valuation.dividend_discount":                {"Multi-stage dividend discount", "Values equity from explicit dividends and terminal growth for an applicable dividend-paying issuer.", "PV(explicit_dividends) + PV(dividend_n*(1+g)/(cost_of_equity-g))", "Applicability and payout sustainability must be established before use.", PeriodMixed, false, Analytical, []CompanyProfile{ProfilePreRevenue}, "cost of equity must exceed terminal growth"},
		"valuation.reverse_revenue_growth":           {"Reverse DCF revenue growth", "Solves constant explicit revenue growth implied by enterprise value under bounded operating assumptions.", "solve(DCF(revenue_growth) = enterprise_value)", "Bisection over a disclosed range with fixed margin, tax, reinvestment, WACC, and terminal growth.", PeriodMixed, false, Analytical, operatingExclusions, "non-convergence fails closed"},
		"valuation.reverse_operating_margin":         {"Reverse DCF operating margin", "Solves the operating margin implied by enterprise value under bounded assumptions.", "solve(DCF(operating_margin) = enterprise_value)", "Bisection over a disclosed margin range.", PeriodMixed, false, Analytical, operatingExclusions, "non-convergence fails closed"},
		"valuation.reverse_reinvestment_rate":        {"Reverse DCF reinvestment rate", "Solves the reinvestment rate implied by enterprise value under bounded assumptions.", "solve(DCF(reinvestment_rate) = enterprise_value)", "Bisection over a disclosed reinvestment range.", PeriodMixed, false, Analytical, operatingExclusions, "non-convergence fails closed"},
		"valuation.implied_roic":                     {"Implied return on capital", "Relates an explicit growth assumption to an explicit reinvestment rate.", "growth_rate / reinvestment_rate", "Analytical identity, not a forecast.", PeriodMixed, false, Analytical, operatingExclusions, "reinvestment rate must be non-zero"},
		"valuation.enterprise_to_equity_detailed":    {"Detailed enterprise-to-equity bridge", "Bridges enterprise value to diluted equity value using explicit financing and non-operating adjustments.", "enterprise_value - debt + cash + investments - minority_interest - option_value", "All adjustments share as-of, currency, and perimeter.", PeriodInstant, true, Analytical, nil, "diluted shares must be positive"},
		"valuation.ev_to_ebitda":                     {"EV to EBITDA", "Relates enterprise value to positive EBITDA.", "enterprise_value / ebitda", "Enterprise-level numerator and denominator.", PeriodMixed, false, Analytical, operatingExclusions, "EBITDA must be positive"},
		"valuation.ev_to_revenue":                    {"EV to revenue", "Relates enterprise value to positive revenue.", "enterprise_value / revenue", "Enterprise-level numerator and denominator.", PeriodMixed, false, Analytical, operatingExclusions, "revenue must be positive"},
		"valuation.ev_to_ebit":                       {"EV to EBIT", "Relates enterprise value to positive EBIT.", "enterprise_value / ebit", "Enterprise-level numerator and denominator.", PeriodMixed, false, Analytical, operatingExclusions, "EBIT must be positive"},
		"valuation.price_to_earnings":                {"Price to earnings", "Relates equity market value to positive net income.", "equity_market_value / net_income", "Equity-level numerator and denominator.", PeriodMixed, false, Analytical, nil, "net income must be positive"},
		"valuation.price_to_book":                    {"Price to book", "Relates equity market value to positive book equity.", "equity_market_value / book_equity", "Equity-level numerator and denominator.", PeriodInstant, true, Analytical, nil, "book equity must be positive"},
		"valuation.price_to_fcf":                     {"Price to free cash flow", "Relates equity market value to positive free cash flow to equity.", "equity_market_value / free_cash_flow_to_equity", "Equity-level numerator and denominator.", PeriodMixed, false, Analytical, operatingExclusions, "free cash flow to equity must be positive"},
		"valuation.fcf_yield":                        {"Free-cash-flow yield", "Measures free cash flow to equity relative to equity market value.", "free_cash_flow_to_equity / equity_market_value", "Equity-level numerator and denominator.", PeriodMixed, false, Analytical, operatingExclusions, "equity market value must be positive"},
		"valuation.earnings_yield":                   {"Earnings yield", "Measures net income relative to equity market value.", "net_income / equity_market_value", "Equity-level numerator and denominator.", PeriodMixed, false, Analytical, nil, "equity market value must be positive"},
		"comparison.dupont":                          {"Three-factor DuPont", "Decomposes return on equity into margin, turnover, and leverage.", "net_income/revenue * revenue/average_assets * average_assets/average_equity", "Aligned duration with positive average balance denominators.", PeriodMixed, false, Analytical, operatingExclusions, "all denominators must be positive"},
		"comparison.peer_statistics":                 {"Robust peer context", "Places a subject value within a declared peer sample using median, percentile, MAD, and robust z-score.", "robust_distribution(peer_values, subject_value)", "Cohort, dates, definitions, and minimum sample are external contract fields.", PeriodSeries, false, Analytical, nil, "finite minimum sample required"},
		"economics.lagged_association":               {"Lagged linear association", "Measures lagged linear association between aligned driver and outcome series.", "OLS(outcome_t on driver_t-lag)", "Association is explicitly not causal evidence.", PeriodSeries, false, Analytical, nil, "finite aligned sample with non-zero variance required"},
	}
}

func quantityKind(name string) string {
	lower := strings.ToLower(name)
	exact := map[string]string{
		"beta": "ratio", "levered_beta": "ratio", "unlevered_beta": "ratio",
		"roic": "ratio", "wacc": "ratio", "return_on_capital": "ratio",
		"exit_multiple": "ratio", "subject_value": "ratio",
		"mid_year": "boolean", "lag": "count", "minimum_sample": "count",
		"days_sales_outstanding": "days", "days_inventory_outstanding": "days", "days_payables_outstanding": "days",
		"years": "years", "peer_values": "series",
	}
	if kind, exists := exact[lower]; exists {
		return kind
	}
	switch {
	case strings.Contains(lower, "rate"), strings.Contains(lower, "margin"), strings.Contains(lower, "yield"), strings.Contains(lower, "inflation"):
		return "ratio"
	case strings.Contains(lower, "shares"):
		return "shares"
	case strings.Contains(lower, "years"):
		return "years"
	case strings.Contains(lower, "returns"), strings.Contains(lower, "forecast"), strings.Contains(lower, "series"), strings.Contains(lower, "index"):
		return "series"
	case strings.Contains(lower, "window"), strings.Contains(lower, "ddof"), strings.Contains(lower, "periods_per_year"):
		return "count"
	default:
		return "money"
	}
}

func signPolicy(name string) string {
	lower := strings.ToLower(name)
	if strings.Contains(lower, "growth") || strings.Contains(lower, "return") || strings.Contains(lower, "income") || strings.Contains(lower, "flow") || strings.Contains(lower, "equity") {
		return "signed value permitted subject to metric-specific denominator policy"
	}
	return "non-negative unless source accounting convention and definition explicitly permit otherwise"
}

func acceptedConcepts(name string) []string {
	concepts := map[string][]string{
		"assets":               {"us-gaap:Assets"},
		"liabilities":          {"us-gaap:Liabilities"},
		"equity":               {"us-gaap:StockholdersEquity", "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"},
		"revenue":              {"us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap:SalesRevenueNet"},
		"revenue_current":      {"us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap:SalesRevenueNet"},
		"revenue_prior":        {"us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap:SalesRevenueNet"},
		"operating_cash_flow":  {"us-gaap:NetCashProvidedByUsedInOperatingActivities"},
		"capital_expenditure":  {"us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"},
		"net_income":           {"us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss"},
		"cash_and_equivalents": {"us-gaap:CashAndCashEquivalentsAtCarryingValue"},
		"debt":                 {"us-gaap:LongTermDebtAndFinanceLeaseObligationsCurrent", "us-gaap:LongTermDebtAndFinanceLeaseObligationsNoncurrent"},
		"current_assets":       {"us-gaap:AssetsCurrent"},
		"current_liabilities":  {"us-gaap:LiabilitiesCurrent"},
		"diluted_shares":       {"us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding"},
		"shares_current":       {"us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding"},
		"shares_prior":         {"us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding"},
	}
	return append([]string(nil), concepts[name]...)
}

func outputKind(policy string) string {
	switch {
	case strings.HasPrefix(policy, "money"):
		return "money"
	case strings.HasPrefix(policy, "ratio"):
		return "ratio"
	case strings.HasPrefix(policy, "statistics"):
		return "series"
	default:
		return "mixed"
	}
}

func definitionSources(operationID string) []string {
	if strings.HasPrefix(operationID, "accounting.") || strings.HasPrefix(operationID, "financial.") {
		return []string{"https://www.sec.gov/search-filings/edgar-application-programming-interfaces"}
	}
	if strings.HasPrefix(operationID, "valuation.") || strings.HasPrefix(operationID, "scenario.") {
		return []string{"https://pages.stern.nyu.edu/~adamodar/New_Home_Page/lectures/val.html"}
	}
	if strings.HasPrefix(operationID, "economics.") {
		return []string{"https://fred.stlouisfed.org/docs/api/fred/"}
	}
	return []string{"https://www.sec.gov/search-filings/edgar-application-programming-interfaces"}
}

func reviewOwner(operationID string) string {
	switch {
	case strings.HasPrefix(operationID, "accounting."), strings.HasPrefix(operationID, "financial."):
		return "accounting-and-financial-quality"
	case strings.HasPrefix(operationID, "valuation."), strings.HasPrefix(operationID, "scenario."):
		return "valuation"
	case strings.HasPrefix(operationID, "economics."):
		return "economics-and-transmission"
	default:
		return "market-behavior-and-evidence-critic"
	}
}
