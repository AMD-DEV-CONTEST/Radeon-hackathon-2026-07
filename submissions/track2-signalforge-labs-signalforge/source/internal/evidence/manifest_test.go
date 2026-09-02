package evidence

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

func TestManifestDetectsArtifactAndTreeStaleness(t *testing.T) {
	root := t.TempDir()
	run(t, root, "git", "init", "-q")
	run(t, root, "git", "config", "user.email", "test@example.com")
	run(t, root, "git", "config", "user.name", "Test")
	artifact := filepath.Join(root, "report.json")
	if err := os.WriteFile(artifact, []byte("{\"ok\":true}\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, root, "git", "add", "report.json")
	run(t, root, "git", "commit", "-qm", "fixture")

	manifest, err := Generate(GenerateOptions{
		RepoRoot: root, Artifacts: []string{artifact},
		Now: time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC),
		Runtime: contracts.RuntimeIdentity{
			OS: "linux", Architecture: "amd64", ROCmVersion: "7.2.1", EngineVersion: "vllm-test",
		},
		GPU: &contracts.GPUIdentity{Vendor: "AMD", Product: "Radeon", Architecture: "gfx1100"},
		Models: []contracts.ModelIdentity{{
			ModelID: "model", Revision: "revision", ArtifactSHA256: strings.Repeat("a", 64),
			Quantization: "fp16", Runtime: "vllm",
		}},
		Datasets: []contracts.DatasetIdentity{{
			DatasetID: "dataset", Version: "v1", ManifestSHA256: strings.Repeat("b", 64), Split: "evaluation",
		}},
	})
	if err != nil {
		t.Fatal(err)
	}
	issues, err := Check(root, manifest)
	if err != nil || len(issues) != 0 {
		t.Fatalf("fresh manifest should pass: %v %+v", err, issues)
	}
	if err := os.WriteFile(artifact, []byte("{\"ok\":false}\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	issues, err = Check(root, manifest)
	if err != nil {
		t.Fatal(err)
	}
	if len(issues) < 2 {
		t.Fatalf("expected artifact and tree staleness, got %+v", issues)
	}
}

func TestArtifactOutsideRepositoryIsRejected(t *testing.T) {
	root := t.TempDir()
	run(t, root, "git", "init", "-q")
	run(t, root, "git", "config", "user.email", "test@example.com")
	run(t, root, "git", "config", "user.name", "Test")
	inside := filepath.Join(root, "inside.txt")
	if err := os.WriteFile(inside, []byte("inside"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, root, "git", "add", "inside.txt")
	run(t, root, "git", "commit", "-qm", "fixture")
	outside := filepath.Join(t.TempDir(), "outside.txt")
	if err := os.WriteFile(outside, []byte("outside"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := Generate(GenerateOptions{RepoRoot: root, Artifacts: []string{outside}}); err == nil {
		t.Fatal("outside artifact must fail")
	}
}

func run(t *testing.T, directory, name string, args ...string) {
	t.Helper()
	command := exec.Command(name, args...)
	command.Dir = directory
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("%s: %v: %s", name, err, output)
	}
}
