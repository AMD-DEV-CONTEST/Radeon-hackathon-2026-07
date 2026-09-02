package evidencefabric

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"net/url"
	"sort"
	"strings"
	"time"
)

const SchemaVersion = "signalforge/evidence-fabric/v1"

type AuthorityClass string

const (
	AuthorityA0 AuthorityClass = "A0"
	AuthorityA1 AuthorityClass = "A1"
	AuthorityA2 AuthorityClass = "A2"
	AuthorityA3 AuthorityClass = "A3"
	AuthorityA4 AuthorityClass = "A4"
	AuthorityA5 AuthorityClass = "A5"
)

type RightsState string

const (
	RightsPublicDataReviewed RightsState = "public_data_reuse_reviewed"
	RightsPublicAPITerms     RightsState = "public_api_terms_bound"
	RightsPublicAuthorial    RightsState = "public_web_authorial_only"
	RightsPublicMetadata     RightsState = "public_metadata_only"
	RightsRestricted         RightsState = "restricted_reference"
	RightsQuarantined        RightsState = "quarantined"
)

type RetrievalMode string

const (
	RetrievalNone       RetrievalMode = "none"
	RetrievalLexical    RetrievalMode = "lexical"
	RetrievalHybrid     RetrievalMode = "hybrid_candidate"
	RetrievalResolution RetrievalMode = "resolution_only"
)

type HyDEPolicy string

const (
	HyDENone        HyDEPolicy = "none"
	HyDEConditional HyDEPolicy = "conditional_candidate_only"
)

type RetrievalProfile struct {
	SchemaVersion      string           `json:"schema_version"`
	ProfileID          string           `json:"profile_id"`
	RoleID             string           `json:"role_id"`
	Version            string           `json:"version"`
	Mode               RetrievalMode    `json:"mode"`
	AllowedAuthorities []AuthorityClass `json:"allowed_authorities,omitempty"`
	AllowedRights      []RightsState    `json:"allowed_rights,omitempty"`
	AllowedSourceKinds []string         `json:"allowed_source_kinds,omitempty"`
	ClaimClasses       []string         `json:"claim_classes,omitempty"`
	ToolAllowlist      []string         `json:"tool_allowlist,omitempty"`
	CompanyRequired    bool             `json:"company_required"`
	AsOfRequired       bool             `json:"as_of_required"`
	HyDE               HyDEPolicy       `json:"hyde_policy"`
	CandidateBudget    int              `json:"candidate_budget"`
	ContextTokenBudget int              `json:"context_token_budget"`
}

type PublicSource struct {
	SchemaVersion string         `json:"schema_version"`
	SourceID      string         `json:"source_id"`
	Name          string         `json:"name"`
	Publisher     string         `json:"publisher"`
	BaseURL       string         `json:"base_url"`
	AccessClass   string         `json:"access_class"`
	Authority     AuthorityClass `json:"authority"`
	Rights        RightsState    `json:"rights_state"`
	SourceKinds   []string       `json:"source_kinds"`
	PrimaryRoles  []string       `json:"primary_roles"`
	TemporalRule  string         `json:"temporal_rule"`
	StorageRule   string         `json:"storage_rule"`
	RateLimitRule string         `json:"rate_limit_rule"`
}

type EvidenceRecord struct {
	SchemaVersion string         `json:"schema_version"`
	EvidenceID    string         `json:"evidence_id"`
	SourceID      string         `json:"source_id"`
	SourceKind    string         `json:"source_kind"`
	CompanyID     string         `json:"company_id,omitempty"`
	SecurityID    string         `json:"security_id,omitempty"`
	Authority     AuthorityClass `json:"authority"`
	Rights        RightsState    `json:"rights_state"`
	PublishedAt   time.Time      `json:"published_at"`
	AvailableAt   time.Time      `json:"available_at"`
	ValidFrom     *time.Time     `json:"valid_from,omitempty"`
	ValidTo       *time.Time     `json:"valid_to,omitempty"`
	Lifecycle     string         `json:"lifecycle"`
	Locator       string         `json:"locator"`
	ContentHash   string         `json:"content_sha256"`
	Text          string         `json:"text,omitempty"`
}

