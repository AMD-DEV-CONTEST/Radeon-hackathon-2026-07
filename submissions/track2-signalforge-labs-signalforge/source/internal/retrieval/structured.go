package retrieval

import (
	"errors"
	"sort"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/data"
	"github.com/rvbernucci/signalforge/internal/engine"
)

type StructuredReference struct {
	ReferenceID  string    `json:"reference_id"`
	Kind         string    `json:"kind"`
	CompanyID    string    `json:"company_id,omitempty"`
	PeriodEnd    time.Time `json:"period_end,omitempty"`
	AsOf         time.Time `json:"as_of"`
	Value        string    `json:"value,omitempty"`
	Unit         string    `json:"unit,omitempty"`
	ReceiptSHA   string    `json:"receipt_sha256,omitempty"`
	EvidenceRefs []string  `json:"evidence_refs,omitempty"`
}

type StructuredResolver struct {
	metrics  map[string]data.NormalizedMetric
	receipts *engine.ReceiptStore
}

func NewStructuredResolver(metrics []data.NormalizedMetric, receipts *engine.ReceiptStore) (*StructuredResolver, error) {
	resolver := &StructuredResolver{metrics: make(map[string]data.NormalizedMetric, len(metrics)), receipts: receipts}
	for _, metric := range metrics {
		if err := data.ValidateNormalizedMetric(metric); err != nil {
			return nil, err
		}
		if _, duplicate := resolver.metrics[metric.MetricID]; duplicate {
			return nil, errors.New("duplicate normalized metric ID")
		}
		resolver.metrics[metric.MetricID] = metric
	}
	return resolver, nil
}

func (resolver *StructuredResolver) ResolveMetric(metricID string, asOf time.Time) (StructuredReference, error) {
	metric, ok := resolver.metrics[metricID]
	if !ok {
		return StructuredReference{}, errors.New("normalized metric does not resolve")
	}
	if asOf.IsZero() || metric.SourceAvailableAt.After(asOf) {
		return StructuredReference{}, errors.New("normalized metric is unavailable at requested time")
	}
	refs := append([]string(nil), metric.SourceFactIDs...)
	sort.Strings(refs)
	return StructuredReference{
		ReferenceID: metric.MetricID, Kind: "normalized_metric", CompanyID: metric.CompanyID,
		PeriodEnd: metric.PeriodEnd, AsOf: metric.SourceAvailableAt, Value: metric.Value,
		Unit: metric.Unit, EvidenceRefs: refs,
	}, nil
}

func (resolver *StructuredResolver) ResolveReceipt(receiptSHA string, asOf time.Time) (StructuredReference, error) {
	if resolver.receipts == nil {
		return StructuredReference{}, errors.New("calculation receipt store is unavailable")
	}
	receipt, err := resolver.receipts.Load(receiptSHA)
	if err != nil {
		return StructuredReference{}, err
	}
	if asOf.IsZero() || receipt.SourceAsOf.After(asOf) {
		return StructuredReference{}, errors.New("calculation receipt is unavailable at requested time")
	}
	if receipt.Status != contracts.ReceiptSuccess {
		return StructuredReference{}, errors.New("only successful calculation receipts can be resolved")
	}
	refs := append([]string(nil), receipt.EvidenceRefs...)
	sort.Strings(refs)
	return StructuredReference{
		ReferenceID: receipt.ReceiptID, Kind: "calculation_receipt", AsOf: receipt.SourceAsOf,
		ReceiptSHA: receipt.ReceiptSHA, EvidenceRefs: refs,
	}, nil
}
