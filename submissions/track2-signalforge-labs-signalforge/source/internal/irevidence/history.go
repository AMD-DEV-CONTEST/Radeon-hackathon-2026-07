package irevidence

import (
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/retrieval"
)

type SectionVersion struct {
	SectionID string `json:"section_id"`
	Heading   string `json:"heading"`
	Text      string `json:"text"`
	Locator   string `json:"locator"`
}

type ChangeKind string

const (
	ChangeAdded    ChangeKind = "added"
	ChangeRemoved  ChangeKind = "removed"
	ChangeModified ChangeKind = "modified"
)

type SectionChange struct {
	SectionID   string     `json:"section_id"`
	Kind        ChangeKind `json:"kind"`
	OldLocator  string     `json:"old_locator,omitempty"`
	NewLocator  string     `json:"new_locator,omitempty"`
	OldEvidence string     `json:"old_evidence_id,omitempty"`
	NewEvidence string     `json:"new_evidence_id,omitempty"`
	Observation string     `json:"observation"`
}

func DetectSectionChanges(oldEvidenceID, newEvidenceID string, oldSections, newSections []SectionVersion) ([]SectionChange, error) {
	if oldEvidenceID == "" || newEvidenceID == "" || oldEvidenceID == newEvidenceID {
		return nil, errors.New("distinct old and new evidence IDs are required")
	}
	index := func(values []SectionVersion) (map[string]SectionVersion, error) {
		result := make(map[string]SectionVersion, len(values))
		for _, value := range values {
			if value.SectionID == "" || value.Heading == "" || value.Locator == "" || result[value.SectionID].SectionID != "" {
				return nil, errors.New("sections require unique IDs, headings, and stable locators")
			}
			result[value.SectionID] = value
		}
		return result, nil
	}
	oldIndex, err := index(oldSections)
	if err != nil {
		return nil, err
	}
	newIndex, err := index(newSections)
	if err != nil {
		return nil, err
	}
	ids := make(map[string]bool)
	for id := range oldIndex {
		ids[id] = true
	}
	for id := range newIndex {
		ids[id] = true
	}
	ordered := make([]string, 0, len(ids))
	for id := range ids {
		ordered = append(ordered, id)
	}
	sort.Strings(ordered)
	changes := make([]SectionChange, 0)
	for _, id := range ordered {
		oldValue, oldExists := oldIndex[id]
		newValue, newExists := newIndex[id]
		switch {
		case !oldExists:
			changes = append(changes, SectionChange{
				SectionID: id, Kind: ChangeAdded, NewLocator: newValue.Locator,
				NewEvidence: newEvidenceID, Observation: "section added in the newer source",
			})
		case !newExists:
			changes = append(changes, SectionChange{
				SectionID: id, Kind: ChangeRemoved, OldLocator: oldValue.Locator,
				OldEvidence: oldEvidenceID, Observation: "section absent from the newer source",
			})
		case normalizeNarrative(oldValue.Text) != normalizeNarrative(newValue.Text):
			changes = append(changes, SectionChange{
				SectionID: id, Kind: ChangeModified, OldLocator: oldValue.Locator, NewLocator: newValue.Locator,
				OldEvidence: oldEvidenceID, NewEvidence: newEvidenceID,
				Observation: "section language changed between source versions",
			})
		}
	}
	return changes, nil
}

type HistoricalChangeClaim struct {
	ClaimID       string   `json:"claim_id"`
	Observation   string   `json:"observation"`
	Inference     string   `json:"inference,omitempty"`
	OldEvidenceID string   `json:"old_evidence_id"`
	NewEvidenceID string   `json:"new_evidence_id"`
	ChangeIDs     []string `json:"change_ids"`
}

func ValidateHistoricalChangeClaim(claim HistoricalChangeClaim, availableEvidence map[string]bool) error {
	if claim.ClaimID == "" || claim.Observation == "" || claim.OldEvidenceID == "" || claim.NewEvidenceID == "" ||
		claim.OldEvidenceID == claim.NewEvidenceID || len(claim.ChangeIDs) == 0 {
		return errors.New("historical change claim requires an observation, both source versions, and change IDs")
	}
	if !availableEvidence[claim.OldEvidenceID] || !availableEvidence[claim.NewEvidenceID] {
		return errors.New("historical change claim does not resolve both citations")
	}
	if claim.Inference != "" && strings.EqualFold(strings.TrimSpace(claim.Inference), strings.TrimSpace(claim.Observation)) {
		return errors.New("observation and inference must remain distinct")
	}
	return nil
}

type TimelineEvent struct {
	EventID      string    `json:"event_id"`
	CompanyID    string    `json:"company_id"`
	OccurredAt   time.Time `json:"occurred_at"`
	DocumentIDs  []string  `json:"document_ids"`
	EvidenceIDs  []string  `json:"evidence_ids"`
	Speakers     []string  `json:"speakers,omitempty"`
	FiscalPeriod string    `json:"fiscal_period,omitempty"`
}

