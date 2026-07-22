package contextcompiler

import (
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

type Policy struct {
	AsOf           time.Time     `json:"as_of"`
	MaxEvidenceAge time.Duration `json:"max_evidence_age"`
	TokenBudget    int           `json:"token_budget"`
	CharsPerToken  int           `json:"chars_per_token"`
	PrimarySources []string      `json:"primary_sources"`
}

type CompiledContext struct {
	RunID               string                  `json:"run_id"`
	AsOf                time.Time               `json:"as_of"`
	Findings            []contracts.Finding     `json:"findings"`
	Evidence            []contracts.EvidenceRef `json:"evidence"`
	Conflicts           []string                `json:"conflicts,omitempty"`
	MissingEvidence     []string                `json:"missing_evidence,omitempty"`
	StaleEvidence       []string                `json:"stale_evidence,omitempty"`
	DroppedForBudget    []string                `json:"dropped_for_budget,omitempty"`
	EstimatedTokenCount int                     `json:"estimated_token_count"`
}

type rankedFinding struct {
	finding contracts.Finding
	primary bool
	order   int
}

func Compile(packets []contracts.ContextPacket, policy Policy) (CompiledContext, error) {
	if len(packets) == 0 {
		return CompiledContext{}, errors.New("at least one context packet is required")
	}
	if policy.AsOf.IsZero() || policy.TokenBudget <= 0 {
		return CompiledContext{}, errors.New("as_of and a positive token budget are required")
	}
	if policy.CharsPerToken <= 0 {
		policy.CharsPerToken = 4
	}

	result := CompiledContext{RunID: packets[0].RunID, AsOf: policy.AsOf}
	evidenceByID := make(map[string]contracts.EvidenceRef)
	evidencePrimary := make(map[string]bool)
	claimByID := make(map[string]contracts.Finding)
	ranked := make([]rankedFinding, 0)
	conflicts := make(map[string]bool)
	missing := make(map[string]bool)
	stale := make(map[string]bool)

	for packetIndex, packet := range packets {
		if err := contracts.ValidateContextPacket(packet); err != nil {
			return CompiledContext{}, fmt.Errorf("packet %q: %w", packet.PacketID, err)
		}
		if packet.RunID != result.RunID {
			return CompiledContext{}, fmt.Errorf("packet %q belongs to a different run", packet.PacketID)
		}
		if packet.Scope.AsOf.After(policy.AsOf) {
			return CompiledContext{}, fmt.Errorf("packet %q contains future-scoped context", packet.PacketID)
		}
		for _, item := range packet.MissingEvidence {
			missing[item] = true
		}
		for _, item := range packet.Conflicts {
			conflicts[item] = true
		}
		for _, evidence := range packet.Evidence {
			if evidence.EvidenceID == "" || evidence.ContentSHA == "" || evidence.AsOf.IsZero() {
				return CompiledContext{}, fmt.Errorf("packet %q contains malformed evidence", packet.PacketID)
			}
			if evidence.AsOf.After(policy.AsOf) {
				return CompiledContext{}, fmt.Errorf("evidence %q is from the future", evidence.EvidenceID)
			}
			if existing, ok := evidenceByID[evidence.EvidenceID]; ok && existing.ContentSHA != evidence.ContentSHA {
				conflicts["evidence_identity:"+evidence.EvidenceID] = true
				continue
			}
			evidenceByID[evidence.EvidenceID] = evidence
			evidencePrimary[evidence.EvidenceID] = isPrimary(evidence.SourceType, policy.PrimarySources)
			if policy.MaxEvidenceAge > 0 && policy.AsOf.Sub(evidence.AsOf) > policy.MaxEvidenceAge {
				stale[evidence.EvidenceID] = true
			}
		}
		for findingIndex, finding := range packet.Findings {
			if existing, ok := claimByID[finding.ClaimID]; ok {
				if existing.Statement != finding.Statement || existing.ClaimType != finding.ClaimType {
					conflicts["claim_identity:"+finding.ClaimID] = true
				}
				continue
			}
			claimByID[finding.ClaimID] = finding
			primary := false
			for _, ref := range finding.EvidenceRefs {
				primary = primary || evidencePrimary[ref]
			}
			ranked = append(ranked, rankedFinding{finding: finding, primary: primary, order: packetIndex*1000 + findingIndex})
		}
	}

	// Facts with primary evidence rank first, followed by calculations and other
	// supported claims. Stable source order resolves ties without rewriting text.
	sort.SliceStable(ranked, func(i, j int) bool {
		left, right := rank(ranked[i]), rank(ranked[j])
		if left != right {
			return left < right
		}
		return ranked[i].order < ranked[j].order
	})

	usedChars := 0
	for _, item := range ranked {
		cost := len(item.finding.Statement) + 32
		if (usedChars+cost+policy.CharsPerToken-1)/policy.CharsPerToken > policy.TokenBudget {
			result.DroppedForBudget = append(result.DroppedForBudget, item.finding.ClaimID)
			continue
		}
		result.Findings = append(result.Findings, item.finding)
		usedChars += cost
	}
	result.EstimatedTokenCount = (usedChars + policy.CharsPerToken - 1) / policy.CharsPerToken

	for id, evidence := range evidenceByID {
		if referencesEvidence(result.Findings, id) {
			result.Evidence = append(result.Evidence, evidence)
		}
	}
	sort.Slice(result.Evidence, func(i, j int) bool { return result.Evidence[i].EvidenceID < result.Evidence[j].EvidenceID })
	result.Conflicts = sortedKeys(conflicts)
	result.MissingEvidence = sortedKeys(missing)
	result.StaleEvidence = sortedKeys(stale)
	return result, nil
}

func rank(item rankedFinding) int {
	if item.finding.ClaimType == contracts.ClaimFact && item.primary {
		return 0
	}
	if item.finding.ClaimType == contracts.ClaimCalculation {
		return 1
	}
	if item.finding.ClaimType == contracts.ClaimFact {
		return 2
	}
	if item.finding.ClaimType == contracts.ClaimInference {
		return 3
	}
	return 4
}

func isPrimary(source string, primary []string) bool {
	for _, value := range primary {
		if strings.EqualFold(source, value) {
			return true
		}
	}
	return false
}

func referencesEvidence(findings []contracts.Finding, id string) bool {
	for _, finding := range findings {
		for _, ref := range finding.EvidenceRefs {
			if ref == id {
				return true
			}
		}
	}
	return false
}

func sortedKeys(values map[string]bool) []string {
	result := make([]string, 0, len(values))
	for value := range values {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}
