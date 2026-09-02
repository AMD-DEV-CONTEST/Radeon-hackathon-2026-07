package evidence

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/runid"
)

type GenerateOptions struct {
	RepoRoot  string
	Artifacts []string
	Models    []contracts.ModelIdentity
	Datasets  []contracts.DatasetIdentity
	Runtime   contracts.RuntimeIdentity
	GPU       *contracts.GPUIdentity
	Now       time.Time
}

type StaleIssue struct {
	Kind     string `json:"kind"`
	Target   string `json:"target"`
	Expected string `json:"expected"`
	Actual   string `json:"actual"`
}

func Generate(options GenerateOptions) (contracts.EvidenceManifest, error) {
	root, err := filepath.Abs(options.RepoRoot)
	if err != nil {
		return contracts.EvidenceManifest{}, err
	}
	commit, dirty, err := gitState(root)
	if err != nil {
		return contracts.EvidenceManifest{}, err
	}
	treeSHA, err := treeHash(root)
	if err != nil {
		return contracts.EvidenceManifest{}, err
	}
	now := options.Now.UTC()
	if now.IsZero() {
		now = time.Now().UTC()
	}
	id, err := runid.New(now)
	if err != nil {
		return contracts.EvidenceManifest{}, err
	}
	runtimeIdentity := options.Runtime
	if runtimeIdentity.OS == "" {
		runtimeIdentity = contracts.RuntimeIdentity{
			OS: runtime.GOOS, Architecture: runtime.GOARCH, GoVersion: runtime.Version(),
		}
	}
	manifest := contracts.EvidenceManifest{
		SchemaVersion: contracts.SchemaVersionV1,
		RunID:         id, CodeCommit: commit, CodeTreeSHA: treeSHA, CodeDirty: dirty,
		CreatedAt: now, Runtime: runtimeIdentity, GPU: options.GPU,
		Models:   append([]contracts.ModelIdentity(nil), options.Models...),
		Datasets: append([]contracts.DatasetIdentity(nil), options.Datasets...),
	}
	for _, artifactPath := range options.Artifacts {
		artifact, err := artifactFromPath(root, artifactPath)
		if err != nil {
			return contracts.EvidenceManifest{}, err
		}
		manifest.Artifacts = append(manifest.Artifacts, artifact)
	}
	sort.Slice(manifest.Artifacts, func(i, j int) bool {
		return manifest.Artifacts[i].Path < manifest.Artifacts[j].Path
	})
	manifest.ManifestSHA, err = manifestHash(manifest)
	if err != nil {
		return contracts.EvidenceManifest{}, err
	}
	if err := contracts.ValidateEvidenceManifest(manifest); err != nil {
		return contracts.EvidenceManifest{}, err
	}
	return manifest, nil
}

func Check(repoRoot string, manifest contracts.EvidenceManifest) ([]StaleIssue, error) {
	if err := contracts.ValidateEvidenceManifest(manifest); err != nil {
		return nil, err
	}
	root, err := filepath.Abs(repoRoot)
	if err != nil {
		return nil, err
	}
	var issues []StaleIssue
	expectedManifestSHA, err := manifestHash(manifest)
	if err != nil {
		return nil, err
	}
	if expectedManifestSHA != manifest.ManifestSHA {
		issues = append(issues, StaleIssue{Kind: "manifest", Target: "manifest", Expected: manifest.ManifestSHA, Actual: expectedManifestSHA})
	}
	commit, dirty, err := gitState(root)
	if err != nil {
		return nil, err
	}
	if commit != manifest.CodeCommit {
		issues = append(issues, StaleIssue{Kind: "code_commit", Target: "repository", Expected: manifest.CodeCommit, Actual: commit})
	}
	if dirty != manifest.CodeDirty {
		issues = append(issues, StaleIssue{Kind: "code_dirty", Target: "repository", Expected: fmt.Sprint(manifest.CodeDirty), Actual: fmt.Sprint(dirty)})
	}
	treeSHA, err := treeHash(root)
	if err != nil {
		return nil, err
	}
	if treeSHA != manifest.CodeTreeSHA {
		issues = append(issues, StaleIssue{Kind: "code_tree", Target: "repository", Expected: manifest.CodeTreeSHA, Actual: treeSHA})
	}
	for _, artifact := range manifest.Artifacts {
		actual, err := fileHash(filepath.Join(root, filepath.FromSlash(artifact.Path)))
		if err != nil {
			actual = "unavailable"
		}
		if actual != artifact.SHA256 {
			issues = append(issues, StaleIssue{Kind: "artifact", Target: artifact.Path, Expected: artifact.SHA256, Actual: actual})
		}
	}
	return issues, nil
}

