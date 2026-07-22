package contextcompiler

import (
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

func TestCompileDeduplicatesAndPreservesConflict(t *testing.T) {
	now := time.Date(2026, 7, 21, 0, 0, 0, 0, time.UTC)
	first := packet(now, "packet-1", "Revenue was 10.", "sha-a")
	second := packet(now, "packet-2", "Revenue was 12.", "sha-b")
	second.Findings[0].ClaimID = first.Findings[0].ClaimID
	second.Evidence[0].EvidenceID = first.Evidence[0].EvidenceID

	compiled, err := Compile([]contracts.ContextPacket{first, second}, policy(now, 1000))
	if err != nil {
		t.Fatal(err)
	}
	if len(compiled.Findings) != 1 || len(compiled.Evidence) != 1 {
		t.Fatalf("expected stable identity deduplication, got %d findings and %d evidence", len(compiled.Findings), len(compiled.Evidence))
	}
	if len(compiled.Conflicts) != 2 {
		t.Fatalf("expected claim and evidence conflicts, got %v", compiled.Conflicts)
	}
	if compiled.Findings[0].Statement != "Revenue was 10." {
		t.Fatal("compiler must preserve the first stable claim rather than rewrite it")
	}
}

func TestCompileReportsStaleMissingAndBudgetDrops(t *testing.T) {
	now := time.Date(2026, 7, 21, 0, 0, 0, 0, time.UTC)
	item := packet(now.AddDate(-2, 0, 0), "packet-1", "A sufficiently long material finding that consumes the deliberately tiny compilation budget.", "sha-a")
	item.Scope.AsOf = now.AddDate(-2, 0, 0)
	item.MissingEvidence = []string{"segment_customer_concentration"}
	compiled, err := Compile([]contracts.ContextPacket{item}, policy(now, 4))
	if err != nil {
		t.Fatal(err)
	}
	if len(compiled.StaleEvidence) != 1 || len(compiled.MissingEvidence) != 1 || len(compiled.DroppedForBudget) != 1 {
		t.Fatalf("expected stale, missing, and dropped markers: %+v", compiled)
	}
}

func TestCompileRejectsMalformedFutureAndCrossRunPackets(t *testing.T) {
	now := time.Date(2026, 7, 21, 0, 0, 0, 0, time.UTC)
	malformed := packet(now, "packet-1", "Revenue was 10.", "sha-a")
	malformed.Findings[0].EvidenceRefs = nil
	if _, err := Compile([]contracts.ContextPacket{malformed}, policy(now, 1000)); err == nil {
		t.Fatal("malformed packet must fail")
	}
	future := packet(now.Add(time.Hour), "packet-1", "Revenue was 10.", "sha-a")
	if _, err := Compile([]contracts.ContextPacket{future}, policy(now, 1000)); err == nil {
		t.Fatal("future packet must fail")
	}
	first := packet(now, "packet-1", "Revenue was 10.", "sha-a")
	second := packet(now, "packet-2", "Revenue was 12.", "sha-b")
	second.RunID = "other-run"
	if _, err := Compile([]contracts.ContextPacket{first, second}, policy(now, 1000)); err == nil {
		t.Fatal("cross-run compilation must fail")
	}
}

func TestPrimaryFactRanksBeforeInference(t *testing.T) {
	now := time.Date(2026, 7, 21, 0, 0, 0, 0, time.UTC)
	item := packet(now, "packet-1", "Primary fact.", "sha-a")
	item.Findings = append([]contracts.Finding{{
		ClaimID: "inference-1", ClaimType: contracts.ClaimInference, Statement: "Inference.",
		EvidenceRefs: []string{"evidence-1"}, AssumptionRefs: []string{"assumption-1"}, Confidence: 0.5, ValidAsOf: now,
	}}, item.Findings...)
	compiled, err := Compile([]contracts.ContextPacket{item}, policy(now, 1000))
	if err != nil {
		t.Fatal(err)
	}
	if compiled.Findings[0].Statement != "Primary fact." {
		t.Fatalf("unexpected ranking: %+v", compiled.Findings)
	}
}

func packet(asOf time.Time, id, statement, sha string) contracts.ContextPacket {
	return contracts.ContextPacket{
		SchemaVersion: contracts.SchemaVersionV1, PacketID: id, RunID: "run-1", StepID: id,
		SpecialistRole: "business-strategy/v1", Objective: "Test", Scope: contracts.Scope{AsOf: asOf},
		Evidence: []contracts.EvidenceRef{{EvidenceID: "evidence-1", SourceType: "sec_filing", Locator: "test", ContentSHA: sha, AsOf: asOf}},
		Findings: []contracts.Finding{{ClaimID: "claim-1", ClaimType: contracts.ClaimFact, Statement: statement, EvidenceRefs: []string{"evidence-1"}, Confidence: 1, ValidAsOf: asOf}},
	}
}

func policy(asOf time.Time, budget int) Policy {
	return Policy{AsOf: asOf, MaxEvidenceAge: 365 * 24 * time.Hour, TokenBudget: budget, CharsPerToken: 4, PrimarySources: []string{"sec_filing", "sec_xbrl"}}
}
