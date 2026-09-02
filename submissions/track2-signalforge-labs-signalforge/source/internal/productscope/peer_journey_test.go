package productscope

import "testing"

func TestPeerJourneyPopulationIsBalancedAndNeverPromoted(t *testing.T) {
	development, sealed, err := BuildPeerJourneySuites(loadPublicCatalogFixture(t), loadPeerEvaluationFixture(t))
	if err != nil {
		t.Fatal(err)
	}
	if len(development.Cases) != 40 || len(sealed.Cases) != 20 {
		t.Fatalf("population = %d development / %d sealed", len(development.Cases), len(sealed.Cases))
	}
	for _, item := range append(development.Cases, sealed.Cases...) {
		if item.ExpectedPromoted {
			t.Fatalf("unevaluated peer journey was promoted: %+v", item)
		}
	}
}
