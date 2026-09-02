package requestparser

import (
	"slices"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/taxonomy"
)

func TestDeterministicParserExtractsClosedRequest(t *testing.T) {
	request, err := ParseDeterministic(Input{
		Text: "Compare Microsoft and NVIDIA on cash conversion over five fiscal years.",
		AsOf: time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC), RunID: "run-1", RequestID: "request-1",
	})
	if err != nil {
		t.Fatal(err)
	}
	if request.PrimaryIntent != string(taxonomy.CompanyComparison) || len(request.Entities) != 2 || request.Comparison.Mode != "peer" {
		t.Fatalf("unexpected request %+v", request)
	}
	if request.Period.Kind != "trailing_fiscal_years" || request.Period.LookbackYears != 5 {
		t.Fatalf("unexpected period %+v", request.Period)
	}
}

func TestDeterministicParserResolvesTechnologyTwentyEntities(t *testing.T) {
	request, err := ParseDeterministic(Input{
		Text:  "Compare Apple and AMD as long-term businesses.",
		AsOf:  time.Date(2026, 7, 23, 12, 0, 0, 0, time.UTC),
		RunID: "run-tech-20", RequestID: "request-tech-20",
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(request.Entities) != 2 || request.Comparison.Mode != "peer" {
		t.Fatalf("technology-20 entities were not resolved: %+v", request)
	}
	if request.Entities[0].EntityID != "sec-cik:0000002488" &&
		request.Entities[1].EntityID != "sec-cik:0000002488" {
		t.Fatalf("AMD CIK missing: %+v", request.Entities)
	}
}

func TestModelIntentMappingFailsClosed(t *testing.T) {
	if _, err := NormalizeModelIntent("company_understanding"); err != nil {
		t.Fatal(err)
	}
	if _, err := NormalizeModelIntent("buy_recommendation"); err == nil {
		t.Fatal("an unknown model intent must fail closed")
	}
}

func TestAmbiguousExplicitRequestDoesNotInventAnEntity(t *testing.T) {
	request, err := ParseDeterministic(Input{
		Text: "How sensitive has this stock been to the Nasdaq?", AsOf: time.Now().UTC(), RunID: "run-1", RequestID: "request-1",
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(request.Entities) != 0 || len(request.Ambiguities) != 1 {
		t.Fatalf("ambiguous request should require context: %+v", request)
	}
}

func TestFollowUpUsesExplicitInheritedEntities(t *testing.T) {
	inherited := []contracts.EntityRef{{EntityType: "company", EntityID: "sec-cik:0000789019", Mention: "Microsoft", Resolved: true}}
	request, err := ParseDeterministic(Input{
		Text: "And is that margin improvement supported by cash?", AsOf: time.Now().UTC(),
		RunID: "run-1", RequestID: "request-2", ParentRequestID: "request-1", InheritedEntities: inherited,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(request.Entities) != 1 || len(request.Ambiguities) != 0 || request.ParentRequestID != "request-1" {
		t.Fatalf("follow-up context was not preserved: %+v", request)
	}
}

func TestThreeGovernedFollowUpsPreservePointInTimeScopeAndLineage(t *testing.T) {
	asOf := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)
	parent, err := ParseDeterministic(Input{
		Text: "Compare Microsoft and NVIDIA as long-term businesses.",
		AsOf: asOf, RunID: "run-parent", RequestID: "request-parent",
	})
	if err != nil {
		t.Fatal(err)
	}
	answer := governedAnswer(parent, "evidence-parent", "receipt-parent")
	questions := []struct {
		text   string
		intent string
	}{
		{"And is that margin improvement supported by cash?", "financial_quality"},
		{"How sensitive have these two companies been to the Nasdaq?", "market_behavior"},
		{"What evidence would invalidate that thesis?", "thesis_review"},
	}
	for index, question := range questions {
		followUp, err := NewFollowUpContext(parent, answer)
		if err != nil {
			t.Fatal(err)
		}
		child, err := ParseDeterministic(Input{
			Text: question.text, AsOf: asOf.Add(time.Duration(index+1) * time.Hour),
			RunID: "run-child-" + string(rune('a'+index)), RequestID: "request-child-" + string(rune('a'+index)),
			FollowUp: &followUp,
		})
		if err != nil {
			t.Fatal(err)
		}
		if child.PrimaryIntent != question.intent || child.ParentRequestID != parent.RequestID ||
			!child.AsOf.Equal(asOf) || len(child.Entities) != 2 || child.Comparison.Mode != "peer" {
			t.Fatalf("follow-up %d lost governed scope: %+v", index+1, child)
		}
		if !slices.Contains(child.LineageEvidenceRefs, "evidence-parent") ||
			!slices.Contains(child.LineageReceiptRefs, "receipt-parent") {
			t.Fatalf("follow-up %d lost lineage: %+v", index+1, child)
		}
		parent = child
		answer = governedAnswer(child, "evidence-child", "receipt-child")
	}
}

func TestParserPreservesFiscalIdentityAndFutureBoundary(t *testing.T) {
	asOf := time.Date(2026, 7, 23, 0, 0, 0, 0, time.UTC)
	request, err := ParseDeterministic(Input{
		Text: "Explain Microsoft free cash flow for FY 2025.", AsOf: asOf,
		RunID: "run-period", RequestID: "request-period",
	})
	if err != nil {
		t.Fatal(err)
	}
	if request.Period.Kind != "fiscal_year" || len(request.Period.FiscalYears) != 1 ||
		request.Period.FiscalYears[0] != 2025 || request.Period.Start != nil || request.Period.End != nil {
		t.Fatalf("fiscal period was not preserved: %+v", request.Period)
	}
	request, err = ParseDeterministic(Input{
		Text: "Explain Microsoft free cash flow from 2026-01-01 to 2027-01-01.", AsOf: asOf,
		RunID: "run-future", RequestID: "request-future",
	})
	if err != nil {
		t.Fatal(err)
	}
	if !contains(request.Ambiguities, "future_information_unavailable") {
		t.Fatalf("future information boundary was not preserved: %+v", request.Ambiguities)
	}
}

func TestParserFlagsUnsupportedLanguageWithoutGuessingTranslation(t *testing.T) {
	request, err := ParseDeterministic(Input{
		Text:  "Explique o free cash flow da Microsoft.",
		AsOf:  time.Date(2026, 7, 23, 0, 0, 0, 0, time.UTC),
		RunID: "run-language", RequestID: "request-language",
	})
	if err != nil {
		t.Fatal(err)
	}
	if !contains(request.RiskFlags, "non_english_input") {
		t.Fatalf("unsupported language was not flagged: %+v", request.RiskFlags)
	}
}

func governedAnswer(request contracts.ResearchRequest, evidenceID, receiptID string) contracts.FinalAnswer {
	sections := []contracts.AnswerSection{}
	for _, sectionType := range contracts.RequiredFinalSections(request.PrimaryIntent) {
		section := contracts.AnswerSection{SectionType: sectionType, Title: sectionType, Content: "Bounded answer."}
		if sectionType != "evidence" && sectionType != "limitations" {
			section.ClaimRefs = []string{"claim-" + request.RequestID}
			section.EvidenceRefs = []string{evidenceID}
			section.ReceiptRefs = []string{receiptID}
		}
		sections = append(sections, section)
	}
	return contracts.FinalAnswer{
		SchemaVersion: contracts.SchemaVersionV1, AnswerID: "answer-" + request.RequestID,
		RunID: request.RunID, RequestID: request.RequestID, PrimaryIntent: request.PrimaryIntent,
		AsOf: request.AsOf, Sections: sections, CritiqueRefs: []string{"critique-" + request.RequestID},
		ReleasedBy: "final-research-analyst/v1", ReleasedAt: request.AsOf,
	}
}
