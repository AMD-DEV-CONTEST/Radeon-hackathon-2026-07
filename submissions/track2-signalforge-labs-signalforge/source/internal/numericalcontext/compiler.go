package numericalcontext

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/cockroachdb/apd/v3"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/numeric"
)

const relationFormulaVersion = "numerical-relation-decimal/v1"

type Options struct {
	ContextID           string
	RunID               string
	AsOf                time.Time
	EntityNames         map[string]string
	EntityFiscalPeriods map[string]FiscalPeriod
	Tolerance           string
}

type FiscalPeriod struct {
	Start time.Time
	End   time.Time
}

func HasEligibleOutputs(receipts []contracts.CalculationReceipt) bool {
	for _, receipt := range receipts {
		if _, eligible := methodForOperation(receipt.OperationID); !eligible || len(receipt.Scope.CompanyIDs) != 1 {
			continue
		}
		for _, output := range receipt.Outputs {
			if eligibleOutput(receipt.OperationID, output) {
				return true
			}
		}
	}
	return false
}

// Compile turns successful deterministic receipts into an immutable numerical
// context. It deliberately excludes non-scalar and operational outputs.
func Compile(options Options, receipts []contracts.CalculationReceipt) (contracts.NumericalContext, error) {
	if strings.TrimSpace(options.ContextID) == "" || strings.TrimSpace(options.RunID) == "" || options.AsOf.IsZero() {
		return contracts.NumericalContext{}, errors.New("context_id, run_id, and as_of are required")
	}
	context := contracts.NumericalContext{
		SchemaVersion: contracts.SchemaVersionV1,
		ContextID:     options.ContextID,
		RunID:         options.RunID,
		Version:       contracts.NumericalContextVersionV1,
		AsOf:          options.AsOf,
	}
	for _, receipt := range receipts {
		variables, err := variablesFromReceipt(receipt, options)
		if err != nil {
			return contracts.NumericalContext{}, err
		}
		context.Variables = append(context.Variables, variables...)
	}
	if len(context.Variables) == 0 {
		return contracts.NumericalContext{}, errors.New("no eligible scalar numerical outputs")
	}
	context.Relations = compileRelations(context.Variables, options.Tolerance)
	contracts.SortNumericalContext(&context)
	if err := contracts.ValidateNumericalContext(context); err != nil {
		return contracts.NumericalContext{}, err
	}
	return context, nil
}

func variablesFromReceipt(receipt contracts.CalculationReceipt, options Options) ([]contracts.NumericalVariable, error) {
	if err := contracts.ValidateCalculationReceipt(receipt); err != nil {
		return nil, fmt.Errorf("receipt %q: %w", receipt.ReceiptID, err)
	}
	if receipt.Status != contracts.ReceiptSuccess || receipt.SourceAsOf.After(options.AsOf) {
		return nil, fmt.Errorf("receipt %q is unsuccessful or future-dated", receipt.ReceiptID)
	}
	if len(receipt.Scope.CompanyIDs) != 1 {
		return nil, nil
	}
	method, eligible := methodForOperation(receipt.OperationID)
	if !eligible {
		return nil, nil
	}
	entityID := receipt.Scope.CompanyIDs[0]
	period := receiptPeriod(receipt, options.AsOf)
	periodBasis, periodStart, periodEnd, comparisonKey := periodIdentity(receipt.OperationID, entityID, period, options)
	result := make([]contracts.NumericalVariable, 0, len(receipt.Outputs))
	for _, output := range receipt.Outputs {
		if !eligibleOutput(receipt.OperationID, output) {
			continue
		}
		value, err := numeric.ParseDecimal(output.Quantity.Value)
		if err != nil {
			return nil, fmt.Errorf("receipt %q output %q: %w", receipt.ReceiptID, output.OutputID, err)
		}
		quantity := output.Quantity
		quantity.Value = value.String()
		quantity.Period = period
		asOf := receipt.SourceAsOf
		quantity.AsOf = &asOf
		metricID := receipt.OperationID + "." + output.OutputID
		seed := strings.Join([]string{entityID, metricID, period, receipt.ReceiptID}, "\n")
		result = append(result, contracts.NumericalVariable{
			VariableID:     "numvar-" + shortHash(seed),
			EntityID:       entityID,
			EntityLabel:    options.EntityNames[entityID],
			MetricID:       metricID,
			Period:         period,
			PeriodBasis:    periodBasis,
			PeriodStart:    periodStart,
			PeriodEnd:      periodEnd,
			ComparisonKey:  comparisonKey,
			ValueKind:      contracts.NumericalDerivedView,
			Value:          quantity,
			Method:         method,
			FormulaVersion: receipt.FormulaVersion,
			EvidenceRefs:   uniqueSorted(receipt.EvidenceRefs),
			ReceiptRefs:    []string{receipt.ReceiptID},
			Warnings:       uniqueSorted(receipt.Warnings),
			AsOf:           receipt.SourceAsOf,
		})
	}
	return result, nil
}