func BuildTimeline(documents []Document, evidenceByDocument map[string][]string) ([]TimelineEvent, error) {
	grouped := make(map[string]*TimelineEvent)
	for _, document := range documents {
		if document.EventID == "" {
			continue
		}
		occurredAt := document.PublishedAt
		if document.EffectiveAt != nil {
			occurredAt = *document.EffectiveAt
		}
		event := grouped[document.EventID]
		if event == nil {
			event = &TimelineEvent{
				EventID: document.EventID, CompanyID: document.CompanyID, OccurredAt: occurredAt,
				FiscalPeriod: document.FiscalPeriod,
			}
			grouped[document.EventID] = event
		}
		if event.CompanyID != document.CompanyID {
			return nil, errors.New("timeline event cannot cross companies")
		}
		if occurredAt.Before(event.OccurredAt) {
			event.OccurredAt = occurredAt
		}
		if event.FiscalPeriod == "" {
			event.FiscalPeriod = document.FiscalPeriod
		} else if document.FiscalPeriod != "" && event.FiscalPeriod != document.FiscalPeriod {
			return nil, errors.New("timeline event cannot mix fiscal periods")
		}
		event.DocumentIDs = append(event.DocumentIDs, document.DocumentID)
		event.EvidenceIDs = append(event.EvidenceIDs, evidenceByDocument[document.DocumentID]...)
		if document.Speaker != "" {
			event.Speakers = append(event.Speakers, document.Speaker)
		}
	}
	result := make([]TimelineEvent, 0, len(grouped))
	for _, event := range grouped {
		event.DocumentIDs = compactStrings(event.DocumentIDs)
		event.EvidenceIDs = compactStrings(event.EvidenceIDs)
		event.Speakers = compactStrings(event.Speakers)
		if len(event.EvidenceIDs) == 0 {
			return nil, fmt.Errorf("event %q has no resolvable evidence", event.EventID)
		}
		result = append(result, *event)
	}
	sort.Slice(result, func(i, j int) bool {
		if result[i].OccurredAt.Equal(result[j].OccurredAt) {
			return result[i].EventID < result[j].EventID
		}
		return result[i].OccurredAt.Before(result[j].OccurredAt)
	})
	return result, nil
}

type RetrievalCandidate struct {
	Hit          retrieval.Hit `json:"hit"`
	RequiredTier string        `json:"required_tier,omitempty"`
}

func AuthorityFilterAndRank(candidates []RetrievalCandidate, asOf time.Time, topK int) ([]retrieval.Hit, error) {
	if asOf.IsZero() || topK < 1 {
		return nil, errors.New("as-of and positive topK are required")
	}
	eligible := make([]retrieval.Hit, 0)
	for _, candidate := range candidates {
		if candidate.RequiredTier != "" && authorityRank(candidate.RequiredTier) > authorityRank("E") {
			return nil, fmt.Errorf("unknown required authority tier %q", candidate.RequiredTier)
		}
		chunk := candidate.Hit.Chunk
		if err := retrieval.ValidateChunk(chunk); err != nil || chunk.AvailableAt.After(asOf) ||
			(chunk.SupersededAt != nil && !chunk.SupersededAt.After(asOf)) ||
			authorityRank(chunk.AuthorityTier) > authorityRank("E") {
			continue
		}
		if candidate.RequiredTier != "" && authorityRank(chunk.AuthorityTier) > authorityRank(candidate.RequiredTier) {
			continue
		}
		if chunk.Promotional && candidate.RequiredTier != "" && authorityRank(candidate.RequiredTier) <= authorityRank("B") {
			continue
		}
		eligible = append(eligible, candidate.Hit)
	}
	sort.SliceStable(eligible, func(i, j int) bool {
		left, right := eligible[i], eligible[j]
		if authorityRank(left.Chunk.AuthorityTier) != authorityRank(right.Chunk.AuthorityTier) {
			return authorityRank(left.Chunk.AuthorityTier) < authorityRank(right.Chunk.AuthorityTier)
		}
		if left.Score != right.Score {
			return left.Score > right.Score
		}
		return left.Chunk.ChunkID < right.Chunk.ChunkID
	})
	if len(eligible) > topK {
		eligible = eligible[:topK]
	}
	for index := range eligible {
		eligible[index].Rank = index + 1
	}
	return eligible, nil
}

