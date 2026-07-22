package golden

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"strings"
	"time"
)

const GoldenPriceSetSchemaV1 = "signalforge/golden-price-set/v1"

type PriceSet struct {
	SchemaVersion string       `json:"schema_version"`
	DatasetID     string       `json:"dataset_id"`
	RetrievedAt   time.Time    `json:"retrieved_at"`
	Prices        []PriceInput `json:"prices"`
}

func LoadPriceSet(path string) (PriceSet, error) {
	payload, err := os.ReadFile(path)
	if err != nil {
		return PriceSet{}, err
	}
	var set PriceSet
	if err := json.Unmarshal(payload, &set); err != nil {
		return PriceSet{}, fmt.Errorf("decode golden price set: %w", err)
	}
	if err := ValidatePriceSet(set); err != nil {
		return PriceSet{}, err
	}
	return set, nil
}

func ValidatePriceSet(set PriceSet) error {
	if set.SchemaVersion != GoldenPriceSetSchemaV1 || strings.TrimSpace(set.DatasetID) == "" || set.RetrievedAt.IsZero() {
		return errors.New("golden price set envelope is invalid")
	}
	if len(set.Prices) < 2 {
		return errors.New("golden price set requires at least two securities")
	}
	seen := map[string]bool{}
	for index, price := range set.Prices {
		ticker := strings.ToUpper(strings.TrimSpace(price.Ticker))
		if ticker == "" || seen[ticker] || price.AsOf.IsZero() || price.AsOf.After(set.RetrievedAt) || !shaPattern.MatchString(price.SourceSHA) {
			return fmt.Errorf("prices[%d] has invalid identity, time, or source hash", index)
		}
		parsed, err := url.Parse(price.Source)
		if err != nil || parsed.Scheme != "https" || parsed.Host != "api.nasdaq.com" {
			return fmt.Errorf("prices[%d] must cite the frozen official Nasdaq endpoint", index)
		}
		seen[ticker] = true
	}
	return nil
}
