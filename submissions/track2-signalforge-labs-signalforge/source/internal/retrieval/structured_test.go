package retrieval

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/data"
	"github.com/rvbernucci/signalforge/internal/engine"
)

func TestStructuredMetricAndReceiptResolveWithoutEmbeddings(t *testing.T) {
	asOf := time.Date(2026, 7, 21, 18, 30, 0, 0, time.UTC)
	metric := data.NormalizedMetric{
		MetricID: "metric-msft-revenue-fy2025", CompanyID: "sec-cik:0000789019",
		CanonicalMetric: "revenue", PeriodStart: time.Date(2024, 7, 1, 0, 0, 0, 0, time.UTC),
		PeriodEnd: time.Date(2025, 6, 30, 0, 0, 0, 0, time.UTC), PeriodType: "annual",
		Value: "281724000000", Unit: "currency", Currency: "USD", SourceFactIDs: []string{"fact-revenue"},
		TransformationID: "identity", NormalizationPolicy: "sec-us-gaap/v1", ComparabilityStatus: "reported",
		SourceAvailableAt: asOf.Add(-2 * time.Hour), ComputedAt: asOf.Add(-time.Hour),
	}
	store, err := engine.NewReceiptStore(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	payload, err := os.ReadFile(filepath.Join("..", "..", "fixtures", "engine", "margin-request.json"))
	if err != nil {
		t.Fatal(err)
	}
	var request contracts.EngineRequest
	if err := json.Unmarshal(payload, &request); err != nil {
		t.Fatal(err)
	}
	executor, _ := engine.New("structured-resolver-test")
	result := executor.Execute(request)
	if result.Receipt == nil {
		t.Fatalf("fixture execution failed: %+v", result.Failure)
	}
	if _, err := store.Save(*result.Receipt); err != nil {
		t.Fatal(err)
	}

	resolver, err := NewStructuredResolver([]data.NormalizedMetric{metric}, store)
	if err != nil {
		t.Fatal(err)
	}
	metricRef, err := resolver.ResolveMetric(metric.MetricID, asOf)
	if err != nil || metricRef.Value != metric.Value || metricRef.Kind != "normalized_metric" {
		t.Fatalf("invalid metric reference %+v: %v", metricRef, err)
	}
	receiptRef, err := resolver.ResolveReceipt(result.Receipt.ReceiptSHA, asOf.Add(time.Hour))
	if err != nil || receiptRef.ReceiptSHA != result.Receipt.ReceiptSHA || receiptRef.Kind != "calculation_receipt" {
		t.Fatalf("invalid receipt reference %+v: %v", receiptRef, err)
	}
	if _, err := resolver.ResolveMetric(metric.MetricID, metric.SourceAvailableAt.Add(-time.Second)); err == nil {
		t.Fatal("future metric must fail closed")
	}
}

func TestCitationOpenTargetIsAllowlistedAndPointInTime(t *testing.T) {
	eval, chunks, err := LoadEvalSet(filepath.Join("..", "..", "fixtures", "retrieval", "golden-eval.json"))
	if err != nil {
		t.Fatal(err)
	}
	resolver, _ := NewResolver(chunks)
	target, err := resolver.OpenTarget("nvda-export-controls", eval.AsOf.Unix())
	if err != nil || target.SourceURI == "" || target.Locator != "export-controls" || target.Page != 28 {
		t.Fatalf("invalid open target %+v: %v", target, err)
	}
	tampered := chunks[0]
	tampered.ChunkID = "untrusted"
	tampered.SourceURI = "https://example.net/filing"
	untrusted, _ := NewResolver([]Chunk{tampered})
	if _, err := untrusted.OpenTarget("untrusted", eval.AsOf.Unix()); err == nil {
		t.Fatal("untrusted citation host must fail closed")
	}
}
