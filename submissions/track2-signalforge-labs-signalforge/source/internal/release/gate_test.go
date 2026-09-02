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

func TestRefreshClaimEvidenceOnlyUpdatesDeclaredHashes(t *testing.T) {
	root := t.TempDir()
	evidence := filepath.Join(root, "evidence.json")
	if err := os.WriteFile(evidence, []byte("current evidence"), 0o644); err != nil {
		t.Fatal(err)
	}
	registry := ClaimRegistry{
		SchemaVersion: "signalforge/public-claims/v1",
		Claims: []Claim{{
			ClaimID: "test",
			Text:    "The claim text must remain unchanged.",
			Status:  "verified",
			Evidence: []EvidenceRef{{
				Path:   "evidence.json",
				SHA256: "stale",
			}},
			PublicFiles: []string{"README.md"},
		}},
	}
	refreshed, err := RefreshClaimEvidence(root, registry)
	if err != nil {
		t.Fatal(err)
	}
	expected := sha256.Sum256([]byte("current evidence"))
	if refreshed.Claims[0].Evidence[0].SHA256 != fmt.Sprintf("%x", expected) {
		t.Fatalf("unexpected refreshed digest: %+v", refreshed.Claims[0].Evidence[0])
	}
	if refreshed.Claims[0].Text != registry.Claims[0].Text ||
		refreshed.Claims[0].Evidence[0].Path != registry.Claims[0].Evidence[0].Path ||
		len(refreshed.Claims[0].Evidence) != len(registry.Claims[0].Evidence) {
		t.Fatal("refresh changed claim scope instead of only updating the declared hash")
	}
}

func TestRefreshClaimEvidenceFailsClosedForMissingDeclaredEvidence(t *testing.T) {
	registry := ClaimRegistry{
		SchemaVersion: "signalforge/public-claims/v1",
		Claims: []Claim{{
			ClaimID:  "test",
			Text:     "Claim.",
			Status:   "verified",
			Evidence: []EvidenceRef{{Path: "missing.json", SHA256: "stale"}},
		}},
	}
	if _, err := RefreshClaimEvidence(t.TempDir(), registry); err == nil {
		t.Fatal("missing declared evidence must fail the refresh")
	}
}

func TestClaimEvidenceCannotEscapeRepositoryRoot(t *testing.T) {
	root := t.TempDir()
	outside := filepath.Join(t.TempDir(), "outside.json")
	if err := os.WriteFile(outside, []byte("outside"), 0o644); err != nil {
		t.Fatal(err)
	}
	relativeOutside, err := filepath.Rel(root, outside)
	if err != nil {
		t.Fatal(err)
	}
	registry := ClaimRegistry{
		SchemaVersion: "signalforge/public-claims/v1",
		Claims: []Claim{{
			ClaimID: "test",
			Text:    "Claim.",
			Status:  "verified",
			Evidence: []EvidenceRef{{
				Path: relativeOutside,
			}},
			PublicFiles: []string{"README.md"},
		}},
	}
	if _, err := RefreshClaimEvidence(root, registry); err == nil {
		t.Fatal("refresh accepted evidence outside the repository")
	}
	if problems := CheckClaims(root, registry); len(problems) == 0 {
		t.Fatal("claim check accepted evidence outside the repository")
	}
	registry.Claims[0].Evidence[0].Path = outside
	if _, err := RefreshClaimEvidence(root, registry); err == nil {
		t.Fatal("refresh accepted an absolute evidence path")
	}
}

func TestClaimEvidenceSymlinkCannotEscapeRepositoryRoot(t *testing.T) {
	root := t.TempDir()
	outside := filepath.Join(t.TempDir(), "outside.json")
	if err := os.WriteFile(outside, []byte("outside"), 0o644); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(root, "evidence-link.json")
	if err := os.Symlink(outside, link); err != nil {
		t.Fatal(err)
	}
	registry := ClaimRegistry{
		SchemaVersion: "signalforge/public-claims/v1",
		Claims: []Claim{{
			ClaimID: "test",
			Text:    "Claim.",
			Status:  "verified",
			Evidence: []EvidenceRef{{
				Path: "evidence-link.json",
			}},
		}},
	}
	if _, err := RefreshClaimEvidence(root, registry); err == nil {
		t.Fatal("refresh accepted a symlink to evidence outside the repository")
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
