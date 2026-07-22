package finance

import (
	"errors"
	"fmt"

	"github.com/cockroachdb/apd/v3"
	"github.com/rvbernucci/signalforge/internal/numeric"
)

var errDivisionByZero = errors.New("division by zero")

func raw(value numeric.Decimal) (*apd.Decimal, error) {
	parsed, _, err := apd.NewFromString(value.String())
	if err != nil {
		return nil, fmt.Errorf("parse canonical decimal: %w", err)
	}
	return parsed, nil
}

func canonical(value *apd.Decimal) (numeric.Decimal, error) {
	return numeric.ParseDecimal(value.String())
}

func binary(left, right numeric.Decimal, operation func(*apd.Decimal, *apd.Decimal, *apd.Decimal) (apd.Condition, error)) (numeric.Decimal, error) {
	x, err := raw(left)
	if err != nil {
		return numeric.Decimal{}, err
	}
	y, err := raw(right)
	if err != nil {
		return numeric.Decimal{}, err
	}
	var result apd.Decimal
	if _, err := operation(&result, x, y); err != nil {
		return numeric.Decimal{}, err
	}
	return canonical(&result)
}

func add(left, right numeric.Decimal) (numeric.Decimal, error) {
	return binary(left, right, numeric.DecimalContext.Add)
}

func subtract(left, right numeric.Decimal) (numeric.Decimal, error) {
	return binary(left, right, numeric.DecimalContext.Sub)
}

func multiply(left, right numeric.Decimal) (numeric.Decimal, error) {
	return binary(left, right, numeric.DecimalContext.Mul)
}

func divide(left, right numeric.Decimal) (numeric.Decimal, error) {
	if right.String() == "0" {
		return numeric.Decimal{}, errDivisionByZero
	}
	return binary(left, right, numeric.DecimalContext.Quo)
}

func power(base, exponent numeric.Decimal) (numeric.Decimal, error) {
	return binary(base, exponent, numeric.DecimalContext.Pow)
}

func negate(value numeric.Decimal) (numeric.Decimal, error) {
	x, err := raw(value)
	if err != nil {
		return numeric.Decimal{}, err
	}
	var result apd.Decimal
	if _, err := numeric.DecimalContext.Neg(&result, x); err != nil {
		return numeric.Decimal{}, err
	}
	return canonical(&result)
}

func absolute(value numeric.Decimal) (numeric.Decimal, error) {
	x, err := raw(value)
	if err != nil {
		return numeric.Decimal{}, err
	}
	var result apd.Decimal
	if _, err := numeric.DecimalContext.Abs(&result, x); err != nil {
		return numeric.Decimal{}, err
	}
	return canonical(&result)
}

func compare(left, right numeric.Decimal) (int, error) {
	x, err := raw(left)
	if err != nil {
		return 0, err
	}
	y, err := raw(right)
	if err != nil {
		return 0, err
	}
	return x.Cmp(y), nil
}

func ratio(numerator, denominator numeric.Decimal) (numeric.Decimal, error) {
	if denominator.String() == "0" {
		return numeric.Decimal{}, errDivisionByZero
	}
	return divide(numerator, denominator)
}
