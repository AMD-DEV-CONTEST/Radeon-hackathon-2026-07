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

func TestCitationHostsCanBeInjectedWithoutBroadeningTheDefault(t *testing.T) {
	now := time.Now().UTC()
	chunk := fixtureChunk("apple-ir", "sec-cik:0000320193", "Strategy", "Official investor evidence.", now)
	chunk.EvidenceType = "investor_relations"
	chunk.FilingID = ""
	chunk.AccessionNumber = ""
	chunk.FormType = ""
	chunk.DocumentType = "official_strategy_or_risk_update"
	chunk.AuthorityTier = "C"
	chunk.Audited = false
	chunk.FiledWithSEC = false
	chunk.SourceURI = "https://investor.apple.com/investor-relations/default.aspx"
	resolver, err := NewResolverWithAllowedHosts([]Chunk{chunk}, []string{"investor.apple.com"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := resolver.OpenTarget(chunk.ChunkID, now.Unix()); err != nil {
		t.Fatalf("issuer-specific host should resolve: %v", err)
	}
	if _, err := NewResolverWithAllowedHosts([]Chunk{chunk}, []string{"apple.com.attacker.test/path"}); err == nil {
		t.Fatal("host definitions with path syntax must fail closed")
	}
}

func TestCitationSharedHostIsBoundToIssuerPrefix(t *testing.T) {
	now := time.Now().UTC()
	chunk := fixtureChunk("amd-deck", "sec-cik:0000002488", "Strategy", "Official investor evidence.", now)
	chunk.EvidenceType = "investor_relations"
	chunk.FilingID = ""
	chunk.AccessionNumber = ""
	chunk.FormType = ""
	chunk.DocumentType = "investor_presentation"
	chunk.AuthorityTier = "C"
	chunk.SourceURI = "https://d1io3yog0oux5.cloudfront.net/_cece5bf914638d0ab16f558d26342d35/amd/deck.pdf"
	resolver, err := NewResolverWithPolicy(
		[]Chunk{chunk},
		[]string{"d1io3yog0oux5.cloudfront.net"},
		map[string][]string{"d1io3yog0oux5.cloudfront.net": {"https://d1io3yog0oux5.cloudfront.net/_cece5bf914638d0ab16f558d26342d35/amd/"}},
	)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := resolver.OpenTarget(chunk.ChunkID, now.Unix()); err != nil {
		t.Fatalf("issuer-owned path should resolve: %v", err)
	}

	chunk.SourceURI = "https://d1io3yog0oux5.cloudfront.net/_3db86d29d2361a15e461e3b4de61f31a/intel/deck.pdf"
	otherIssuer, err := NewResolverWithPolicy(
		[]Chunk{chunk},
		[]string{"d1io3yog0oux5.cloudfront.net"},
		map[string][]string{"d1io3yog0oux5.cloudfront.net": {"https://d1io3yog0oux5.cloudfront.net/_cece5bf914638d0ab16f558d26342d35/amd/"}},
	)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := otherIssuer.OpenTarget(chunk.ChunkID, now.Unix()); err == nil {
		t.Fatal("another issuer path on the shared host must fail closed")
	}
}
