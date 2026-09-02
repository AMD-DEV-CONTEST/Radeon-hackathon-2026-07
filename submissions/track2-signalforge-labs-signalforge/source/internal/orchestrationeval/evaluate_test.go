package orchestrationeval

import "testing"

func TestFrozenOrchestrationEvaluationPasses(t *testing.T) {
	report, err := Evaluate()
	if err != nil {
		t.Fatal(err)
	}
	if !report.Accepted {
		t.Fatalf("orchestration evaluation failed: %+v", report)
	}
}
