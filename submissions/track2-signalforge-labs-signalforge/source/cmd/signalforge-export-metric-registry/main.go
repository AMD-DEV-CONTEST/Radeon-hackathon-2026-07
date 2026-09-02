package main

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/rvbernucci/signalforge/internal/metricregistry"
)

type catalog struct {
	SchemaVersion string       `json:"schema_version"`
	Metrics       []metricView `json:"metrics"`
}

type metricView struct {
	MetricID               string                    `json:"metric_id"`
	Version                string                    `json:"version"`
	Status                 metricregistry.Lifecycle  `json:"status"`
	Name                   string                    `json:"name"`
	EconomicMeaning        string                    `json:"economic_meaning"`
	Formula                formulaView               `json:"formula"`
	Inputs                 []inputView               `json:"inputs"`
	Output                 outputView                `json:"output"`
	PeriodPolicy           periodView                `json:"period_policy"`
	Applicability          applicabilityView         `json:"applicability"`
	GAAPStatus             metricregistry.GAAPStatus `json:"gaap_status"`
	ReconciliationRequired bool                      `json:"reconciliation_required"`
	Authority              authorityView             `json:"authority"`
	FailureDispositions    []string                  `json:"failure_dispositions"`
	Supersedes             string                    `json:"supersedes,omitempty"`
}

type formulaView struct {
	Expression          string `json:"expression"`
	Convention          string `json:"convention"`
	ImplementationOwner string `json:"implementation_owner"`
}

type inputView struct {
	Name             string   `json:"name"`
	QuantityKind     string   `json:"quantity_kind"`
	SignPolicy       string   `json:"sign_policy"`
	Required         bool     `json:"required"`
	AcceptedConcepts []string `json:"accepted_concepts,omitempty"`
}

type outputView struct {
	QuantityKind    string `json:"quantity_kind"`
	UnitPolicy      string `json:"unit_policy"`
	PrecisionPolicy string `json:"precision_policy"`
}

type periodView struct {
	Basis               metricregistry.PeriodBasis `json:"basis"`
	AlignmentRequired   bool                       `json:"alignment_required"`
	LookAheadProhibited bool                       `json:"look_ahead_prohibited"`
}

type applicabilityView struct {
	DefaultProfile      metricregistry.CompanyProfile   `json:"default_profile"`
	ExcludedProfiles    []metricregistry.CompanyProfile `json:"excluded_profiles"`
	NegativeValuePolicy string                          `json:"negative_value_policy"`
}

type authorityView struct {
	DefinitionSources []string `json:"definition_sources"`
	ReviewOwner       string   `json:"review_owner"`
}

func main() {
	result := buildCatalog()
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(result); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func buildCatalog() catalog {
	definitions := metricregistry.Default().ListActive()
	result := catalog{SchemaVersion: "signalforge.metric-registry/v1", Metrics: make([]metricView, 0, len(definitions))}
	for _, definition := range definitions {
		inputs := make([]inputView, 0, len(definition.Inputs))
		for _, input := range definition.Inputs {
			inputs = append(inputs, inputView{Name: input.Name, QuantityKind: input.QuantityKind, SignPolicy: input.SignPolicy, Required: input.Required, AcceptedConcepts: input.AcceptedConcepts})
		}
		result.Metrics = append(result.Metrics, metricView{
			MetricID: definition.MetricID, Version: definition.Version, Status: definition.Status,
			Name: definition.Name, EconomicMeaning: definition.EconomicMeaning,
			Formula: formulaView{Expression: definition.FormulaExpression, Convention: definition.Convention, ImplementationOwner: definition.ImplementationOwner},
			Inputs:  inputs, Output: outputView{QuantityKind: definition.Output.QuantityKind, UnitPolicy: definition.Output.UnitPolicy, PrecisionPolicy: definition.Output.PrecisionPolicy},
			PeriodPolicy:  periodView{Basis: definition.PeriodPolicy.Basis, AlignmentRequired: definition.PeriodPolicy.AlignmentRequired, LookAheadProhibited: definition.PeriodPolicy.LookAheadProhibited},
			Applicability: applicabilityView{DefaultProfile: definition.Applicability.DefaultProfile, ExcludedProfiles: definition.Applicability.ExcludedProfiles, NegativeValuePolicy: definition.Applicability.NegativeValuePolicy},
			GAAPStatus:    definition.GAAPStatus, ReconciliationRequired: definition.ReconciliationRequired,
			Authority:           authorityView{DefinitionSources: definition.DefinitionSources, ReviewOwner: definition.ReviewOwner},
			FailureDispositions: definition.FailureDispositions, Supersedes: definition.Supersedes,
		})
	}
	return result
}