func periodIdentity(operationID, entityID, period string, options Options) (contracts.NumericalPeriodBasis, *time.Time, *time.Time, string) {
	if strings.HasPrefix(operationID, "financial.") || strings.HasPrefix(operationID, "accounting.") {
		if boundary, ok := options.EntityFiscalPeriods[entityID]; ok && !boundary.Start.IsZero() && boundary.End.After(boundary.Start) {
			start, end := boundary.Start.UTC(), boundary.End.UTC()
			key := "fiscal:" + start.Format("2006-01-02") + ":" + end.Format("2006-01-02")
			return contracts.PeriodBasisFiscalExact, &start, &end, key
		}
	}
	if strings.HasPrefix(operationID, "valuation.") {
		return contracts.PeriodBasisAnalysisAsOf, nil, nil, "analysis-as-of:" + options.AsOf.UTC().Format("2006-01-02T15:04:05Z")
	}
	return contracts.PeriodBasisNominalLabel, nil, nil, "nominal:" + period
}

func methodForOperation(operationID string) (contracts.NormalizationMethod, bool) {
	switch operationID {
	case "financial.revenue_growth", "financial.cagr", "financial.dilution":
		return contracts.NormalizationTemporalGrowth, true
	case "financial.margin", "financial.cash_conversion", "financial.capex_intensity", "financial.roic_proxy", "financial.current_ratio", "financial.debt_to_equity", "financial.quality_of_earnings":
		return contracts.NormalizationCommonSize, true
	case "financial.free_cash_flow", "financial.net_debt", "financial.earnings_per_share", "accounting.balance_sheet_identity":
		return contracts.NormalizationAbsoluteDerived, true
	case "valuation.fcff_dcf", "valuation.reverse_dcf":
		return contracts.NormalizationScenarioOutput, true
	case "valuation.peer_multiple":
		return contracts.NormalizationMultiple, true
	case "market.total_return", "market.volatility", "market.maximum_drawdown", "market.beta", "market.correlation":
		return contracts.NormalizationMarketStatistic, true
	default:
		return "", false
	}
}

func eligibleOutput(operationID string, output contracts.ReceiptOutput) bool {
	if output.Status != "derived" {
		return false
	}
	// DCF present-value vectors and terminal components remain available in the immutable receipt
	// for audit, but only the registered decision output enters semantic comparison and prose.
	switch operationID {
	case "valuation.fcff_dcf":
		if output.OutputID != "enterprise_value" {
			return false
		}
	case "valuation.reverse_dcf":
		if output.OutputID != "implied_growth" {
			return false
		}
	}
	switch output.Quantity.Unit {
	case "currency", "currency_per_share", "ratio", "percent", "shares", "index_point":
	default:
		return false
	}
	_, err := numeric.ParseDecimal(output.Quantity.Value)
	return err == nil
}

func receiptPeriod(receipt contracts.CalculationReceipt, asOf time.Time) string {
	periods := make(map[string]bool)
	for _, output := range receipt.Outputs {
		if output.Quantity.Period != "" {
			periods[output.Quantity.Period] = true
		}
	}
	if len(periods) == 0 {
		for _, input := range receipt.NormalizedInputs {
			if input.Quantity.Period != "" {
				periods[input.Quantity.Period] = true
			}
		}
	}
	values := make([]string, 0, len(periods))
	for period := range periods {
		values = append(values, period)
	}
	sort.Strings(values)
	if len(values) == 0 {
		return "as_of:" + asOf.Format("2006-01-02")
	}
	return compactPeriods(values)
}

func compactPeriods(values []string) string {
	years := make([]int, len(values))
	for index, value := range values {
		if _, err := fmt.Sscanf(value, "FY%d", &years[index]); err != nil {
			return strings.Join(values, "..")
		}
	}
	for index := 1; index < len(years); index++ {
		if years[index] != years[index-1]+1 {
			return strings.Join(values, "..")
		}
	}
	if len(values) == 1 {
		return values[0]
	}
	return values[0] + "-" + values[len(values)-1]
}

