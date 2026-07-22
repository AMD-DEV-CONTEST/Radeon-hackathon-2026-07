package release

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

type EvidenceRef struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
}

type Claim struct {
	ClaimID     string        `json:"claim_id"`
	Text        string        `json:"text"`
	Status      string        `json:"status"`
	Evidence    []EvidenceRef `json:"evidence,omitempty"`
	PublicFiles []string      `json:"public_files"`
}

type ClaimRegistry struct {
	SchemaVersion string  `json:"schema_version"`
	Claims        []Claim `json:"claims"`
}

type ChecklistItem struct {
	CheckID  string `json:"check_id"`
	Required bool   `json:"required"`
	Status   string `json:"status"`
	Evidence string `json:"evidence,omitempty"`
}

type ReleaseChecklist struct {
	SchemaVersion string          `json:"schema_version"`
	Items         []ChecklistItem `json:"items"`
}

func CheckClaims(root string, registry ClaimRegistry) []error {
	var problems []error
	if registry.SchemaVersion != "signalforge/public-claims/v1" {
		problems = append(problems, fmt.Errorf("unsupported claim registry schema %q", registry.SchemaVersion))
	}
	seen := map[string]bool{}
	for _, claim := range registry.Claims {
		if claim.ClaimID == "" || claim.Text == "" || len(claim.PublicFiles) == 0 {
			problems = append(problems, fmt.Errorf("incomplete claim %q", claim.ClaimID))
			continue
		}
		if seen[claim.ClaimID] {
			problems = append(problems, fmt.Errorf("duplicate claim %q", claim.ClaimID))
		}
		seen[claim.ClaimID] = true
		switch claim.Status {
		case "verified", "measured":
			if len(claim.Evidence) == 0 {
				problems = append(problems, fmt.Errorf("claim %q has no evidence", claim.ClaimID))
			}
		case "planned", "estimate":
			// Planning and estimates are allowed only under an explicit status.
		default:
			problems = append(problems, fmt.Errorf("claim %q has invalid status %q", claim.ClaimID, claim.Status))
		}
		for _, evidence := range claim.Evidence {
			actual, err := hashFile(filepath.Join(root, filepath.FromSlash(evidence.Path)))
			if err != nil {
				problems = append(problems, fmt.Errorf("claim %q evidence %q: %w", claim.ClaimID, evidence.Path, err))
				continue
			}
			if actual != evidence.SHA256 {
				problems = append(problems, fmt.Errorf("claim %q evidence %q is stale", claim.ClaimID, evidence.Path))
			}
		}
		marker := "<!-- evidence-claim:" + claim.ClaimID + " -->"
		for _, publicFile := range claim.PublicFiles {
			payload, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(publicFile)))
			if err != nil {
				problems = append(problems, fmt.Errorf("claim %q public file %q: %w", claim.ClaimID, publicFile, err))
				continue
			}
			if !strings.Contains(string(payload), marker) {
				problems = append(problems, fmt.Errorf("claim %q marker missing from %q", claim.ClaimID, publicFile))
			}
		}
	}
	return problems
}

func CheckRelease(checklist ReleaseChecklist) []error {
	var problems []error
	if checklist.SchemaVersion != "signalforge/release-checklist/v1" {
		problems = append(problems, fmt.Errorf("unsupported release checklist schema %q", checklist.SchemaVersion))
	}
	seen := map[string]bool{}
	for _, item := range checklist.Items {
		if item.CheckID == "" {
			problems = append(problems, fmt.Errorf("release checklist contains an empty check ID"))
			continue
		}
		if seen[item.CheckID] {
			problems = append(problems, fmt.Errorf("duplicate release check %q", item.CheckID))
		}
		seen[item.CheckID] = true
		if item.Required && item.Status != "passed" {
			problems = append(problems, fmt.Errorf("required release check %q is %q", item.CheckID, item.Status))
		}
		if item.Status == "passed" && item.Evidence == "" {
			problems = append(problems, fmt.Errorf("passed release check %q lacks evidence", item.CheckID))
		}
	}
	return problems
}

func ReadClaims(path string) (ClaimRegistry, error) {
	var registry ClaimRegistry
	payload, err := os.ReadFile(path)
	if err != nil {
		return registry, err
	}
	err = json.Unmarshal(payload, &registry)
	return registry, err
}

func ReadChecklist(path string) (ReleaseChecklist, error) {
	var checklist ReleaseChecklist
	payload, err := os.ReadFile(path)
	if err != nil {
		return checklist, err
	}
	err = json.Unmarshal(payload, &checklist)
	return checklist, err
}

func hashFile(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}