type ContextRequest struct {
	SchemaVersion string    `json:"schema_version"`
	RequestID     string    `json:"request_id"`
	RunID         string    `json:"run_id"`
	RoleID        string    `json:"role_id"`
	Query         string    `json:"query"`
	CompanyIDs    []string  `json:"company_ids,omitempty"`
	AsOf          time.Time `json:"as_of"`
	ClaimClasses  []string  `json:"claim_classes,omitempty"`
	MaxCandidates int       `json:"max_candidates"`
}

type EvidenceCandidate struct {
	EvidenceID string  `json:"evidence_id"`
	Score      float64 `json:"score"`
	Rank       int     `json:"rank"`
}

type EvidenceBundle struct {
	SchemaVersion string              `json:"schema_version"`
	BundleID      string              `json:"bundle_id"`
	RequestID     string              `json:"request_id"`
	RunID         string              `json:"run_id"`
	RoleID        string              `json:"role_id"`
	AsOf          time.Time           `json:"as_of"`
	Candidates    []EvidenceCandidate `json:"candidates"`
	Missing       []string            `json:"missing,omitempty"`
	Warnings      []string            `json:"warnings,omitempty"`
	Degraded      bool                `json:"degraded"`
}

type GraphNode struct {
	NodeID     string `json:"node_id"`
	EntityType string `json:"entity_type"`
}

type GraphEdge struct {
	EdgeID      string     `json:"edge_id"`
	FromNodeID  string     `json:"from_node_id"`
	ToNodeID    string     `json:"to_node_id"`
	Relation    string     `json:"relation"`
	EvidenceIDs []string   `json:"evidence_ids"`
	ValidFrom   *time.Time `json:"valid_from,omitempty"`
	ValidTo     *time.Time `json:"valid_to,omitempty"`
	Confidence  string     `json:"confidence"`
}

type GraphPath struct {
	SchemaVersion string      `json:"schema_version"`
	PathID        string      `json:"path_id"`
	RoleID        string      `json:"role_id"`
	AsOf          time.Time   `json:"as_of"`
	Nodes         []GraphNode `json:"nodes"`
	Edges         []GraphEdge `json:"edges"`
}

type HyDETrace struct {
	SchemaVersion              string `json:"schema_version"`
	TraceID                    string `json:"trace_id"`
	RoleID                     string `json:"role_id"`
	OriginalQuerySHA256        string `json:"original_query_sha256"`
	HypothesisSHA256           string `json:"hypothesis_sha256"`
	UsedForCandidateGeneration bool   `json:"used_for_candidate_generation"`
	DiscardedBeforeCompilation bool   `json:"discarded_before_compilation"`
	EvidenceAuthority          bool   `json:"evidence_authority"`
}

func (profile RetrievalProfile) Validate() error {
	if profile.SchemaVersion != SchemaVersion || !safeID(profile.ProfileID) ||
		!safeID(profile.RoleID) || strings.TrimSpace(profile.Version) == "" {
		return errors.New("invalid retrieval profile identity")
	}
	switch profile.Mode {
	case RetrievalNone, RetrievalLexical, RetrievalHybrid, RetrievalResolution:
	default:
		return fmt.Errorf("invalid retrieval mode %q", profile.Mode)
	}
	switch profile.HyDE {
	case HyDENone, HyDEConditional:
	default:
		return fmt.Errorf("invalid HyDE policy %q", profile.HyDE)
	}
	if profile.Mode == RetrievalNone {
		if profile.HyDE != HyDENone || profile.CandidateBudget != 0 {
			return errors.New("retrieval-disabled profile cannot use HyDE or candidates")
		}
		return nil
	}
	if len(profile.AllowedAuthorities) == 0 || len(profile.AllowedRights) == 0 ||
		len(profile.AllowedSourceKinds) == 0 || profile.CandidateBudget <= 0 ||
		profile.ContextTokenBudget <= 0 {
		return errors.New("active retrieval profile is incomplete")
	}
	if containsRights(profile.AllowedRights, RightsRestricted) ||
		containsRights(profile.AllowedRights, RightsQuarantined) {
		return errors.New("active retrieval profile cannot authorize restricted or quarantined rights")
	}
	if profile.HyDE == HyDEConditional && profile.Mode != RetrievalHybrid {
		return errors.New("conditional HyDE requires hybrid candidate mode")
	}
	return uniqueStrings(profile.AllowedSourceKinds, profile.ClaimClasses, profile.ToolAllowlist)
}

