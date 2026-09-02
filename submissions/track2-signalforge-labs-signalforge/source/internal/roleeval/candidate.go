package roleeval

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/rvbernucci/signalforge/internal/localagent"
)

const candidateManifestSchema = "signalforge/sprint16a-candidate-manifest/v1"

type candidateFile struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
}

type candidateFiles struct {
	CandidateDefinition candidateFile `json:"candidate_definition"`
	PromptAddon         candidateFile `json:"prompt_addon"`
	BasePromptSource    candidateFile `json:"base_prompt_source"`
}

type candidateManifest struct {
	SchemaVersion    string         `json:"schema_version"`
	CandidateID      string         `json:"candidate_id"`
	RoleID           string         `json:"role_id"`
	BasePromptSet    string         `json:"base_prompt_set"`
	PrimaryFactor    string         `json:"primary_factor"`
	HoldoutAccessed  bool           `json:"holdout_accessed"`
	RunnableOnRadeon bool           `json:"runnable_on_radeon"`
	PromotionStatus  string         `json:"promotion_status"`
	Files            candidateFiles `json:"files"`
}

type candidateDefinition struct {
	CandidateID     string `json:"candidate_id"`
	RoleID          string `json:"role_id"`
	BasePromptSet   string `json:"base_prompt_set"`
	PrimaryFactor   string `json:"primary_factor"`
	HoldoutAccessed bool   `json:"holdout_accessed"`
}

type CandidateIdentity struct {
	CandidateID    string   `json:"candidate_id"`
	RoleID         string   `json:"role_id"`
	ManifestSHA    string   `json:"candidate_manifest_sha256"`
	PromptAddonSHA string   `json:"prompt_addon_sha256"`
	ComponentIDs   []string `json:"component_ids,omitempty"`
}

func LoadCandidatePromptRegistry(manifestPath, sourceRoot string) (localagent.PromptRegistry, CandidateIdentity, error) {
	return LoadCandidatePromptBundle([]string{manifestPath}, sourceRoot)
}

func LoadCandidatePromptBundle(manifestPaths []string, sourceRoot string) (localagent.PromptRegistry, CandidateIdentity, error) {
	if len(manifestPaths) == 0 {
		return localagent.PromptRegistry{}, CandidateIdentity{}, errors.New("candidate bundle requires at least one manifest")
	}
	paths := append([]string(nil), manifestPaths...)
	sort.Strings(paths)
	registry := localagent.DefaultPromptRegistry()
	identities := make([]CandidateIdentity, 0, len(paths))
	seenIDs, seenRoles := map[string]bool{}, map[string]bool{}
	for _, path := range paths {
		addon, identity, err := loadCandidate(path, sourceRoot)
		if err != nil {
			return localagent.PromptRegistry{}, CandidateIdentity{}, err
		}
		if seenIDs[identity.CandidateID] || seenRoles[identity.RoleID] {
			return localagent.PromptRegistry{}, CandidateIdentity{}, errors.New("candidate bundle duplicates an ID or specialist role")
		}
		seenIDs[identity.CandidateID], seenRoles[identity.RoleID] = true, true
		registry, err = registry.WithSystemAddon(identity.RoleID, localagent.PromptSetVersion, addon)
		if err != nil {
			return localagent.PromptRegistry{}, CandidateIdentity{}, err
		}
		identities = append(identities, identity)
	}
	if len(identities) == 1 {
		return registry, identities[0], nil
	}
	componentIDs, manifests, addons := []string{}, []string{}, []string{}
	for _, identity := range identities {
		componentIDs = append(componentIDs, identity.CandidateID)
		manifests = append(manifests, identity.ManifestSHA)
		addons = append(addons, identity.PromptAddonSHA)
	}
	return registry, CandidateIdentity{
		CandidateID: "bundle:" + strings.Join(componentIDs, "+"), RoleID: "multiple-context-roles",
		ManifestSHA:    digest([]byte(strings.Join(manifests, "\n"))),
		PromptAddonSHA: digest([]byte(strings.Join(addons, "\n"))), ComponentIDs: componentIDs,
	}, nil
}

func loadCandidate(manifestPath, sourceRoot string) (string, CandidateIdentity, error) {
	payload, err := os.ReadFile(manifestPath)
	if err != nil {
		return "", CandidateIdentity{}, err
	}
	var manifest candidateManifest
	if err := json.Unmarshal(payload, &manifest); err != nil {
		return "", CandidateIdentity{}, fmt.Errorf("decode candidate manifest: %w", err)
	}
	if manifest.SchemaVersion != candidateManifestSchema || manifest.CandidateID == "" || manifest.RoleID == "" ||
		manifest.BasePromptSet != localagent.PromptSetVersion || manifest.HoldoutAccessed || !manifest.RunnableOnRadeon ||
		manifest.PromotionStatus != "provisional_pre_radeon" {
		return "", CandidateIdentity{}, errors.New("candidate manifest header is not runnable")
	}
	manifestDir, err := filepath.Abs(filepath.Dir(manifestPath))
	if err != nil {
		return "", CandidateIdentity{}, err
	}
	sourceRoot, err = filepath.Abs(sourceRoot)
	if err != nil {
		return "", CandidateIdentity{}, err
	}
	definitionPayload, err := readVerifiedFile(manifestDir, manifest.Files.CandidateDefinition)
	if err != nil {
		return "", CandidateIdentity{}, fmt.Errorf("candidate definition: %w", err)
	}
	addon, err := readVerifiedFile(manifestDir, manifest.Files.PromptAddon)
	if err != nil {
		return "", CandidateIdentity{}, fmt.Errorf("prompt add-on: %w", err)
	}
	if _, err := readVerifiedFile(sourceRoot, manifest.Files.BasePromptSource); err != nil {
		return "", CandidateIdentity{}, fmt.Errorf("base prompt source: %w", err)
	}
	var definition candidateDefinition
	if err := json.Unmarshal(definitionPayload, &definition); err != nil {
		return "", CandidateIdentity{}, fmt.Errorf("decode candidate definition: %w", err)
	}
	if definition.CandidateID != manifest.CandidateID || definition.RoleID != manifest.RoleID ||
		definition.BasePromptSet != manifest.BasePromptSet || definition.PrimaryFactor != manifest.PrimaryFactor ||
		definition.HoldoutAccessed {
		return "", CandidateIdentity{}, errors.New("candidate definition does not match its manifest")
	}
	return string(addon), CandidateIdentity{
		CandidateID: manifest.CandidateID, RoleID: manifest.RoleID,
		ManifestSHA: digest(payload), PromptAddonSHA: manifest.Files.PromptAddon.SHA256,
	}, nil
}

func readVerifiedFile(root string, file candidateFile) ([]byte, error) {
	if file.Path == "" || file.SHA256 == "" || filepath.IsAbs(file.Path) {
		return nil, errors.New("file identity is incomplete or absolute")
	}
	path := filepath.Clean(filepath.Join(root, file.Path))
	relative, err := filepath.Rel(root, path)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		return nil, errors.New("file path escapes its authority root")
	}
	payload, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if digest(payload) != file.SHA256 {
		return nil, errors.New("file digest does not match the manifest")
	}
	return payload, nil
}

func digest(payload []byte) string {
	sum := sha256.Sum256(payload)
	return hex.EncodeToString(sum[:])
}
