package cpureplay

import (
	"errors"
	"fmt"
	"time"

	"github.com/rvbernucci/signalforge/internal/capability"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/planner"
	"github.com/rvbernucci/signalforge/internal/requestparser"
	"github.com/rvbernucci/signalforge/internal/roleprofiles"
	"github.com/rvbernucci/signalforge/internal/roles"
)

type PreparedReplay struct {
	SchemaVersion                   string                    `json:"schema_version"`
	JourneyID                       string                    `json:"journey_id"`
	Request                         contracts.ResearchRequest `json:"request"`
	Plan                            contracts.ResearchPlan    `json:"plan"`
	DeterministicToolsBeforeModels  bool                      `json:"deterministic_tools_before_models"`
	RiskAndEvidenceReviewSeparated  bool                      `json:"risk_and_evidence_review_separated"`
	EvidenceCriticIsLastReviewGate  bool                      `json:"evidence_critic_is_last_review_gate"`
	FinalAnalystHasNoFreshRetrieval bool                      `json:"final_analyst_has_no_fresh_retrieval"`
}

type Input struct {
	JourneyID string
	Text      string
	AsOf      time.Time
	RunID     string
	RequestID string
}

func Prepare(input Input) (PreparedReplay, error) {
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: input.Text, AsOf: input.AsOf, RunID: input.RunID, RequestID: input.RequestID,
	})
	if err != nil {
		return PreparedReplay{}, err
	}
	builder := planner.Builder{
		Roles: roles.DefaultRegistry(), Capabilities: capability.RuntimeRegistry(), DeadlineMS: 90000,
	}
	plan, err := builder.Build(request)
	if err != nil {
		return PreparedReplay{}, err
	}
	profiles := roleprofiles.DefaultRegistry()
	deterministicToolsBeforeModels := true
	reviewOrder := []string{}
	finalCount := 0
	for _, step := range plan.Steps {
		profile, ok := profiles.Get(step.RoleID)
		if !ok {
			return PreparedReplay{}, fmt.Errorf("step %q has no retrieval profile", step.StepID)
		}
		switch step.Kind {
		case "context":
			if profile.Mode == "none" {
				return PreparedReplay{}, fmt.Errorf("context role %q cannot retrieve", step.RoleID)
			}
			// Capabilities are attached to a context request and executed by the deterministic
			// adapter before the model receives its context packet.
			for _, operationID := range step.CapabilityIDs {
				if !builder.Capabilities.Authorizes(step.RoleID, operationID) {
					deterministicToolsBeforeModels = false
				}
			}
		case "review":
			reviewOrder = append(reviewOrder, step.RoleID)
		case "synthesis":
			finalCount++
			if step.RoleID != roles.FinalResearchAnalyst || len(step.CapabilityIDs) > 0 {
				return PreparedReplay{}, errors.New("synthesis violates final-authority boundary")
			}
		}
	}
	finalProfile, _ := profiles.Get(roles.FinalResearchAnalyst)
	separated := contains(reviewOrder, roles.RiskContrarian) && contains(reviewOrder, roles.EvidenceCritic)
	criticLast := len(reviewOrder) > 0 && reviewOrder[len(reviewOrder)-1] == roles.EvidenceCritic
	if finalCount != 1 || !criticLast || !deterministicToolsBeforeModels {
		return PreparedReplay{}, errors.New("prepared replay violates orchestration invariants")
	}
	return PreparedReplay{
		SchemaVersion: "signalforge/cpu-prepared-replay/v1", JourneyID: input.JourneyID,
		Request: request, Plan: plan, DeterministicToolsBeforeModels: deterministicToolsBeforeModels,
		RiskAndEvidenceReviewSeparated: separated, EvidenceCriticIsLastReviewGate: criticLast,
		FinalAnalystHasNoFreshRetrieval: finalProfile.Mode == "none",
	}, nil
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
