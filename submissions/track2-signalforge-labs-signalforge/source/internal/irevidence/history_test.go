package irevidence

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/retrieval"
)

func TestHistoricalChangesRequireBothVersionsAndSeparateInference(t *testing.T) {
	changes, err := DetectSectionChanges("old-evidence", "new-evidence",
		[]SectionVersion{{SectionID: "strategy", Heading: "Strategy", Text: "Focus on cloud.", Locator: "p:1"}},
		[]SectionVersion{{SectionID: "strategy", Heading: "Strategy", Text: "Focus on cloud and AI.", Locator: "p:2"}},
	)
	if err != nil || len(changes) != 1 || changes[0].Kind != ChangeModified {
		t.Fatalf("unexpected changes %+v: %v", changes, err)
	}
	claim := HistoricalChangeClaim{
		ClaimID: "claim-1", Observation: "The strategy section added AI language.",
		Inference:     "Management may be broadening product emphasis.",
		OldEvidenceID: "old-evidence", NewEvidenceID: "new-evidence", ChangeIDs: []string{"strategy"},
	}
	if err := ValidateHistoricalChangeClaim(claim, map[string]bool{"old-evidence": true, "new-evidence": true}); err != nil {
		t.Fatal(err)
	}
	if err := ValidateHistoricalChangeClaim(claim, map[string]bool{"new-evidence": true}); err == nil {
		t.Fatal("one-sided historical claim must fail")
	}
}

func TestTimelineAuthorityRankingAndSECPrecedence(t *testing.T) {
	now := time.Date(2026, 7, 23, 12, 0, 0, 0, time.UTC)
	document := validDocument()
	document.EventID = "earnings-2025"
	document.Speaker = "Example CEO"
	timeline, err := BuildTimeline([]Document{document}, map[string][]string{document.DocumentID: {"evidence-1"}})
	if err != nil || len(timeline) != 1 || len(timeline[0].Speakers) != 1 {
		t.Fatalf("unexpected timeline %+v: %v", timeline, err)
	}
	tierB := irRetrievalChunk(now, "tier-b", "B", false, "Issuer-reported result.")
	tierE := irRetrievalChunk(now, "tier-e", "E", true, "Promotional market leadership claim.")
	hits, err := AuthorityFilterAndRank([]RetrievalCandidate{
		{Hit: retrieval.Hit{Chunk: tierE, Score: 0.99}, RequiredTier: "B"},
		{Hit: retrieval.Hit{Chunk: tierB, Score: 0.50}, RequiredTier: "B"},
	}, now, 5)
	if err != nil || len(hits) != 1 || hits[0].Chunk.ChunkID != "tier-b" {
		t.Fatalf("authority filtering failed %+v: %v", hits, err)
	}
	if NonSECMaySupportClaim(true, document, ClaimAuditedFinancialFact, now) {
		t.Fatal("non-SEC evidence must not override available SEC authority")
	}
}

func TestProductContextShowsDegradedAndConflictStates(t *testing.T) {
	now := time.Date(2026, 7, 23, 12, 0, 0, 0, time.UTC)
	packet := ProductContextPacket{
		SchemaVersion: "signalforge/ir-product-context/v1", PacketID: "packet", RunID: "run",
		RoleID: "evidence-critic/v1", AsOf: now,
		Evidence: []contracts.EvidenceRef{{
			EvidenceID: "evidence-1", SourceType: "official_investor_relations",
			Locator: "html:p=1", ContentSHA: "abc", AsOf: now,
		}, {
			EvidenceID: "evidence-0", SourceType: "official_investor_relations",
			Locator: "html:p=0", ContentSHA: "def", AsOf: now.Add(-24 * time.Hour),
		}},
		Sources: []ProductSource{{
			EvidenceID: "evidence-1", SourceURI: "https://example.com/investors/results",
			Locator: "html:p=1", AuthorityTier: "B",
		}},
		Changes: []SectionChange{{
			SectionID: "strategy", Kind: ChangeModified, Observation: "language changed",
			OldLocator: "html:p=0", NewLocator: "html:p=1",
			OldEvidence: "evidence-0", NewEvidence: "evidence-1",
		}},
		Timeline: []TimelineEvent{{
			EventID: "strategy-update", CompanyID: "sec-cik:0000789019",
			OccurredAt: now.Add(-time.Hour), DocumentIDs: []string{"document-1"},
			EvidenceIDs: []string{"evidence-1"},
		}},
		ArchiveGaps: []string{"FY2021 investor-day deck unavailable"},
		Conflicts:   []string{"IR copy differs from filed exhibit; SEC version controls"},
	}
	if err := ValidateProductContextPacket(packet); err != nil {
		t.Fatal(err)
	}
	invalidChange := packet
	invalidChange.Changes = append([]SectionChange(nil), packet.Changes...)
	invalidChange.Changes[0].OldEvidence = "missing"
	if err := ValidateProductContextPacket(invalidChange); err == nil {
		t.Fatal("one-sided historical change must fail")
	}
	invalidTimeline := packet
	invalidTimeline.Timeline = append([]TimelineEvent(nil), packet.Timeline...)
	invalidTimeline.Timeline[0].OccurredAt = now.Add(time.Hour)
	if err := ValidateProductContextPacket(invalidTimeline); err == nil {
		t.Fatal("future timeline event must fail")
	}
	empty := ProductContextPacket{
		SchemaVersion: packet.SchemaVersion, PacketID: "empty", RunID: "run",
		RoleID: "business-strategy/v1", AsOf: now,
	}
	if err := ValidateProductContextPacket(empty); err == nil {
		t.Fatal("empty context without visible degradation must fail")
	}
}

