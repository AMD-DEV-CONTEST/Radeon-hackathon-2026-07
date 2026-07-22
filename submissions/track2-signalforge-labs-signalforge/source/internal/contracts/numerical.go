package contracts

import (
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/cockroachdb/apd/v3"
)

const NumericalContextVersionV1 = "numerical-silence/v1"

type NumericalValueKind string

type NumericalPeriodBasis string

const (
	NumericalActual      NumericalValueKind = "actual"
	NumericalDerivedView NumericalValueKind = "derived_view"

	PeriodBasisFiscalExact  NumericalPeriodBasis = "fiscal_period_exact"
	PeriodBasisAnalysisAsOf NumericalPeriodBasis = "analysis_as_of"
	PeriodBasisNominalLabel NumericalPeriodBasis = "nominal_label"
)

type NormalizationMethod string

const (
	NormalizationNone            NormalizationMethod = "none"
	NormalizationCommonSize      NormalizationMethod = "common_size"
	NormalizationTemporalGrowth  NormalizationMethod = "temporal_growth"
	NormalizationCAGR            NormalizationMethod = "cagr"
	NormalizationIndexBase100    NormalizationMethod = "index_base_100"
	NormalizationPeerPercentile  NormalizationMethod = "peer_percentile"
	NormalizationZScore          NormalizationMethod = "z_score"
	NormalizationScenarioOutput  NormalizationMethod = "scenario_output"
	NormalizationMarketStatistic NormalizationMethod = "market_statistic"
	NormalizationMultiple        NormalizationMethod = "multiple"
	NormalizationAbsoluteDerived NormalizationMethod = "absolute_derived"
)

type RelationOperator string

const (
	RelationGreaterThan  RelationOperator = "greater_than"
	RelationLessThan     RelationOperator = "less_than"
	RelationEqual        RelationOperator = "equal_within_tolerance"
	RelationIncomparable RelationOperator = "incomparable"
)

type NumericalVariable struct {
	VariableID     string               `json:"variable_id"`
	EntityID       string               `json:"entity_id"`
	EntityLabel    string               `json:"entity_label,omitempty"`
	MetricID       string               `json:"metric_id"`
	Period         string               `json:"period"`
	PeriodBasis    NumericalPeriodBasis `json:"period_basis"`
	PeriodStart    *time.Time           `json:"period_start,omitempty"`
	PeriodEnd      *time.Time           `json:"period_end,omitempty"`
	ComparisonKey  string               `json:"comparison_key"`
	ValueKind      NumericalValueKind   `json:"value_kind"`
	Value          Quantity             `json:"value"`
	Method         NormalizationMethod  `json:"method"`
	FormulaVersion string               `json:"formula_version,omitempty"`
	BaselineRefs   []string             `json:"baseline_refs,omitempty"`
	CohortID       string               `json:"cohort_id,omitempty"`
	EvidenceRefs   []string             `json:"evidence_refs,omitempty"`
	ReceiptRefs    []string             `json:"receipt_refs,omitempty"`
	Warnings       []string             `json:"warnings,omitempty"`
	AsOf           time.Time            `json:"as_of"`
}

type NumericalRelation struct {
	RelationID      string           `json:"relation_id"`
	MetricID        string           `json:"metric_id"`
	LeftVariableID  string           `json:"left_variable_id"`
	Operator        RelationOperator `json:"operator"`
	RightVariableID string           `json:"right_variable_id"`
	Difference      *Quantity        `json:"difference,omitempty"`
	Tolerance       string           `json:"tolerance"`
	Comparable      bool             `json:"comparable"`
	FormulaVersion  string           `json:"formula_version"`
	EvidenceRefs    []string         `json:"evidence_refs,omitempty"`
	ReceiptRefs     []string         `json:"receipt_refs,omitempty"`
	Warnings        []string         `json:"warnings,omitempty"`
}

