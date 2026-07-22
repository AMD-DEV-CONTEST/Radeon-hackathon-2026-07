package taxonomy

import (
	"testing"

	"github.com/rvbernucci/signalforge/internal/roles"
)

func TestTaxonomyHasEightVersionedJobs(t *testing.T) {
	if Version != "question-taxonomy/v1" {
		t.Fatalf("unexpected version %q", Version)
	}
	if got := len(Definitions()); got != 8 {
		t.Fatalf("expected eight jobs, got %d", got)
	}
	for _, definition := range Definitions() {
		if len(definition.PositiveExamples) < 2 || len(definition.NegativeExamples) < 2 {
			t.Fatalf("intent %s lacks positive or negative examples", definition.Intent)
		}
	}
}

func TestFrozenCasesCoverEveryIntentAndEdge(t *testing.T) {
	cases := FrozenCases()
	if len(cases) != 24 {
		t.Fatalf("expected 24 cases, got %d", len(cases))
	}
	counts := map[Intent]int{}
	seen := map[string]bool{}
	var followUp, ambiguous, adversarial bool
	for _, item := range cases {
		if seen[item.CaseID] {
			t.Fatalf("duplicate case %q", item.CaseID)
		}
		seen[item.CaseID] = true
		counts[item.PrimaryIntent]++
		if item.Period == "" || item.AnswerDepth == "" || !item.AsOfRequired || len(item.MandatoryRoles) == 0 || len(item.ProhibitedCapabilities) == 0 {
			t.Fatalf("case %s is incompletely labeled", item.CaseID)
		}
		followUp = followUp || item.FollowUp
		ambiguous = ambiguous || item.ClarificationRequired
		adversarial = adversarial || item.AdversarialAdvice
	}
	for _, definition := range Definitions() {
		if counts[definition.Intent] != 3 {
			t.Fatalf("intent %s has %d cases", definition.Intent, counts[definition.Intent])
		}
	}
	if !followUp || !ambiguous || !adversarial {
		t.Fatal("frozen set must include follow-up, ambiguity, and adversarial cases")
	}
}

func TestInterpreterAndMinimalRouterAgainstFrozenCases(t *testing.T) {
	for _, item := range FrozenCases() {
		intent, err := Interpret(item.Question)
		if err != nil {
			t.Fatalf("case %s: %v", item.CaseID, err)
		}
		if intent != item.PrimaryIntent {
			t.Fatalf("case %s: got %s, want %s", item.CaseID, intent, item.PrimaryIntent)
		}
		route, err := Plan(item.Question, intent, false)
		if err != nil {
			t.Fatalf("case %s: %v", item.CaseID, err)
		}
		activeRoles := append(append([]string(nil), route.ContextRoles...), route.ReviewRoles...)
		if !containsAll(activeRoles, item.MandatoryRoles) {
			t.Fatalf("case %s misses mandatory roles: got %v want %v", item.CaseID, activeRoles, item.MandatoryRoles)
		}
		if intersects(activeRoles, item.ProhibitedRoles) {
			t.Fatalf("case %s activated prohibited role", item.CaseID)
		}
		if len(route.ContextRoles) > 4 {
			t.Fatalf("case %s exceeds four context roles", item.CaseID)
		}
		if !contains(route.ReviewRoles, roles.EvidenceCritic) {
			t.Fatalf("case %s omits evidence critic", item.CaseID)
		}
	}
}

func containsAll(values, required []string) bool {
	for _, item := range required {
		if !contains(values, item) {
			return false
		}
	}
	return true
}

func intersects(left, right []string) bool {
	for _, item := range left {
		if contains(right, item) {
			return true
		}
	}
	return false
}

func contains(values []string, target string) bool {
	for _, item := range values {
		if item == target {
			return true
		}
	}
	return false
}