func compileRelations(variables []contracts.NumericalVariable, tolerance string) []contracts.NumericalRelation {
	groups := make(map[string][]contracts.NumericalVariable)
	for _, variable := range variables {
		groups[variable.MetricID] = append(groups[variable.MetricID], variable)
	}
	if strings.TrimSpace(tolerance) == "" {
		tolerance = "0"
	}
	result := []contracts.NumericalRelation{}
	for _, group := range groups {
		sort.Slice(group, func(i, j int) bool { return group[i].VariableID < group[j].VariableID })
		for leftIndex := 0; leftIndex < len(group); leftIndex++ {
			for rightIndex := leftIndex + 1; rightIndex < len(group); rightIndex++ {
				left, right := group[leftIndex], group[rightIndex]
				if left.EntityID == right.EntityID {
					continue
				}
				relation := relationForPair(left, right, tolerance)
				result = append(result, relation)
			}
		}
	}
	return result
}

func relationForPair(left, right contracts.NumericalVariable, tolerance string) contracts.NumericalRelation {
	seed := strings.Join([]string{left.VariableID, right.VariableID, relationFormulaVersion}, "\n")
	relation := contracts.NumericalRelation{
		RelationID:      "numrel-" + shortHash(seed),
		MetricID:        left.MetricID,
		LeftVariableID:  left.VariableID,
		RightVariableID: right.VariableID,
		Tolerance:       tolerance,
		FormulaVersion:  relationFormulaVersion,
		EvidenceRefs:    uniqueSorted(append(append([]string(nil), left.EvidenceRefs...), right.EvidenceRefs...)),
		ReceiptRefs:     uniqueSorted(append(append([]string(nil), left.ReceiptRefs...), right.ReceiptRefs...)),
	}
	if !contracts.NumericalVariablesComparable(left, right) {
		relation.Operator = contracts.RelationIncomparable
		relation.Comparable = false
		relation.Warnings = []string{incomparabilityWarning(left, right)}
		return relation
	}
	leftValue, _, _ := apd.NewFromString(left.Value.Value)
	rightValue, _, _ := apd.NewFromString(right.Value.Value)
	difference := new(apd.Decimal)
	_, _ = apd.BaseContext.Sub(difference, leftValue, rightValue)
	if difference.Negative {
		difference.Negative = false
	}
	canonical, _ := numeric.ParseDecimal(difference.String())
	relation.Difference = &contracts.Quantity{Value: canonical.String(), Unit: left.Value.Unit, Currency: left.Value.Currency}
	relation.Comparable = true
	toleranceValue, _, _ := apd.NewFromString(tolerance)
	if difference.Cmp(toleranceValue) <= 0 {
		relation.Operator = contracts.RelationEqual
	} else if leftValue.Cmp(rightValue) > 0 {
		relation.Operator = contracts.RelationGreaterThan
	} else {
		relation.Operator = contracts.RelationLessThan
	}
	return relation
}

func incomparabilityWarning(left, right contracts.NumericalVariable) string {
	if left.Value.Unit != right.Value.Unit || left.Value.Currency != right.Value.Currency {
		return "unit or currency differs; no direction was released"
	}
	return fmt.Sprintf("period identity differs: %s versus %s; no direction was released", periodDescription(left), periodDescription(right))
}

func periodDescription(variable contracts.NumericalVariable) string {
	if variable.PeriodBasis == contracts.PeriodBasisFiscalExact && variable.PeriodStart != nil && variable.PeriodEnd != nil {
		return fmt.Sprintf("%s %s to %s", variable.Period, variable.PeriodStart.Format("2006-01-02"), variable.PeriodEnd.Format("2006-01-02"))
	}
	if variable.PeriodBasis == contracts.PeriodBasisAnalysisAsOf {
		return fmt.Sprintf("%s as of %s", variable.Period, variable.AsOf.Format("2006-01-02"))
	}
	return variable.Period
}

func uniqueSorted(values []string) []string {
	set := make(map[string]bool, len(values))
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			set[value] = true
		}
	}
	result := make([]string, 0, len(set))
	for value := range set {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}

func shortHash(value string) string {
	digest := sha256.Sum256([]byte(value))
	return hex.EncodeToString(digest[:10])
}