func Write(path string, manifest contracts.EvidenceManifest) error {
	payload, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return err
	}
	payload = append(payload, '\n')
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(path, payload, 0o644)
}

func Read(path string) (contracts.EvidenceManifest, error) {
	payload, err := os.ReadFile(path)
	if err != nil {
		return contracts.EvidenceManifest{}, err
	}
	var manifest contracts.EvidenceManifest
	if err := json.Unmarshal(payload, &manifest); err != nil {
		return contracts.EvidenceManifest{}, err
	}
	return manifest, nil
}

func artifactFromPath(root, path string) (contracts.EvidenceArtifact, error) {
	absolute, err := filepath.Abs(path)
	if err != nil {
		return contracts.EvidenceArtifact{}, err
	}
	relative, err := filepath.Rel(root, absolute)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		return contracts.EvidenceArtifact{}, fmt.Errorf("artifact %q is outside the repository", path)
	}
	info, err := os.Lstat(absolute)
	if err != nil {
		return contracts.EvidenceArtifact{}, err
	}
	if !info.Mode().IsRegular() {
		return contracts.EvidenceArtifact{}, errors.New("artifact must be a regular file")
	}
	hash, err := fileHash(absolute)
	if err != nil {
		return contracts.EvidenceArtifact{}, err
	}
	slashPath := filepath.ToSlash(relative)
	return contracts.EvidenceArtifact{
		ArtifactID: strings.NewReplacer("/", "-", ".", "-").Replace(slashPath),
		Kind:       filepath.Ext(slashPath), Path: slashPath, SHA256: hash,
		Metrics: map[string]string{"bytes": fmt.Sprint(info.Size())},
	}, nil
}

func fileHash(path string) (string, error) {
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

func treeHash(root string) (string, error) {
	command := exec.Command("git", "-C", root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
	output, err := command.Output()
	if err != nil {
		return "", fmt.Errorf("list repository files: %w", err)
	}
	names := strings.Split(strings.TrimSuffix(string(output), "\x00"), "\x00")
	sort.Strings(names)
	hash := sha256.New()
	for _, name := range names {
		if name == "" {
			continue
		}
		digest, err := fileHash(filepath.Join(root, filepath.FromSlash(name)))
		if err != nil {
			return "", err
		}
		_, _ = io.WriteString(hash, name+"\x00"+digest+"\x00")
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func gitState(root string) (string, bool, error) {
	commitOutput, err := exec.Command("git", "-C", root, "rev-parse", "HEAD").Output()
	if err != nil {
		return "", false, fmt.Errorf("read git commit: %w", err)
	}
	statusOutput, err := exec.Command("git", "-C", root, "status", "--porcelain=v1", "--untracked-files=all").Output()
	if err != nil {
		return "", false, fmt.Errorf("read git status: %w", err)
	}
	return strings.TrimSpace(string(commitOutput)), len(statusOutput) > 0, nil
}

func manifestHash(manifest contracts.EvidenceManifest) (string, error) {
	manifest.ManifestSHA = ""
	payload, err := json.Marshal(manifest)
	if err != nil {
		return "", err
	}
	hash := sha256.Sum256(payload)
	return hex.EncodeToString(hash[:]), nil
}