func TestHistoricalJourneyFixtureCoversFourResearchClusters(t *testing.T) {
	payload, err := os.ReadFile("../../fixtures/ir-historical-change-journeys.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		SchemaVersion string `json:"schema_version"`
		Journeys      []struct {
			JourneyID        string   `json:"journey_id"`
			ResearchCluster  string   `json:"research_cluster"`
			RequiredEvidence []string `json:"required_evidence"`
			RequiredControls []string `json:"required_controls"`
		} `json:"journeys"`
	}
	if err := json.Unmarshal(payload, &fixture); err != nil {
		t.Fatal(err)
	}
	if fixture.SchemaVersion != "signalforge/ir-historical-change-journeys/v1" || len(fixture.Journeys) != 4 {
		t.Fatalf("unexpected fixture %+v", fixture)
	}
	seen := make(map[string]bool)
	for _, journey := range fixture.Journeys {
		if journey.JourneyID == "" || len(journey.RequiredEvidence) < 2 || len(journey.RequiredControls) < 2 {
			t.Fatalf("incomplete historical journey %+v", journey)
		}
		seen[journey.ResearchCluster] = true
	}
	for _, cluster := range []string{"company_history", "strategy_evolution", "governance_change", "earnings_explanation"} {
		if !seen[cluster] {
			t.Fatalf("missing cluster %s", cluster)
		}
	}
}

func TestIRAdversarialFixtureCoversIsolationAndFailureClasses(t *testing.T) {
	payload, err := os.ReadFile("../../fixtures/ir-retrieval-adversarial-cases.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		SchemaVersion string `json:"schema_version"`
		Cases         []struct {
			CaseID          string `json:"case_id"`
			Kind            string `json:"kind"`
			Isolation       string `json:"isolation"`
			ExpectedControl string `json:"expected_control"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(payload, &fixture); err != nil {
		t.Fatal(err)
	}
	if fixture.SchemaVersion != "signalforge/ir-retrieval-adversarial/v1" || len(fixture.Cases) != 12 {
		t.Fatalf("unexpected adversarial fixture %+v", fixture)
	}
	kinds := make(map[string]bool)
	for _, item := range fixture.Cases {
		if item.CaseID == "" || item.Isolation == "" || item.ExpectedControl == "" {
			t.Fatalf("incomplete adversarial case %+v", item)
		}
		kinds[item.Kind] = true
	}
	for _, kind := range []string{
		"single_source", "multi_source", "historical_diff", "cross_document", "cross_company",
		"management_vs_sec", "superseded", "promotional", "missing_evidence", "abstention",
	} {
		if !kinds[kind] {
			t.Fatalf("missing adversarial kind %s", kind)
		}
	}
}

func irRetrievalChunk(now time.Time, id, tier string, promotional bool, text string) retrieval.Chunk {
	digest := sha256.Sum256([]byte(text))
	return retrieval.Chunk{
		SchemaVersion: retrieval.ChunkSchemaV1, ChunkID: id, DocumentID: "doc-" + id,
		CompanyID: "sec-cik:0000789019", EvidenceType: "investor_relations",
		DocumentType: "earnings_release", AuthorityTier: tier, Issuer: "Microsoft Corporation",
		Language: "en", RightsClass: "reference_only", Promotional: promotional,
		PublishedAt: now.Add(-24 * time.Hour), AvailableAt: now.Add(-24 * time.Hour), RetrievedAt: now,
		Section: "Results", Locator: "html:p=1", Text: text,
		SourceURI:      "https://www.microsoft.com/en-us/investor/default",
		DocumentSHA256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		ContentSHA256:  hex.EncodeToString(digest[:]), TokenEstimate: 10, ChunkingVersion: "test/v1",
	}
}
