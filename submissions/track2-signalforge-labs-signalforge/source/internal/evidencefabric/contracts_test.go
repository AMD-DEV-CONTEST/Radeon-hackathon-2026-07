package evidencefabric

import (
	"crypto/sha256"
	"encoding/hex"
	"testing"
	"time"
)

func TestResolverFailsClosedAcrossRightsTimeCompanyAndLifecycle(t *testing.T) {
	asOf := time.Date(2026, 7, 23, 12, 0, 0, 0, time.UTC)
	source := testSource()
	records := []EvidenceRecord{
		testRecord("evidence-msft", source, "msft", "Microsoft disclosed cloud strategy and segment changes.", asOf.Add(-time.Hour)),
		testRecord("evidence-nvda", source, "nvda", "NVIDIA disclosed data center demand and supply risks.", asOf.Add(-time.Hour)),
		testRecord("evidence-future", source, "msft", "Microsoft future filing.", asOf.Add(time.Hour)),
	}
	records[2].PublishedAt = asOf.Add(time.Hour)
	resolver, err := NewResolver([]PublicSource{source}, records)
	if err != nil {
		t.Fatal(err)
	}
	profile := testProfile()
	request := ContextRequest{
		SchemaVersion: SchemaVersion, RequestID: "request-1", RunID: "run-1",
		RoleID: profile.RoleID, Query: "Microsoft cloud strategy", CompanyIDs: []string{"msft"},
		AsOf: asOf, ClaimClasses: []string{"business_fact"}, MaxCandidates: 5,
	}
	bundle, err := resolver.Resolve(profile, request)
	if err != nil {
		t.Fatal(err)
	}
	if len(bundle.Candidates) != 1 || bundle.Candidates[0].EvidenceID != "evidence-msft" {
		t.Fatalf("unexpected candidates: %+v", bundle.Candidates)
	}
	quarantined, err := resolver.Quarantine("evidence-msft")
	if err != nil {
		t.Fatal(err)
	}
	bundle, err = quarantined.Resolve(profile, request)
	if err != nil {
		t.Fatal(err)
	}
	if len(bundle.Candidates) != 0 || len(bundle.Missing) == 0 {
		t.Fatalf("quarantined evidence leaked: %+v", bundle)
	}
}

func TestProfilesRejectRestrictedRightsAndUnauthorizedHyDE(t *testing.T) {
	profile := testProfile()
	profile.AllowedRights = append(profile.AllowedRights, RightsRestricted)
	if err := profile.Validate(); err == nil {
		t.Fatal("expected restricted rights rejection")
	}
	profile = testProfile()
	profile.Mode = RetrievalLexical
	profile.HyDE = HyDEConditional
	if err := profile.Validate(); err == nil {
		t.Fatal("expected HyDE mode rejection")
	}
}

func TestEvidenceHashParityAndGraphTemporalPolicy(t *testing.T) {
	source := testSource()
	record := testRecord("evidence-1", source, "msft", "Exact source-linked text.", time.Now().UTC())
	record.ContentHash = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	if err := record.Validate(source); err == nil {
		t.Fatal("expected content hash mismatch")
	}
	asOf := time.Date(2026, 7, 23, 0, 0, 0, 0, time.UTC)
	future := asOf.Add(time.Hour)
	path := GraphPath{
		SchemaVersion: SchemaVersion, PathID: "path-1", RoleID: "risk-contrarian/v1", AsOf: asOf,
		Nodes: []GraphNode{{NodeID: "company-msft", EntityType: "company"}, {NodeID: "event-1", EntityType: "event"}},
		Edges: []GraphEdge{{
			EdgeID: "edge-1", FromNodeID: "company-msft", ToNodeID: "event-1",
			Relation: "EXPOSED_TO", EvidenceIDs: []string{"evidence-1"}, ValidFrom: &future,
			Confidence: "direct",
		}},
	}
	if err := path.Validate(map[string]bool{"EXPOSED_TO": true}); err == nil {
		t.Fatal("expected future graph edge rejection")
	}
}

func TestHyDETraceIsEphemeralAndNonAuthoritative(t *testing.T) {
	profile := testProfile()
	query := sha256.Sum256([]byte("query"))
	hypothesis := sha256.Sum256([]byte("hypothesis"))
	trace := HyDETrace{
		SchemaVersion: SchemaVersion, TraceID: "hyde-1", RoleID: profile.RoleID,
		OriginalQuerySHA256: hex.EncodeToString(query[:]), HypothesisSHA256: hex.EncodeToString(hypothesis[:]),
		UsedForCandidateGeneration: true, DiscardedBeforeCompilation: true,
	}
	if err := trace.Validate(profile); err != nil {
		t.Fatal(err)
	}
	trace.EvidenceAuthority = true
	if err := trace.Validate(profile); err == nil {
		t.Fatal("expected authoritative HyDE rejection")
	}
}

func testProfile() RetrievalProfile {
	return RetrievalProfile{
		SchemaVersion: SchemaVersion, ProfileID: "business-strategy/v1.0.0",
		RoleID: "business-strategy/v1", Version: "1.0.0", Mode: RetrievalHybrid,
		AllowedAuthorities: []AuthorityClass{AuthorityA0, AuthorityA1, AuthorityA2},
		AllowedRights:      []RightsState{RightsPublicDataReviewed, RightsPublicAuthorial},
		AllowedSourceKinds: []string{"filing", "authorial_context"},
		ClaimClasses:       []string{"business_fact"}, ToolAllowlist: []string{"evidence.retrieve"},
		CompanyRequired: true, AsOfRequired: true, HyDE: HyDEConditional,
		CandidateBudget: 10, ContextTokenBudget: 3000,
	}
}

func testSource() PublicSource {
	return PublicSource{
		SchemaVersion: SchemaVersion, SourceID: "sec-filings", Name: "SEC filings",
		Publisher: "US SEC", BaseURL: "https://www.sec.gov/edgar", AccessClass: "public_no_key",
		Authority: AuthorityA0, Rights: RightsPublicDataReviewed,
		SourceKinds: []string{"filing"}, PrimaryRoles: []string{"business-strategy/v1"},
		TemporalRule: "available_at", StorageRule: "content_addressed",
		RateLimitRule: "identified_bounded_client",
	}
}

func testRecord(id string, source PublicSource, companyID, text string, availableAt time.Time) EvidenceRecord {
	sum := sha256.Sum256([]byte(text))
	return EvidenceRecord{
		SchemaVersion: SchemaVersion, EvidenceID: id, SourceID: source.SourceID,
		SourceKind: "filing", CompanyID: companyID, Authority: source.Authority, Rights: source.Rights,
		PublishedAt: availableAt.Add(-time.Minute), AvailableAt: availableAt, Lifecycle: "active",
		Locator: "https://www.sec.gov/Archives/example", ContentHash: hex.EncodeToString(sum[:]), Text: text,
	}
}
