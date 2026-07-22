package numericalcontext

import (
	"fmt"
	"sort"
	"strings"

	"github.com/cockroachdb/apd/v3"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/numeric"
)

const DisplayPolicyVersion = "numerical-display/v1"

func RenderReferences(references []string, contexts []*contracts.NumericalContext) ([]string, error) {
	variables := map[string]contracts.NumericalVariable{}
	relations := map[string]contracts.NumericalRelation{}
	for _, context := range contexts {
		if context == nil {
			continue
		}
		if err := contracts.ValidateNumericalContext(*context); err != nil {
			return nil, err
		}
		for _, variable := range context.Variables {
			if _, duplicate := variables[variable.VariableID]; duplicate {
				return nil, fmt.Errorf("duplicate numerical variable %q across contexts", variable.VariableID)
			}
			variables[variable.VariableID] = variable
		}
		for _, relation := range context.Relations {
			if _, duplicate := relations[relation.RelationID]; duplicate {
				return nil, fmt.Errorf("duplicate numerical relation %q across contexts", relation.RelationID)
			}
			relations[relation.RelationID] = relation
		}
	}
	seen := map[string]bool{}
	result := []string{}
	for _, reference := range references {
		if seen[reference] {
			continue
		}
		seen[reference] = true
		if relation, ok := relations[reference]; ok {
			left, leftOK := variables[relation.LeftVariableID]
			right, rightOK := variables[relation.RightVariableID]
			if !leftOK || !rightOK {
				return nil, fmt.Errorf("relation %q is missing an operand", reference)
			}
			result = append(result, renderRelation(relation, left, right))
			continue
		}
		if variable, ok := variables[reference]; ok {
			result = append(result, renderVariable(variable))
			continue
		}
		return nil, fmt.Errorf("unknown numerical reference %q", reference)
	}
	return result, nil
}

func renderRelation(relation contracts.NumericalRelation, left, right contracts.NumericalVariable) string {
	metric := metricLabel(relation.MetricID)
	if !relation.Comparable {
		warnings := append([]string(nil), relation.Warnings...)
		sort.Strings(warnings)
		return fmt.Sprintf("%s and %s %s were not compared (%s).", entityLabel(left), entityLabel(right), metric, strings.Join(warnings, "; "))
	}
	direction := "equal to"
	switch relation.Operator {
	case contracts.RelationGreaterThan:
		direction = "higher than"
	case contracts.RelationLessThan:
		direction = "lower than"
	}
	leftValue := displayVariableQuantity(left)
	rightValue := displayVariableQuantity(right)
	result := fmt.Sprintf("%s %s was %s, %s %s at %s for %s.", entityLabel(left), metric, leftValue, direction, entityLabel(right), rightValue, periodDescription(left))
	if relation.Operator != contracts.RelationEqual && relation.Difference != nil {
		result = strings.TrimSuffix(result, ".") + fmt.Sprintf(", a deterministic difference of %s.", displayDifference(*relation.Difference, left.Method))
	}
	return result
}

func renderVariable(variable contracts.NumericalVariable) string {
	return fmt.Sprintf("%s %s was %s for %s.", entityLabel(variable), metricLabel(variable.MetricID), displayVariableQuantity(variable), periodDescription(variable))
}

func displayVariableQuantity(variable contracts.NumericalVariable) string {
	if variable.Method == contracts.NormalizationMultiple {
		return decimalRounded(variable.Value.Value, 2) + "x"
	}
	return displayQuantity(variable.Value)
}

func entityLabel(variable contracts.NumericalVariable) string {
	if strings.TrimSpace(variable.EntityLabel) != "" {
		return variable.EntityLabel
	}
	return variable.EntityID
}

func metricLabel(metricID string) string {
	parts := strings.Split(metricID, ".")
	label := parts[len(parts)-1]
	return strings.ReplaceAll(label, "_", " ")
}

func displayQuantity(quantity contracts.Quantity) string {
	switch quantity.Unit {
	case "ratio":
		return decimalPercent(quantity.Value) + "%"
	case "percent":
		return decimalRounded(quantity.Value, 2) + "%"
	case "currency":
		return strings.TrimSpace(quantity.Currency + " " + scaledMoney(quantity.Value))
	case "currency_per_share":
		return strings.TrimSpace(quantity.Currency + " " + decimalRounded(quantity.Value, 2) + " per share")
	case "shares":
		return decimalRounded(quantity.Value, 2) + " shares"
	case "index_point":
		return decimalRounded(quantity.Value, 2) + " index points"
	default:
		return decimalRounded(quantity.Value, 2) + " " + quantity.Unit
	}
}

func scaledMoney(value string) string {
	decimal, _, err := apd.NewFromString(value)
	if err != nil {
		return value
	}
	abs := new(apd.Decimal).Set(decimal)
	if abs.Negative {
		abs.Negative = false
	}
	type scale struct {
		threshold *apd.Decimal
		label     string
	}
	for _, item := range []scale{{apd.New(1, 12), "trillion"}, {apd.New(1, 9), "billion"}, {apd.New(1, 6), "million"}} {
		if abs.Cmp(item.threshold) >= 0 {
			scaled := new(apd.Decimal)
			_, _ = numeric.DecimalContext.Quo(scaled, decimal, item.threshold)
			return decimalRounded(scaled.String(), 2) + " " + item.label
		}
	}
	return decimalRounded(value, 2)
}

func displayDifference(quantity contracts.Quantity, method contracts.NormalizationMethod) string {
	if method == contracts.NormalizationMultiple {
		return decimalRounded(quantity.Value, 2) + "x"
	}
	if quantity.Unit == "ratio" {
		return decimalPercent(quantity.Value) + " percentage points"
	}
	return displayQuantity(quantity)
}

func decimalPercent(value string) string {
	decimal, _, _ := apd.NewFromString(value)
	percentage := new(apd.Decimal)
	_, _ = numeric.DecimalContext.Mul(percentage, decimal, apd.New(100, 0))
	return decimalRounded(percentage.String(), 2)
}

func decimalRounded(value string, places int32) string {
	decimal, _, err := apd.NewFromString(value)
	if err != nil {
		return value
	}
	quantized := new(apd.Decimal)
	if _, err := numeric.DecimalContext.Quantize(quantized, decimal, -places); err != nil {
		return value
	}
	var reduced apd.Decimal
	reduced.Reduce(quantized)
	return reduced.Text('f')
}