type NumericalContext struct {
	SchemaVersion string              `json:"schema_version"`
	ContextID     string              `json:"context_id"`
	RunID         string              `json:"run_id"`
	Version       string              `json:"version"`
	AsOf          time.Time           `json:"as_of"`
	Variables     []NumericalVariable `json:"variables"`
	Relations     []NumericalRelation `json:"relations,omitempty"`
}

func ValidateNumericalContext(context NumericalContext) error {
	if err := validateEnvelope(context.SchemaVersion, context.ContextID, context.RunID); err != nil {
		return err
	}
	if context.Version != NumericalContextVersionV1 || context.AsOf.IsZero() || len(context.Variables) == 0 {
		return errors.New("numerical context requires version, as_of, and variables")
	}
	variables := make(map[string]NumericalVariable, len(context.Variables))
	for index, variable := range context.Variables {
		if err := validateNumericalVariable(variable, context.AsOf); err != nil {
			return fmt.Errorf("variables[%d]: %w", index, err)
		}
		if _, duplicate := variables[variable.VariableID]; duplicate {
			return fmt.Errorf("variables[%d] duplicates %q", index, variable.VariableID)
		}
		variables[variable.VariableID] = variable
	}
	for index, variable := range context.Variables {
		for _, reference := range variable.BaselineRefs {
			if _, exists := variables[reference]; !exists {
				return fmt.Errorf("variables[%d] references unknown baseline %q", index, reference)
			}
		}
	}
	relations := make(map[string]bool, len(context.Relations))
	for index, relation := range context.Relations {
		if relations[relation.RelationID] {
			return fmt.Errorf("relations[%d] duplicates %q", index, relation.RelationID)
		}
		relations[relation.RelationID] = true
		if err := validateNumericalRelation(relation, variables); err != nil {
			return fmt.Errorf("relations[%d]: %w", index, err)
		}
	}
	return nil
}

func validateNumericalVariable(variable NumericalVariable, contextAsOf time.Time) error {
	if variable.VariableID == "" || variable.EntityID == "" || variable.MetricID == "" || variable.Period == "" || variable.ComparisonKey == "" || variable.AsOf.IsZero() {
		return errors.New("variable_id, entity_id, metric_id, period, comparison_key, and as_of are required")
	}
	if variable.AsOf.After(contextAsOf) || (variable.Value.AsOf != nil && variable.Value.AsOf.After(contextAsOf)) {
		return errors.New("numerical variable leaks information after context as_of")
	}
	switch variable.PeriodBasis {
	case PeriodBasisFiscalExact:
		if variable.PeriodStart == nil || variable.PeriodEnd == nil || !variable.PeriodEnd.After(*variable.PeriodStart) || variable.PeriodEnd.After(contextAsOf) {
			return errors.New("exact fiscal period requires valid non-future start and end")
		}
	case PeriodBasisAnalysisAsOf, PeriodBasisNominalLabel:
		if variable.PeriodStart != nil || variable.PeriodEnd != nil {
			return errors.New("non-fiscal period basis cannot carry exact fiscal boundaries")
		}
	default:
		return fmt.Errorf("unsupported numerical period basis %q", variable.PeriodBasis)
	}
	value, _, err := apd.NewFromString(variable.Value.Value)
	if err != nil || value.Form != apd.Finite || variable.Value.Unit == "" {
		return errors.New("numerical variable requires a finite decimal value and unit")
	}
	if variable.ValueKind == NumericalActual {
		if variable.Method != NormalizationNone || len(variable.EvidenceRefs) == 0 {
			return errors.New("actual variable requires method none and evidence_refs")
		}
		return nil
	}
	if variable.ValueKind != NumericalDerivedView || !validNormalizationMethod(variable.Method) || variable.Method == NormalizationNone {
		return errors.New("derived variable requires an allowed normalization method")
	}
	if variable.FormulaVersion == "" || len(variable.ReceiptRefs) == 0 {
		return errors.New("derived variable requires formula_version and receipt_refs")
	}
	if variable.Method == NormalizationIndexBase100 && len(variable.BaselineRefs) == 0 {
		return errors.New("index-base-100 variable requires baseline_refs")
	}
	if (variable.Method == NormalizationPeerPercentile || variable.Method == NormalizationZScore) && variable.CohortID == "" {
		return errors.New("peer-normalized variable requires cohort_id")
	}
	return nil
}

