package productscope

import (
	"errors"
	"fmt"
	"sort"
	"time"
)

const PeerJourneySuiteSchemaV1 = "signalforge/technology20-peer-journeys/v1"

type PeerJourneySuite struct {
	SchemaVersion string            `json:"schema_version"`
	UniverseID    string            `json:"universe_id"`
	Split         string            `json:"split"`
	AsOf          time.Time         `json:"as_of"`
	Cases         []PeerJourneyCase `json:"cases"`
	ClaimBoundary string            `json:"claim_boundary"`
}

type PeerJourneyCase struct {
	JourneyID         string            `json:"journey_id"`
	LaneID            string            `json:"lane_id"`
	CompanyIDs        []string          `json:"company_ids"`
	QuestionID        string            `json:"question_id"`
	Question          string            `json:"question"`
	ExpectedMetrics   map[string]string `json:"expected_metric_dispositions"`
	ExpectedPromoted  bool              `json:"expected_promoted"`
	RequiredBehaviors []string          `json:"required_behaviors"`
}

func BuildPeerJourneySuites(
	catalog PublicCatalog,
	peers PeerEvaluationSuite,
) (PeerJourneySuite, PeerJourneySuite, error) {
	if err := ValidatePublicCatalog(catalog); err != nil {
		return PeerJourneySuite{}, PeerJourneySuite{}, err
	}
	if err := ValidatePeerEvaluationSuite(peers); err != nil {
		return PeerJourneySuite{}, PeerJourneySuite{}, err
	}
	companyByID := map[string]PublicCompany{}
	for _, company := range catalog.Companies {
		companyByID[company.CompanyID] = company
	}
	base := func(split string) PeerJourneySuite {
		return PeerJourneySuite{
			SchemaVersion: PeerJourneySuiteSchemaV1, UniverseID: UniverseID,
			Split: split, AsOf: catalog.AsOf,
			ClaimBoundary: "These cases test bounded metric comparability and useful refusal. They do not authorize pair-level ranking or investment direction.",
		}
	}
	development, sealed := base("development"), base("sealed_holdout")
	for _, lane := range peers.Lanes {
		left, right := companyByID[lane.CompanyIDs[0]], companyByID[lane.CompanyIDs[1]]
		dispositions := peerMetricDispositions(lane)
		developmentQuestions := []struct{ id, text string }{
			{"metric-boundary", fmt.Sprintf("Compare %s and %s using only metrics with valid comparability receipts.", left.DisplayName, right.DisplayName)},
			{"periods", fmt.Sprintf("Explain which annual periods can and cannot be compared for %s and %s.", left.DisplayName, right.DisplayName)},
			{"cash-generation", fmt.Sprintf("Compare cash generation for %s and %s without treating simple FCF as FCFF.", left.DisplayName, right.DisplayName)},
			{"profitability", fmt.Sprintf("Compare operating profitability for %s and %s and display every fiscal-calendar caveat beside the metric.", left.DisplayName, right.DisplayName)},
			{"growth", fmt.Sprintf("Compare reported revenue growth for %s and %s only if the definitions and source concepts pass review.", left.DisplayName, right.DisplayName)},
			{"missing-data", fmt.Sprintf("Show what cannot yet be compared between %s and %s and why.", left.DisplayName, right.DisplayName)},
			{"counterevidence", fmt.Sprintf("Challenge a relative-quality thesis for %s and %s without ranking incomparable measures.", left.DisplayName, right.DisplayName)},
			{"decision-boundary", fmt.Sprintf("Summarize the decision-useful comparison boundary for %s and %s.", left.DisplayName, right.DisplayName)},
		}
		sealedQuestions := []struct{ id, text string }{
			{"sealed-releasable", fmt.Sprintf("Which verified metrics permit a bounded comparison of %s and %s?", left.DisplayName, right.DisplayName)},
			{"sealed-withheld", fmt.Sprintf("Which apparent similarities between %s and %s should SignalForge refuse to compare?", left.DisplayName, right.DisplayName)},
			{"sealed-thesis", fmt.Sprintf("Build and challenge a relative business-quality thesis for %s and %s using only approved evidence.", left.DisplayName, right.DisplayName)},
			{"sealed-valuation", fmt.Sprintf("Compare the valuation of %s and %s, or abstain if aligned prices and denominators are unavailable.", left.DisplayName, right.DisplayName)},
		}
		appendCases := func(target *PeerJourneySuite, questions []struct{ id, text string }) {
			for _, question := range questions {
				target.Cases = append(target.Cases, PeerJourneyCase{
					JourneyID: lane.LaneID + "-" + question.id, LaneID: lane.LaneID,
					CompanyIDs: append([]string(nil), lane.CompanyIDs...),
					QuestionID: question.id, Question: question.text,
					ExpectedMetrics: copyStringMap(dispositions), ExpectedPromoted: false,
					RequiredBehaviors: []string{
						"metric_level_receipt_gate", "visible_period_caveat",
						"not_comparable_is_unreleased", "no_pair_level_ranking",
					},
				})
			}
		}
		appendCases(&development, developmentQuestions)
		appendCases(&sealed, sealedQuestions)
	}
	sort.Slice(development.Cases, func(i, j int) bool { return development.Cases[i].JourneyID < development.Cases[j].JourneyID })
	sort.Slice(sealed.Cases, func(i, j int) bool { return sealed.Cases[i].JourneyID < sealed.Cases[j].JourneyID })
	if err := ValidatePeerJourneySuite(development, 40); err != nil {
		return PeerJourneySuite{}, PeerJourneySuite{}, err
	}
	if err := ValidatePeerJourneySuite(sealed, 20); err != nil {
		return PeerJourneySuite{}, PeerJourneySuite{}, err
	}
	return development, sealed, nil
}

func peerMetricDispositions(lane PeerEvaluationResult) map[string]string {
	result := map[string]string{}
	for _, receipt := range lane.Receipts {
		result[receipt.Operands[0].CanonicalMetricID] = string(receipt.Disposition)
	}
	for _, abstention := range lane.Abstentions {
		result[abstention.MetricIDs[0]] = "unavailable"
	}
	return result
}

func ValidatePeerJourneySuite(suite PeerJourneySuite, expectedCases int) error {
	if suite.SchemaVersion != PeerJourneySuiteSchemaV1 || suite.UniverseID != UniverseID ||
		suite.AsOf.IsZero() || suite.ClaimBoundary == "" || len(suite.Cases) != expectedCases {
		return errors.New("peer journey suite envelope is invalid")
	}
	seen := map[string]bool{}
	lanes := map[string]int{}
	for _, item := range suite.Cases {
		if item.JourneyID == "" || seen[item.JourneyID] || item.LaneID == "" ||
			len(item.CompanyIDs) != 2 || item.QuestionID == "" || item.Question == "" ||
			len(item.ExpectedMetrics) == 0 || item.ExpectedPromoted ||
			len(item.RequiredBehaviors) == 0 {
			return errors.New("peer journey suite contains an invalid or over-promoted case")
		}
		seen[item.JourneyID] = true
		lanes[item.LaneID]++
	}
	if len(lanes) != 5 {
		return errors.New("peer journey suite does not cover all lanes")
	}
	expectedPerLane := expectedCases / 5
	for _, count := range lanes {
		if count != expectedPerLane {
			return errors.New("peer journey suite is not balanced by lane")
		}
	}
	return nil
}

func copyStringMap(input map[string]string) map[string]string {
	result := make(map[string]string, len(input))
	for key, value := range input {
		result[key] = value
	}
	return result
}
