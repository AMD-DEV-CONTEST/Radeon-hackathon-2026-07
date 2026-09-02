package contracts

import (
	"encoding/json"
	"os"
	"testing"
)

type accountingEvalSet struct {
	SchemaVersion string               `json:"schema_version"`
	Cases         []accountingEvalCase `json:"cases"`
}

type accountingEvalCase struct {
	CaseID                string   `json:"case_id"`
	Prompt                string   `json:"prompt"`
	ExpectedEvidenceState string   `json:"expected_evidence_state"`
	ExpectedHandoff       *string  `json:"expected_handoff"`
	RequiredPacketFields  []string `json:"required_packet_fields"`
	Prohibited            []string `json:"prohibited"`
}

func TestAccountingPacketEvaluationSetIsComplete(t *testing.T) {
	data, err := os.ReadFile("../../fixtures/accounting-context-packet-eval.json")
	if err != nil {
		t.Fatal(err)
	}
	var set accountingEvalSet
	if err := json.Unmarshal(data, &set); err != nil {
		t.Fatal(err)
	}
	if set.SchemaVersion != "accounting-context-packet-eval/v1" || len(set.Cases) != 8 {
		t.Fatalf("unexpected accounting eval set: %s, %d cases", set.SchemaVersion, len(set.Cases))
	}
	seen := map[string]bool{}
	states := map[string]bool{}
	handoffs := map[string]bool{}
	for _, item := range set.Cases {
		if item.CaseID == "" || item.Prompt == "" || len(item.RequiredPacketFields) == 0 || len(item.Prohibited) == 0 {
			t.Fatalf("incomplete case %+v", item)
		}
		if seen[item.CaseID] {
			t.Fatalf("duplicate case %q", item.CaseID)
		}
		seen[item.CaseID] = true
		states[item.ExpectedEvidenceState] = true
		if item.ExpectedHandoff != nil {
			handoffs[*item.ExpectedHandoff] = true
		}
	}
	for _, state := range []string{"available", "stale", "conflicting", "missing", "incomparable"} {
		if !states[state] {
			t.Fatalf("missing evidence state %q", state)
		}
	}
	for _, role := range []string{"financial-quality/v1", "valuation/v1"} {
		if !handoffs[role] {
			t.Fatalf("missing handoff %q", role)
		}
	}
}
