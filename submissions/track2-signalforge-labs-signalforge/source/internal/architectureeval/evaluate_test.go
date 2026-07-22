package architectureeval

import "testing"

func TestFrozenArchitectureEvaluationSelectsSeparatePipeline(t *testing.T) {
	report, err := Evaluate()
	if err != nil {
		t.Fatal(err)
	}
	if report.Selected != "separate-interpreter-orchestrator" {
		t.Fatalf("unexpected selected architecture %q", report.Selected)
	}
	if !report.Candidates[0].Accepted {
		t.Fatalf("separate architecture should pass: %+v", report.Candidates[0])
	}
	if report.Candidates[1].Accepted {
		t.Fatal("broad fused route should fail fanout or unnecessary activation")
	}
	if report.Candidates[2].Accepted {
		t.Fatal("smaller bench should fail mandatory specialist recall")
	}
}
