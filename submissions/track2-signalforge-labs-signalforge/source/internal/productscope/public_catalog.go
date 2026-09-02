package productscope

import (
	"errors"
	"sort"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

const PublicCatalogSchemaV1 = "signalforge/technology20-public-catalog/v1"

type PublicCatalog struct {
	SchemaVersion           string           `json:"schema_version"`
	UniverseID              string           `json:"universe_id"`
	AsOf                    time.Time        `json:"as_of"`
	CompanyPolicyVersion    string           `json:"company_policy_version"`
	ActivationPolicyVersion string           `json:"activation_policy_version"`
	PeerLanePolicyVersion   string           `json:"peer_lane_policy_version"`
	SourceRegistrySHA256    string           `json:"source_registry_sha256"`
	Companies               []PublicCompany  `json:"companies"`
	PeerLanes               []PublicPeerLane `json:"peer_lanes"`
	ClaimBoundary           string           `json:"claim_boundary"`
}

type PublicCompany struct {
	CompanyID        string                    `json:"company_id"`
	DisplayName      string                    `json:"display_name"`
	PrimaryTicker    string                    `json:"primary_ticker"`
	Tickers          []string                  `json:"tickers"`
	ResearchCluster  string                    `json:"research_cluster"`
	PeerGroup        string                    `json:"peer_group"`
	ResearchRole     string                    `json:"research_role"`
	ActivationState  contracts.ActivationState `json:"activation_state"`
	ResearchEnabled  bool                      `json:"research_enabled"`
	ReasonCodes      []string                  `json:"reason_codes"`
	MetricStateCount map[string]int            `json:"metric_state_count"`
	ProfileSHA256    string                    `json:"profile_sha256"`
}

type PublicPeerLane struct {
	LaneID             string   `json:"lane_id"`
	CompanyIDs         []string `json:"company_ids"`
	ComparisonType     string   `json:"comparison_type"`
	DecisionQuestion   string   `json:"decision_question"`
	AllowedQuestionIDs []string `json:"allowed_question_ids"`
	AllowedMetricIDs   []string `json:"allowed_metric_ids"`
	Enabled            bool     `json:"enabled"`
	ReasonCodes        []string `json:"reason_codes"`
	LaneSHA256         string   `json:"lane_sha256"`
}

func BuildPublicCatalog(matrix ActivationMatrix) (PublicCatalog, error) {
	if matrix.SchemaVersion != ActivationMatrixSchemaV1 || matrix.UniverseID != UniverseID ||
		matrix.AsOf.IsZero() || matrix.SourceCoverageSHA256 == "" || len(matrix.Profiles) != 20 {
		return PublicCatalog{}, errors.New("activation matrix cannot authorize a public catalog")
	}
	result := PublicCatalog{
		SchemaVersion: PublicCatalogSchemaV1, UniverseID: UniverseID, AsOf: matrix.AsOf,
		CompanyPolicyVersion:    matrix.CompanyPolicyVersion,
		ActivationPolicyVersion: matrix.ActivationPolicyVersion,
		PeerLanePolicyVersion:   matrix.PeerLanePolicyVersion,
		SourceRegistrySHA256:    matrix.SourceCoverageSHA256,
		ClaimBoundary:           "Catalog presence means the issuer identity and SEC-derived data coverage were validated. Research and comparison remain disabled until their separate journey and comparability gates pass.",
	}
	for _, profile := range matrix.Profiles {
		if err := contracts.ValidateCompanyResearchProfile(profile); err != nil {
			return PublicCatalog{}, err
		}
		company := PublicCompany{
			CompanyID: profile.CompanyID, DisplayName: profile.DisplayName,
			ResearchCluster: profile.ResearchCluster, PeerGroup: profile.PeerGroup,
			ResearchRole: profile.ResearchRole, ActivationState: profile.Activation.State,
			ResearchEnabled: profile.Activation.State == contracts.ActivationResearchReady ||
				profile.Activation.State == contracts.ActivationComparisonReady,
			MetricStateCount: map[string]int{}, ProfileSHA256: profile.ProfileSHA256,
		}
		if !company.ResearchEnabled {
			company.ReasonCodes = []string{"standalone_journey_not_yet_promoted"}
		}
		for _, security := range profile.Securities {
			company.Tickers = append(company.Tickers, security.Ticker)
			if security.Primary {
				company.PrimaryTicker = security.Ticker
			}
		}
		if company.PrimaryTicker == "" || len(company.Tickers) == 0 {
			return PublicCatalog{}, errors.New("public company has no primary security")
		}
		sort.Strings(company.Tickers)
		for _, metric := range profile.Metrics {
			company.MetricStateCount[string(metric.State)]++
		}
		result.Companies = append(result.Companies, company)
	}
	for _, lane := range matrix.PeerLanes {
		if err := contracts.ValidatePeerLane(lane); err != nil {
			return PublicCatalog{}, err
		}
		item := PublicPeerLane{
			LaneID: lane.LaneID, CompanyIDs: append([]string(nil), lane.CompanyIDs...),
			ComparisonType: lane.ComparisonType, DecisionQuestion: lane.DecisionQuestion,
			AllowedQuestionIDs: append([]string(nil), lane.AllowedQuestionIDs...),
			AllowedMetricIDs:   append([]string(nil), lane.AllowedMetricIDs...),
			Enabled:            lane.Enabled, LaneSHA256: lane.LaneSHA256,
		}
		if !item.Enabled {
			item.ReasonCodes = []string{"peer_lane_not_yet_promoted"}
		}
		result.PeerLanes = append(result.PeerLanes, item)
	}
	sort.Slice(result.Companies, func(i, j int) bool {
		if result.Companies[i].DisplayName != result.Companies[j].DisplayName {
			return result.Companies[i].DisplayName < result.Companies[j].DisplayName
		}
		return result.Companies[i].CompanyID < result.Companies[j].CompanyID
	})
	sort.Slice(result.PeerLanes, func(i, j int) bool { return result.PeerLanes[i].LaneID < result.PeerLanes[j].LaneID })
	if err := ValidatePublicCatalog(result); err != nil {
		return PublicCatalog{}, err
	}
	return result, nil
}

func ValidatePublicCatalog(catalog PublicCatalog) error {
	if catalog.SchemaVersion != PublicCatalogSchemaV1 || catalog.UniverseID != UniverseID ||
		catalog.AsOf.IsZero() || catalog.SourceRegistrySHA256 == "" ||
		len(catalog.Companies) != 20 || len(catalog.PeerLanes) != 5 {
		return errors.New("public catalog envelope is invalid")
	}
	companies := map[string]bool{}
	for _, company := range catalog.Companies {
		if company.CompanyID == "" || companies[company.CompanyID] || company.DisplayName == "" ||
			company.PrimaryTicker == "" || company.ResearchCluster == "" || company.PeerGroup == "" ||
			company.ResearchRole == "" || company.ProfileSHA256 == "" {
			return errors.New("public catalog contains an invalid company")
		}
		if company.ResearchEnabled && company.ActivationState != contracts.ActivationResearchReady &&
			company.ActivationState != contracts.ActivationComparisonReady {
			return errors.New("public catalog expands company activation")
		}
		if !company.ResearchEnabled && len(company.ReasonCodes) == 0 {
			return errors.New("disabled public company requires reason codes")
		}
		companies[company.CompanyID] = true
	}
	for _, lane := range catalog.PeerLanes {
		if lane.LaneID == "" || len(lane.CompanyIDs) != 2 || lane.LaneSHA256 == "" {
			return errors.New("public catalog contains an invalid peer lane")
		}
		if !companies[lane.CompanyIDs[0]] || !companies[lane.CompanyIDs[1]] {
			return errors.New("public peer lane references an unknown company")
		}
		if !lane.Enabled && len(lane.ReasonCodes) == 0 {
			return errors.New("disabled public peer lane requires reason codes")
		}
	}
	return nil
}
