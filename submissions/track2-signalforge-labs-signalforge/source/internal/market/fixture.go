package market

import (
	"context"
	"fmt"
)

type FixtureProvider struct {
	Values map[string][]Bar
}

func (provider FixtureProvider) Bars(_ context.Context, query Query) ([]Bar, error) {
	if err := ValidateQuery(query); err != nil {
		return nil, err
	}
	values, ok := provider.Values[query.Symbol]
	if !ok {
		return nil, fmt.Errorf("fixture has no symbol %s", query.Symbol)
	}
	result := make([]Bar, 0, len(values))
	for _, bar := range values {
		if !bar.Timestamp.Before(query.Start) && bar.Timestamp.Before(query.End) {
			result = append(result, bar)
		}
	}
	return result, nil
}
