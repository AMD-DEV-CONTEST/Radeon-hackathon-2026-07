package release

import (
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func TestClaimGateAcceptsCurrentEvidenceAndRejectsStaleness(t *testing.T) {
	root := t.TempDir()
	evidence := filepath.Join(root, "evidence.json")
	public := filepath.Join(root, "README.md")
	if err := os.WriteFile(evidence, []byte("evidence"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(public, []byte("Claim. <!-- evidence-claim:test -->\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256([]byte("evidence"))
	registry := ClaimRegistry{
		SchemaVersion: "signalforge/public-claims/v1",
		Claims: []Claim{{
			ClaimID: "test", Text: "Claim.", Status: "verified",
			Evidence:    []EvidenceRef{{Path: "evidence.json", SHA256: fmt.Sprintf("%x", digest)}},
			PublicFiles: []string{"README.md"},
		}},
	}
	if problems := CheckClaims(root, registry); len(problems) != 0 {
		t.Fatalf("current evidence rejected: %v", problems)
	}
	if err := os.WriteFile(evidence, []byte("changed"), 0o644); err != nil {
		t.Fatal(err)
	}
	if problems := CheckClaims(root, registry); len(problems) == 0 {
		t.Fatal("stale evidence must fail")
	}
}

func TestReleaseGateRejectsUnsupportedOrPendingItems(t *testing.T) {
	checklist := ReleaseChecklist{
		SchemaVersion: "signalforge/release-checklist/v1",
		Items:         []ChecklistItem{{CheckID: "tests", Required: true, Status: "pending"}},
	}
	if problems := CheckRelease(checklist); len(problems) != 1 {
		t.Fatalf("pending required item must fail: %v", problems)
	}
	checklist.Items[0].Status = "passed"
	if problems := CheckRelease(checklist); len(problems) != 1 {
		t.Fatalf("passed item without evidence must fail: %v", problems)
	}
	checklist.Items[0].Evidence = "evidence/validation-summary.json"
	if problems := CheckRelease(checklist); len(problems) != 0 {
		t.Fatalf("supported release item should pass: %v", problems)
	}
}
