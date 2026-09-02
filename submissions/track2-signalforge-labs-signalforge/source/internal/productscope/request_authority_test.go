package productscope

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/requestparser"
)

func TestRequestAuthorityBindsCompanyAndComparisonReceipts(t *testing.T) {
	catalog := loadPublicCatalogFixture(t)
	peers := loadPeerEvaluationFixture(t)
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Compare Microsoft and Alphabet on operating margin and cash conversion.",
		AsOf: catalog.AsOf, RunID: "run-authority", RequestID: "request-authority",
	})
	if err != nil {
		t.Fatal(err)
	}
	bound, err := BindRequestAuthority(request, catalog, peers)
	if err != nil {
		t.Fatal(err)
	}
	if bound.AuthorityState != "limited" || len(bound.AuthorityRefs) < 4 {
		t.Fatalf("authority was not bound: %+v", bound)
	}
}

func TestRequestAuthorityRejectsUnknownPairWithoutInventingLane(t *testing.T) {
	catalog := loadPublicCatalogFixture(t)
	peers := loadPeerEvaluationFixture(t)
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text:  "Compare Apple and Adobe as long-term businesses.",
		AsOf:  time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC),
		RunID: "run-unknown-pair", RequestID: "request-unknown-pair",
	})
	if err != nil {
		t.Fatal(err)
	}
	bound, err := BindRequestAuthority(request, catalog, peers)
	if err != nil {
		t.Fatal(err)
	}
	if bound.AuthorityState != "limited" || !containsString(bound.AuthorityReasonCodes, "peer_lane_not_defined") {
		t.Fatalf("undefined pair was over-promoted: %+v", bound)
	}
}

func loadPeerEvaluationFixture(t *testing.T) PeerEvaluationSuite {
	t.Helper()
	payload, err := os.ReadFile(filepath.Join("..", "..", "fixtures", "productscope", "technology20-peer-evaluation.json"))
	if err != nil {
		t.Fatal(err)
	}
	var result PeerEvaluationSuite
	if err := json.Unmarshal(payload, &result); err != nil {
		t.Fatal(err)
	}
	return result
}

func containsString(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
