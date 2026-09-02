package productscope

import (
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/entityresolver"
)

const ActivationMatrixSchemaV1 = "signalforge/technology20-activation-matrix/v1"

type CoverageInput struct {
	InputName        string   `json:"input_name"`
	AcceptedConcepts []string `json:"accepted_concepts"`
	MatchedConcepts  []string `json:"matched_concepts"`
	Covered          bool     `json:"covered"`
}

type MetricCoverage struct {
	MetricID      string          `json:"metric_id"`
	MetricVersion string          `json:"metric_version"`
	Status        string          `json:"status"`
	Inputs        []CoverageInput `json:"inputs"`
}

type CompanyCoverage struct {
	CIK         string           `json:"cik"`
	CompanyID   string           `json:"company_id"`
	DisplayName string           `json:"display_name"`
	HTTPStatus  int              `json:"http_status"`
	Metrics     []MetricCoverage `json:"metrics"`
}

type CoverageReport struct {
	SchemaVersion string            `json:"schema_version"`
	UniverseID    string            `json:"universe_id"`
	GeneratedAt   time.Time         `json:"generated_at"`
	CompanyCount  int               `json:"company_count"`
	MetricCount   int               `json:"metric_count"`
	Observations  []CompanyCoverage `json:"observations"`
	ClaimBoundary string            `json:"claim_boundary"`
}

type ActivationSummary struct {
	Companies              int            `json:"companies"`
	ActivationStates       map[string]int `json:"activation_states"`
	MetricStates           map[string]int `json:"metric_states"`
	PeerLanes              int            `json:"peer_lanes"`
	EnabledPeerLanes       int            `json:"enabled_peer_lanes"`
	ResearchReadyCompanies int            `json:"research_ready_companies"`
}

type ActivationMatrix struct {
	SchemaVersion           string                             `json:"schema_version"`
	UniverseID              string                             `json:"universe_id"`
	AsOf                    time.Time                          `json:"as_of"`
	SourceCoverageSHA256    string                             `json:"source_coverage_sha256"`
	CompanyPolicyVersion    string                             `json:"company_policy_version"`
	ActivationPolicyVersion string                             `json:"activation_policy_version"`
	PeerLanePolicyVersion   string                             `json:"peer_lane_policy_version"`
	Profiles                []contracts.CompanyResearchProfile `json:"profiles"`
	PeerLanes               []contracts.PeerLane               `json:"peer_lanes"`
	Summary                 ActivationSummary                  `json:"summary"`
	ClaimBoundary           string                             `json:"claim_boundary"`
}