func (source PublicSource) Validate() error {
	if source.SchemaVersion != SchemaVersion || !safeID(source.SourceID) ||
		strings.TrimSpace(source.Name) == "" || strings.TrimSpace(source.Publisher) == "" {
		return errors.New("invalid public source identity")
	}
	parsed, err := url.Parse(source.BaseURL)
	if err != nil || parsed.Scheme != "https" || parsed.Host == "" {
		return errors.New("public source requires an absolute HTTPS URL")
	}
	if !validAuthority(source.Authority) || !validRights(source.Rights) {
		return errors.New("invalid source authority or rights state")
	}
	if len(source.SourceKinds) == 0 || len(source.PrimaryRoles) == 0 ||
		source.TemporalRule == "" || source.StorageRule == "" || source.RateLimitRule == "" {
		return errors.New("public source policy is incomplete")
	}
	return uniqueStrings(source.SourceKinds, source.PrimaryRoles)
}

func (record EvidenceRecord) Validate(source PublicSource) error {
	if record.SchemaVersion != SchemaVersion || !safeID(record.EvidenceID) ||
		record.SourceID != source.SourceID || record.SourceKind == "" {
		return errors.New("invalid evidence identity")
	}
	if record.Authority != source.Authority || record.Rights != source.Rights {
		return errors.New("evidence authority or rights differs from source registry")
	}
	if record.AvailableAt.IsZero() || record.PublishedAt.IsZero() ||
		record.AvailableAt.Before(record.PublishedAt) {
		return errors.New("invalid evidence temporal state")
	}
	if record.ValidFrom != nil && record.ValidTo != nil && record.ValidTo.Before(*record.ValidFrom) {
		return errors.New("invalid evidence validity interval")
	}
	if record.Lifecycle != "active" && record.Lifecycle != "superseded" &&
		record.Lifecycle != "quarantined" && record.Lifecycle != "deleted" {
		return errors.New("invalid evidence lifecycle")
	}
	if strings.TrimSpace(record.Locator) == "" || len(record.ContentHash) != 64 {
		return errors.New("evidence locator and SHA-256 are required")
	}
	if _, err := hex.DecodeString(record.ContentHash); err != nil {
		return errors.New("invalid evidence content SHA-256")
	}
	if record.Text != "" {
		sum := sha256.Sum256([]byte(record.Text))
		if hex.EncodeToString(sum[:]) != record.ContentHash {
			return errors.New("evidence text does not match content SHA-256")
		}
	}
	return nil
}

func (request ContextRequest) Validate(profile RetrievalProfile) error {
	if request.SchemaVersion != SchemaVersion || !safeID(request.RequestID) ||
		!safeID(request.RunID) || request.RoleID != profile.RoleID {
		return errors.New("invalid context request identity")
	}
	if profile.Mode == RetrievalNone {
		return errors.New("role is not authorized to retrieve evidence")
	}
	if strings.TrimSpace(request.Query) == "" || request.MaxCandidates <= 0 ||
		request.MaxCandidates > profile.CandidateBudget {
		return errors.New("invalid context request query or candidate budget")
	}
	if profile.CompanyRequired && len(request.CompanyIDs) == 0 {
		return errors.New("retrieval profile requires a company")
	}
	if profile.AsOfRequired && request.AsOf.IsZero() {
		return errors.New("retrieval profile requires as_of")
	}
	if !subset(request.ClaimClasses, profile.ClaimClasses) {
		return errors.New("request contains an unauthorized claim class")
	}
	return nil
}

