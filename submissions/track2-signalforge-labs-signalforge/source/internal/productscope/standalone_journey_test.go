package productscope

import (
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"testing"

	"github.com/rvbernucci/signalforge/internal/planner"
	"github.com/rvbernucci/signalforge/internal/requestparser"
)

func TestStandaloneJourneyPopulationIsBalancedAndAuthorityBound(t *testing.T) {
	catalog := loadPublicCatalogFixture(t)
	financials := loadPublicFinancialSummaryFixture(t)
	development, sealed, err := BuildStandaloneJourneySuites(catalog, financials)
	if err != nil {
		t.Fatal(err)
	}
	if len(development.Cases) != 80 || len(sealed.Cases) != 40 {
		t.Fatalf("population = %d development / %d sealed", len(development.Cases), len(sealed.Cases))
	}
	for _, item := range append(development.Cases, sealed.Cases...) {
		if item.ExpectedReceipts == nil || item.ExpectedAbstentions == nil {
			t.Fatalf("authority outcomes must serialize as arrays: %+v", item)
		}
		if item.QuestionID == "valuation-macro" && item.ExpectedDisposition != "typed_abstention" {
			t.Fatalf("valuation was released without price/macro authority: %+v", item)
		}
	}
}

func TestStandaloneDevelopmentAugmentationIsBalancedAndDoesNotContainSealedCases(t *testing.T) {
	catalog := loadPublicCatalogFixture(t)
	financials := loadPublicFinancialSummaryFixture(t)
	suite, err := BuildStandaloneDevelopmentAugmentationSuite(catalog, financials)
	if err != nil {
		t.Fatal(err)
	}
	if suite.Split != StandaloneAugmentationSplit || len(suite.Cases) != 60 {
		t.Fatalf("augmentation = split %q / %d cases", suite.Split, len(suite.Cases))
	}
	counts := map[string]int{}
	for _, item := range suite.Cases {
		counts[item.QuestionID]++
		if item.QuestionID == "business-model" || item.QuestionID == "valuation-macro" {
			t.Fatalf("sealed case leaked into development augmentation: %+v", item)
		}
		if item.ExpectedDisposition != "typed_abstention" ||
			len(item.ExpectedReceipts) != 0 ||
			len(item.ExpectedAbstentions) == 0 {
			t.Fatalf("unsupported augmentation authority was not fail-closed: %+v", item)
		}
		switch item.QuestionID {
		case "economics-transmission":
			if !slices.Contains(item.RequiredDomains, "economics") ||
				!slices.Equal(item.ExpectedAbstentions, []string{"economics.yield_curve"}) {
				t.Fatalf("economics contract = %+v", item)
			}
		case "valuation-readiness":
			if !slices.Contains(item.RequiredDomains, "valuation") ||
				!slices.Equal(item.ExpectedAbstentions, []string{
					"scenario.sensitivity_matrix",
					"valuation.fcff_dcf",
					"valuation.peer_multiple",
				}) {
				t.Fatalf("valuation contract = %+v", item)
			}
		case "thesis-monitoring":
			if !slices.Contains(item.RequiredDomains, "risk") ||
				!slices.Equal(item.ExpectedAbstentions, []string{"narrative.investor_relations"}) {
				t.Fatalf("thesis contract = %+v", item)
			}
		default:
			t.Fatalf("unknown augmentation case: %+v", item)
		}
	}
	for _, questionID := range []string{
		"economics-transmission",
		"valuation-readiness",
		"thesis-monitoring",
	} {
		if counts[questionID] != 20 {
			t.Fatalf("%s = %d cases, want 20", questionID, counts[questionID])
		}
	}
}

func TestStandaloneDevelopmentAugmentationRoutesToExpectedIntentAndCapabilities(t *testing.T) {
	catalog := loadPublicCatalogFixture(t)
	financials := loadPublicFinancialSummaryFixture(t)
	suite, err := BuildStandaloneDevelopmentAugmentationSuite(catalog, financials)
	if err != nil {
		t.Fatal(err)
	}
	for _, item := range suite.Cases {
		assertAugmentationQuestionRoute(t, suite, item)
	}
}

func assertAugmentationQuestionRoute(
	t *testing.T,
	suite StandaloneJourneySuite,
	item StandaloneJourneyCase,
) {
	t.Helper()
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text:      item.Question,
		AsOf:      suite.AsOf,
		RunID:     "run-" + item.JourneyID,
		RequestID: "request-" + item.JourneyID,
	})
	if err != nil {
		t.Fatalf("%s parse: %v", item.JourneyID, err)
	}
	expectedIntent := map[string]string{
		"economics-transmission": "economic_transmission",
		"valuation-readiness":    "valuation",
		"thesis-monitoring":      "thesis_review",
	}[item.QuestionID]
	if request.PrimaryIntent != expectedIntent {
		t.Fatalf("%s intent = %s, want %s", item.JourneyID, request.PrimaryIntent, expectedIntent)
	}
	plan, err := planner.Default().Build(request)
	if err != nil {
		t.Fatalf("%s plan: %v", item.JourneyID, err)
	}
	authorized := map[string]bool{}
	for _, step := range plan.Steps {
		for _, operationID := range step.CapabilityIDs {
			authorized[operationID] = true
		}
	}
	expectedCapabilities := map[string][]string{
		"economics-transmission": {"economics.yield_curve"},
		"valuation-readiness": {
			"scenario.sensitivity_matrix",
			"valuation.fcff_dcf",
			"valuation.peer_multiple",
		},
		"thesis-monitoring": {},
	}[item.QuestionID]
	for _, operationID := range expectedCapabilities {
		if !authorized[operationID] {
			t.Fatalf("%s omitted expected capability %s: %+v", item.JourneyID, operationID, plan)
		}
	}
}

func loadPublicCatalogFixture(t *testing.T) PublicCatalog {
	t.Helper()
	payload, err := os.ReadFile(filepath.Join("..", "..", "fixtures", "productscope", "technology20-catalog.json"))
	if err != nil {
		t.Fatal(err)
	}
	var result PublicCatalog
	if err := json.Unmarshal(payload, &result); err != nil {
		t.Fatal(err)
	}
	return result
}

func loadPublicFinancialSummaryFixture(t *testing.T) PublicFinancialSummary {
	t.Helper()
	payload, err := os.ReadFile(filepath.Join("..", "..", "fixtures", "productscope", "technology20-financial-summary.json"))
	if err != nil {
		t.Fatal(err)
	}
	var result PublicFinancialSummary
	if err := json.Unmarshal(payload, &result); err != nil {
		t.Fatal(err)
	}
	return result
}