func BuildActivationMatrix(report CoverageReport, sourceHash string) (ActivationMatrix, error) {
	if err := ValidateCatalog(); err != nil {
		return ActivationMatrix{}, err
	}
	if report.UniverseID != UniverseID || report.GeneratedAt.IsZero() || report.CompanyCount != 20 ||
		report.MetricCount == 0 || len(report.Observations) != 20 || sourceHash == "" {
		return ActivationMatrix{}, errors.New("coverage report does not match the Technology 20 contract")
	}
	coverageByCompany := map[string]CompanyCoverage{}
	for _, observation := range report.Observations {
		if observation.CompanyID == "" || coverageByCompany[observation.CompanyID].CompanyID != "" {
			return ActivationMatrix{}, errors.New("coverage report contains duplicate or empty company identity")
		}
		coverageByCompany[observation.CompanyID] = observation
	}
	issuerByCompany := map[string]entityresolver.Issuer{}
	for _, issuer := range entityresolver.DefaultRegistry().Issuers() {
		issuerByCompany[issuer.CompanyID] = issuer
	}
	matrix := ActivationMatrix{
		SchemaVersion: ActivationMatrixSchemaV1, UniverseID: UniverseID, AsOf: report.GeneratedAt,
		SourceCoverageSHA256: sourceHash, CompanyPolicyVersion: CompanyPolicyVersion,
		ActivationPolicyVersion: ActivationPolicyVersion, PeerLanePolicyVersion: PeerLanePolicyVersion,
		Summary:       ActivationSummary{ActivationStates: map[string]int{}, MetricStates: map[string]int{}},
		ClaimBoundary: "Data-ready means identity and measured Company Facts coverage passed. It does not authorize research_ready, comparison_ready, period alignment, semantic equivalence, or professional accounting review.",
	}
	for _, policy := range Companies() {
		observation, exists := coverageByCompany[policy.CompanyID]
		issuer, issuerExists := issuerByCompany[policy.CompanyID]
		if !exists || !issuerExists || observation.HTTPStatus != 200 ||
			observation.CIK != issuer.CIK || observation.DisplayName != issuer.DisplayName {
			return ActivationMatrix{}, fmt.Errorf("company %q failed identity or acquisition reconciliation", policy.CompanyID)
		}
		activation, err := contracts.PopulateCompanyActivationHash(contracts.CompanyActivation{
			SchemaVersion: contracts.CompanyActivationSchemaV1,
			ActivationID:  "activation-" + issuer.CIK + "-data-ready",
			UniverseID:    UniverseID, Scope: contracts.ActivationScopeCompany,
			SubjectID: policy.CompanyID, CompanyIDs: []string{policy.CompanyID},
			State: contracts.ActivationDataReady, PolicyVersion: ActivationPolicyVersion,
			EvidenceHashes: []string{sourceHash}, EffectiveAsOf: report.GeneratedAt,
			GeneratedAt: report.GeneratedAt,
		})
		if err != nil {
			return ActivationMatrix{}, err
		}
		metrics, err := metricAvailability(observation.Metrics, sourceHash, report.GeneratedAt)
		if err != nil {
			return ActivationMatrix{}, fmt.Errorf("%s: %w", policy.CompanyID, err)
		}
		securities := make([]contracts.SecurityIdentity, 0, len(issuer.Securities))
		for _, security := range issuer.Securities {
			securities = append(securities, contracts.SecurityIdentity{
				SecurityID: security.SecurityID, Ticker: security.Ticker,
				Exchange: security.Exchange, Primary: security.Primary,
			})
		}
		profile, err := contracts.PopulateCompanyResearchProfileHash(contracts.CompanyResearchProfile{
			SchemaVersion: contracts.CompanyResearchProfileV1,
			ProfileID:     "profile-" + issuer.CIK, UniverseID: UniverseID,
			CompanyID: policy.CompanyID, CIK: issuer.CIK, DisplayName: issuer.DisplayName,
			Securities: securities, ResearchCluster: policy.ResearchCluster,
			PeerGroup: policy.PeerGroup, ResearchRole: policy.ResearchRole,
			Activation: activation, Metrics: metrics, SourceRegistryHash: sourceHash,
			PolicyVersion: CompanyPolicyVersion, AsOf: report.GeneratedAt,
		})
		if err != nil {
			return ActivationMatrix{}, err
		}
		if err := contracts.ValidateCompanyResearchProfile(profile); err != nil {
			return ActivationMatrix{}, fmt.Errorf("%s: %w", policy.CompanyID, err)
		}
		matrix.Profiles = append(matrix.Profiles, profile)
		matrix.Summary.ActivationStates[string(activation.State)]++
		for _, metric := range metrics {
			matrix.Summary.MetricStates[string(metric.State)]++
		}
	}
	lanes, err := InitialPeerLanes(report.GeneratedAt, sourceHash)
	if err != nil {
		return ActivationMatrix{}, err
	}
	matrix.PeerLanes = lanes
	matrix.Summary.Companies = len(matrix.Profiles)
	matrix.Summary.PeerLanes = len(matrix.PeerLanes)
	sort.Slice(matrix.Profiles, func(i, j int) bool { return matrix.Profiles[i].CompanyID < matrix.Profiles[j].CompanyID })
	return matrix, nil
}

func metricAvailability(coverage []MetricCoverage, sourceHash string, asOf time.Time) ([]contracts.MetricAvailability, error) {
	result := make([]contracts.MetricAvailability, 0, len(coverage))
	seen := map[string]bool{}
	for _, metric := range coverage {
		if metric.MetricID == "" || seen[metric.MetricID] {
			return nil, errors.New("metric coverage contains duplicate or empty metric identity")
		}
		seen[metric.MetricID] = true
		item := contracts.MetricAvailability{MetricID: metric.MetricID}
		switch metric.Status {
		case "covered":
			item.State = contracts.AvailabilityCovered
			item.EvidenceHashes = []string{sourceHash}
			item.AvailableAt = timePointer(asOf)
		case "partial":
			item.State = contracts.AvailabilityPartial
			item.ReasonCodes = []string{"required_company_facts_input_missing"}
			item.EvidenceHashes = []string{sourceHash}
			item.AvailableAt = timePointer(asOf)
		case "missing":
			item.State = contracts.AvailabilityMissing
			item.ReasonCodes = []string{"accepted_company_facts_concept_not_found"}
		case "not_xbrl_bound":
			item.State = contracts.AvailabilityNotApplicable
			item.ReasonCodes = []string{"operation_not_company_facts_bound"}
		default:
			return nil, fmt.Errorf("metric %q has unsupported coverage state %q", metric.MetricID, metric.Status)
		}
		result = append(result, item)
	}
	sort.Slice(result, func(i, j int) bool { return result[i].MetricID < result[j].MetricID })
	return result, nil
}

func timePointer(value time.Time) *time.Time {
	return &value
}
