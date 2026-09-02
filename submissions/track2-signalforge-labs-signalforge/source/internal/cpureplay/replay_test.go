package cpureplay

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestSevenGoldenJourneysPrepareWithoutModelOrGPU(t *testing.T) {
	asOf := time.Date(2026, 7, 23, 12, 0, 0, 0, time.UTC)
	journeys := []struct {
		id   string
		text string
	}{
		{"journey-business", "What does Microsoft's business model sell and who pays?"},
		{"journey-quality", "Explain Microsoft free cash flow and cash conversion."},
		{"journey-economics", "How do higher interest rates affect Microsoft economic demand?"},
		{"journey-comparison", "Compare Microsoft and NVIDIA on financial quality and valuation."},
		{"journey-valuation", "What value range does Microsoft's current price imply using DCF?"},
		{"journey-thesis", "Challenge my Microsoft thesis and identify evidence that would invalidate it."},
		{"journey-controls", "Explain what is evidence lineage for Microsoft."},
	}
	for index, journey := range journeys {
		replay, err := Prepare(Input{
			JourneyID: journey.id, Text: journey.text, AsOf: asOf,
			RunID: "run-" + journey.id, RequestID: "request-" + journey.id,
		})
		if err != nil {
			t.Fatalf("journey %d %s: %v", index+1, journey.id, err)
		}
		if !replay.DeterministicToolsBeforeModels || !replay.EvidenceCriticIsLastReviewGate ||
			!replay.FinalAnalystHasNoFreshRetrieval {
			t.Fatalf("journey %q violates controls: %+v", journey.id, replay)
		}
	}
}

func TestFinancialIntelligenceReplayFixturesArePublicAndControlled(t *testing.T) {
	var fixture struct {
		SchemaVersion          string `json:"schema_version"`
		AsOf                   string `json:"as_of"`
		ContainsPrivatePrompts bool   `json:"contains_private_prompts"`
		ContainsChainOfThought bool   `json:"contains_chain_of_thought"`
		Journeys               []struct {
			JourneyID      string   `json:"journey_id"`
			Question       string   `json:"question"`
			RequiredStates []string `json:"required_states"`
		} `json:"journeys"`
	}
	content, err := os.ReadFile(filepath.Join("..", "..", "fixtures", "financial-intelligence-journeys.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(content, &fixture); err != nil {
		t.Fatal(err)
	}
	if fixture.ContainsPrivatePrompts || fixture.ContainsChainOfThought || len(fixture.Journeys) != 3 {
		t.Fatalf("unsafe or incomplete replay fixture: %+v", fixture)
	}
	asOf, err := time.Parse(time.RFC3339, fixture.AsOf)
	if err != nil {
		t.Fatal(err)
	}
	for _, journey := range fixture.Journeys {
		replay, err := Prepare(Input{
			JourneyID: journey.JourneyID, Text: journey.Question, AsOf: asOf,
			RunID: "run-" + journey.JourneyID, RequestID: "request-" + journey.JourneyID,
		})
		if err != nil {
			t.Fatalf("%s: %v", journey.JourneyID, err)
		}
		if !replay.DeterministicToolsBeforeModels || !replay.EvidenceCriticIsLastReviewGate {
			t.Fatalf("%s violates orchestration controls", journey.JourneyID)
		}
	}
}

func TestMaterialJourneySeparatesRiskFromEvidenceCritic(t *testing.T) {
	replay, err := Prepare(Input{
		JourneyID: "journey-valuation",
		Text:      "What value range does Microsoft's current price imply using DCF?",
		AsOf:      time.Date(2026, 7, 23, 12, 0, 0, 0, time.UTC),
		RunID:     "run-valuation", RequestID: "request-valuation",
	})
	if err != nil {
		t.Fatal(err)
	}
	if !replay.RiskAndEvidenceReviewSeparated {
		t.Fatalf("material journey omitted independent risk review: %+v", replay.Plan)
	}
}