func (path GraphPath) Validate(allowedRelations map[string]bool) error {
	if path.SchemaVersion != SchemaVersion || !safeID(path.PathID) ||
		!safeID(path.RoleID) || path.AsOf.IsZero() || len(path.Nodes) == 0 {
		return errors.New("invalid graph path identity")
	}
	nodes := map[string]bool{}
	for _, node := range path.Nodes {
		if !safeID(node.NodeID) || !safeID(node.EntityType) || nodes[node.NodeID] {
			return errors.New("invalid or duplicate graph node")
		}
		nodes[node.NodeID] = true
	}
	for _, edge := range path.Edges {
		if !safeID(edge.EdgeID) || !nodes[edge.FromNodeID] || !nodes[edge.ToNodeID] ||
			!allowedRelations[edge.Relation] || len(edge.EvidenceIDs) == 0 {
			return errors.New("invalid or unauthorized graph edge")
		}
		if edge.ValidFrom != nil && edge.ValidFrom.After(path.AsOf) {
			return errors.New("future graph edge")
		}
		if edge.ValidTo != nil && !edge.ValidTo.After(path.AsOf) {
			return errors.New("expired graph edge")
		}
	}
	return nil
}

func (trace HyDETrace) Validate(profile RetrievalProfile) error {
	if trace.SchemaVersion != SchemaVersion || !safeID(trace.TraceID) ||
		trace.RoleID != profile.RoleID || len(trace.OriginalQuerySHA256) != 64 ||
		len(trace.HypothesisSHA256) != 64 {
		return errors.New("invalid HyDE trace")
	}
	if profile.HyDE != HyDEConditional || !trace.UsedForCandidateGeneration ||
		!trace.DiscardedBeforeCompilation || trace.EvidenceAuthority {
		return errors.New("HyDE must remain conditional, ephemeral, and non-authoritative")
	}
	return nil
}

func safeID(value string) bool {
	if value == "" || len(value) > 160 {
		return false
	}
	for _, char := range value {
		if (char >= 'a' && char <= 'z') || (char >= 'A' && char <= 'Z') ||
			(char >= '0' && char <= '9') || strings.ContainsRune("-._/:", char) {
			continue
		}
		return false
	}
	return true
}

func validAuthority(value AuthorityClass) bool {
	return value >= AuthorityA0 && value <= AuthorityA5
}

func validRights(value RightsState) bool {
	switch value {
	case RightsPublicDataReviewed, RightsPublicAPITerms, RightsPublicAuthorial,
		RightsPublicMetadata, RightsRestricted, RightsQuarantined:
		return true
	default:
		return false
	}
}

func containsRights(values []RightsState, target RightsState) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func subset(values, allowed []string) bool {
	index := map[string]bool{}
	for _, value := range allowed {
		index[value] = true
	}
	for _, value := range values {
		if !index[value] {
			return false
		}
	}
	return true
}

func uniqueStrings(groups ...[]string) error {
	for _, values := range groups {
		seen := map[string]bool{}
		for _, value := range values {
			if strings.TrimSpace(value) == "" || seen[value] {
				return errors.New("empty or duplicate policy value")
			}
			seen[value] = true
		}
	}
	return nil
}

func sortedUnique(values []string) []string {
	seen := map[string]bool{}
	for _, value := range values {
		if value != "" {
			seen[value] = true
		}
	}
	result := make([]string, 0, len(seen))
	for value := range seen {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}