type ProductContextPacket struct {
	SchemaVersion   string                  `json:"schema_version"`
	PacketID        string                  `json:"packet_id"`
	RunID           string                  `json:"run_id"`
	RoleID          string                  `json:"role_id"`
	AsOf            time.Time               `json:"as_of"`
	Evidence        []contracts.EvidenceRef `json:"evidence"`
	Sources         []ProductSource         `json:"sources,omitempty"`
	Changes         []SectionChange         `json:"changes,omitempty"`
	Timeline        []TimelineEvent         `json:"timeline,omitempty"`
	ArchiveGaps     []string                `json:"archive_gaps,omitempty"`
	Unavailable     []string                `json:"unavailable_classes,omitempty"`
	Conflicts       []string                `json:"conflicting_evidence,omitempty"`
	DegradedReasons []string                `json:"degraded_reasons,omitempty"`
}

type ProductSource struct {
	EvidenceID    string     `json:"evidence_id"`
	SourceURI     string     `json:"source_uri"`
	Locator       string     `json:"locator"`
	AuthorityTier string     `json:"authority_tier"`
	ChangedSince  *time.Time `json:"changed_since,omitempty"`
}

func ValidateProductContextPacket(packet ProductContextPacket) error {
	if packet.SchemaVersion != "signalforge/ir-product-context/v1" || packet.PacketID == "" ||
		packet.RunID == "" || packet.RoleID == "" || packet.AsOf.IsZero() {
		return errors.New("IR product context envelope is invalid")
	}
	seen := make(map[string]bool)
	for _, evidence := range packet.Evidence {
		if evidence.EvidenceID == "" || evidence.SourceType == "" || evidence.Locator == "" ||
			evidence.ContentSHA == "" || evidence.AsOf.After(packet.AsOf) || seen[evidence.EvidenceID] {
			return errors.New("IR product context contains invalid or duplicate evidence")
		}
		seen[evidence.EvidenceID] = true
	}
	sourceSeen := make(map[string]bool)
	for _, source := range packet.Sources {
		if !seen[source.EvidenceID] || !strings.HasPrefix(source.SourceURI, "https://") ||
			source.Locator == "" || authorityRank(source.AuthorityTier) > authorityRank("E") ||
			sourceSeen[source.EvidenceID] {
			return errors.New("IR product context contains an invalid source affordance")
		}
		sourceSeen[source.EvidenceID] = true
		if source.ChangedSince != nil && source.ChangedSince.After(packet.AsOf) {
			return errors.New("IR source change timestamp exceeds packet as-of")
		}
	}
	for _, change := range packet.Changes {
		if change.SectionID == "" || change.Observation == "" {
			return errors.New("IR product context contains an incomplete historical change")
		}
		switch change.Kind {
		case ChangeAdded:
			if change.NewLocator == "" || !seen[change.NewEvidence] || change.OldEvidence != "" {
				return errors.New("added IR section does not resolve its new evidence")
			}
		case ChangeRemoved:
			if change.OldLocator == "" || !seen[change.OldEvidence] || change.NewEvidence != "" {
				return errors.New("removed IR section does not resolve its old evidence")
			}
		case ChangeModified:
			if change.OldLocator == "" || change.NewLocator == "" ||
				!seen[change.OldEvidence] || !seen[change.NewEvidence] ||
				change.OldEvidence == change.NewEvidence {
				return errors.New("modified IR section must resolve distinct source versions")
			}
		default:
			return errors.New("IR product context contains an unknown historical change kind")
		}
	}
	eventSeen := make(map[string]bool)
	for _, event := range packet.Timeline {
		if event.EventID == "" || event.CompanyID == "" || event.OccurredAt.IsZero() ||
			event.OccurredAt.After(packet.AsOf) || len(event.DocumentIDs) == 0 ||
			len(event.EvidenceIDs) == 0 || eventSeen[event.EventID] {
			return errors.New("IR product context contains an invalid timeline event")
		}
		eventSeen[event.EventID] = true
		for _, evidenceID := range event.EvidenceIDs {
			if !seen[evidenceID] {
				return errors.New("IR timeline event references unavailable evidence")
			}
		}
	}
	if len(packet.Evidence) == 0 && len(packet.DegradedReasons) == 0 && len(packet.Unavailable) == 0 {
		return errors.New("empty IR context must disclose a degraded or unavailable state")
	}
	return nil
}

func NonSECMaySupportClaim(secAvailable bool, document Document, claim ClaimClass, asOf time.Time) bool {
	if secAvailable && (claim == ClaimRegulatoryFact || claim == ClaimAuditedFinancialFact) {
		return false
	}
	return CanSupport(document, claim, asOf)
}

func authorityRank(tier string) int {
	switch tier {
	case "A":
		return 1
	case "B":
		return 2
	case "C":
		return 3
	case "D":
		return 4
	case "E":
		return 5
	default:
		return 100
	}
}

func normalizeNarrative(value string) string {
	return strings.Join(strings.Fields(strings.ToLower(value)), " ")
}
