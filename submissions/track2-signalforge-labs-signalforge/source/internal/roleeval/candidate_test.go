package roleeval

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/rvbernucci/signalforge/internal/localagent"
	"github.com/rvbernucci/signalforge/internal/roles"
)

func TestLoadCandidatePromptRegistryVerifiesAndAppliesAddon(t *testing.T) {
	manifestPath, sourceRoot := writeCandidateFixture(t, false)
	registry, identity, err := LoadCandidatePromptRegistry(manifestPath, sourceRoot)
	if err != nil {
		t.Fatal(err)
	}
	prompt, _ := registry.Get(roles.AccountingReporting)
	if identity.CandidateID != "accounting-test-v1" || identity.RoleID != roles.AccountingReporting ||
		identity.ManifestSHA == "" || !strings.Contains(prompt.System, "Classify policy evidence.") {
		t.Fatalf("candidate identity or prompt binding failed: %+v", identity)
	}
}

func TestLoadCandidatePromptRegistryRejectsDigestDrift(t *testing.T) {
	manifestPath, sourceRoot := writeCandidateFixture(t, false)
	if err := os.WriteFile(filepath.Join(filepath.Dir(manifestPath), "prompt-addon.txt"), []byte("tampered\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, _, err := LoadCandidatePromptRegistry(manifestPath, sourceRoot); err == nil || !strings.Contains(err.Error(), "digest") {
		t.Fatalf("expected digest rejection, got %v", err)
	}
}

func TestLoadCandidatePromptRegistryRejectsTraversal(t *testing.T) {
	manifestPath, sourceRoot := writeCandidateFixture(t, true)
	if _, _, err := LoadCandidatePromptRegistry(manifestPath, sourceRoot); err == nil || !strings.Contains(err.Error(), "escapes") {
		t.Fatalf("expected traversal rejection, got %v", err)
	}
}

func TestLoadCandidatePromptBundleRejectsDuplicateRole(t *testing.T) {
	manifestPath, sourceRoot := writeCandidateFixture(t, false)
	if _, _, err := LoadCandidatePromptBundle([]string{manifestPath, manifestPath}, sourceRoot); err == nil || !strings.Contains(err.Error(), "duplicates") {
		t.Fatalf("expected duplicate bundle rejection, got %v", err)
	}
}

func writeCandidateFixture(t *testing.T, traversal bool) (string, string) {
	t.Helper()
	root := t.TempDir()
	sourceRoot := filepath.Join(root, "source")
	candidateRoot := filepath.Join(root, "candidate")
	if err := os.MkdirAll(filepath.Join(sourceRoot, "internal/localagent"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(candidateRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	basePath := filepath.Join(sourceRoot, "internal/localagent/prompts.go")
	definitionPath := filepath.Join(candidateRoot, "candidate.json")
	addonPath := filepath.Join(candidateRoot, "prompt-addon.txt")
	base := []byte("package localagent\n")
	definition := []byte(`{"candidate_id":"accounting-test-v1","role_id":"accounting-reporting/v1","base_prompt_set":"signalforge-role-prompts/v12","primary_factor":"instruction_precision","holdout_accessed":false}`)
	addon := []byte("Classify policy evidence.\n")
	for path, payload := range map[string][]byte{basePath: base, definitionPath: definition, addonPath: addon} {
		if err := os.WriteFile(path, payload, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	addonFile := candidateFile{Path: "prompt-addon.txt", SHA256: testDigest(addon)}
	if traversal {
		addonFile.Path = "../outside.txt"
		if err := os.WriteFile(filepath.Join(root, "outside.txt"), addon, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	manifest := candidateManifest{
		SchemaVersion: candidateManifestSchema, CandidateID: "accounting-test-v1", RoleID: roles.AccountingReporting,
		BasePromptSet: localagent.PromptSetVersion, PrimaryFactor: "instruction_precision", RunnableOnRadeon: true,
		PromotionStatus: "provisional_pre_radeon",
		Files: candidateFiles{
			CandidateDefinition: candidateFile{Path: "candidate.json", SHA256: testDigest(definition)},
			PromptAddon:         addonFile,
			BasePromptSource:    candidateFile{Path: "internal/localagent/prompts.go", SHA256: testDigest(base)},
		},
	}
	payload, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	manifestPath := filepath.Join(candidateRoot, "candidate-manifest.json")
	if err := os.WriteFile(manifestPath, payload, 0o644); err != nil {
		t.Fatal(err)
	}
	return manifestPath, sourceRoot
}

func testDigest(payload []byte) string {
	sum := sha256.Sum256(payload)
	return hex.EncodeToString(sum[:])
}
