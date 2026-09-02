package roleeval

import "testing"

func TestClassifyFailureUsesSpecificContractBoundaries(t *testing.T) {
	tests := []struct {
		observation Observation
		want        string
	}{
		{Observation{Error: "decode context packet body: invalid JSON"}, FailureSchemaInvalid},
		{Observation{Error: "claim invented evidence evidence-7"}, FailureInventedEvidence},
		{Observation{Metrics: Metrics{ContractValid: 1, RoutingCorrect: 0}}, FailureRouting},
		{Observation{Metrics: Metrics{ContractValid: 1, RoutingCorrect: 1, PacketComplete: 1, CitationSupport: 1, NumericalConsistency: 1, ContradictionHandling: 0}}, FailureContradictionUnhandled},
	}
	for _, test := range tests {
		if got := classifyFailure(test.observation); got != test.want {
			t.Fatalf("classifyFailure(%+v) = %q, want %q", test.observation, got, test.want)
		}
	}
}