func validNormalizationMethod(method NormalizationMethod) bool {
	switch method {
	case NormalizationNone, NormalizationCommonSize, NormalizationTemporalGrowth, NormalizationCAGR,
		NormalizationIndexBase100, NormalizationPeerPercentile, NormalizationZScore,
		NormalizationScenarioOutput, NormalizationMarketStatistic, NormalizationMultiple,
		NormalizationAbsoluteDerived:
		return true
	default:
		return false
	}
}

func validateNumericalRelation(relation NumericalRelation, variables map[string]NumericalVariable) error {
	if relation.RelationID == "" || relation.MetricID == "" || relation.LeftVariableID == "" || relation.RightVariableID == "" || relation.FormulaVersion == "" {
		return errors.New("relation identity and formula_version are required")
	}
	if relation.LeftVariableID == relation.RightVariableID {
		return errors.New("relation requires two distinct variables")
	}
	left, leftOK := variables[relation.LeftVariableID]
	right, rightOK := variables[relation.RightVariableID]
	if !leftOK || !rightOK {
		return errors.New("relation references an unknown variable")
	}
	if relation.MetricID != left.MetricID || relation.MetricID != right.MetricID {
		return errors.New("relation metric differs from variable metrics")
	}
	compatible := NumericalVariablesComparable(left, right)
	if !relation.Comparable {
		if relation.Operator != RelationIncomparable || compatible || len(relation.Warnings) == 0 || relation.Difference != nil {
			return errors.New("incomparable relation requires incompatibility, warning, and no difference")
		}
		return nil
	}
	if !compatible || relation.Operator == RelationIncomparable || relation.Difference == nil || len(relation.ReceiptRefs) == 0 {
		return errors.New("comparable relation requires compatible variables, operator, difference, and receipts")
	}
	leftValue, _, _ := apd.NewFromString(left.Value.Value)
	rightValue, _, _ := apd.NewFromString(right.Value.Value)
	tolerance, _, err := apd.NewFromString(defaultTolerance(relation.Tolerance))
	if err != nil || tolerance.Form != apd.Finite || tolerance.Negative {
		return errors.New("relation tolerance must be a non-negative decimal")
	}
	difference := new(apd.Decimal)
	_, _ = apd.BaseContext.Sub(difference, leftValue, rightValue)
	if difference.Negative {
		difference.Negative = false
	}
	recordedDifference, _, err := apd.NewFromString(relation.Difference.Value)
	if err != nil || recordedDifference.Cmp(difference) != 0 || relation.Difference.Unit != left.Value.Unit || relation.Difference.Currency != left.Value.Currency {
		return errors.New("relation difference does not match the underlying values")
	}
	order := leftValue.Cmp(rightValue)
	if difference.Cmp(tolerance) <= 0 {
		order = 0
	}
	expected := RelationEqual
	if order > 0 {
		expected = RelationGreaterThan
	} else if order < 0 {
		expected = RelationLessThan
	}
	if relation.Operator != expected {
		return fmt.Errorf("relation operator %q contradicts recomputed operator %q", relation.Operator, expected)
	}
	return nil
}

func NumericalVariablesComparable(left, right NumericalVariable) bool {
	return left.Value.Unit == right.Value.Unit &&
		left.Value.Currency == right.Value.Currency &&
		left.PeriodBasis == right.PeriodBasis &&
		left.ComparisonKey == right.ComparisonKey
}

func defaultTolerance(value string) string {
	if strings.TrimSpace(value) == "" {
		return "0"
	}
	return value
}

func SortNumericalContext(context *NumericalContext) {
	sort.Slice(context.Variables, func(i, j int) bool { return context.Variables[i].VariableID < context.Variables[j].VariableID })
	sort.Slice(context.Relations, func(i, j int) bool { return context.Relations[i].RelationID < context.Relations[j].RelationID })
}
