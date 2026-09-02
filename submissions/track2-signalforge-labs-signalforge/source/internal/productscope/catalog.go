package productscope

import (
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/entityresolver"
)

const (
	UniverseID              = "us-technology-20-v2"
	CompanyPolicyVersion    = "technology20-company-policy/v1"
	PeerLanePolicyVersion   = "technology20-peer-lanes/v1"
	ActivationPolicyVersion = "technology20-activation/v1"
)

type CompanyPolicy struct {
	CompanyID       string `json:"company_id"`
	DisplayName     string `json:"display_name"`
	ResearchCluster string `json:"research_cluster"`
	PeerGroup       string `json:"peer_group"`
	ResearchRole    string `json:"research_role"`
}

func Companies() []CompanyPolicy {
	result := []CompanyPolicy{
		company("0000320193", "Apple", "devices_and_infrastructure", "consumer_compute_devices", "integrated devices, services, installed base, and capital returns"),
		company("0000789019", "Microsoft", "platforms_and_cloud", "hyperscale_platforms", "enterprise software, cloud infrastructure, and AI platform demand"),
		company("0001652044", "Alphabet", "platforms_and_cloud", "hyperscale_platforms", "digital advertising, cloud, AI infrastructure, and platform economics"),
		company("0001018724", "Amazon", "platforms_and_cloud", "hyperscale_platforms", "commerce, logistics, cloud infrastructure, and advertising"),
		company("0001326801", "Meta Platforms", "platforms_and_cloud", "hyperscale_platforms", "digital advertising, social platforms, and AI capital intensity"),
		company("0001045810", "NVIDIA", "semiconductors", "accelerated_compute", "accelerated computing, data-center demand, and platform economics"),
		company("0000002488", "Advanced Micro Devices", "semiconductors", "accelerated_compute", "CPU, GPU, adaptive computing, and data-center share"),
		company("0001730168", "Broadcom", "semiconductors", "diversified_compute_infrastructure", "custom silicon, connectivity, infrastructure software, and acquisition economics"),
		company("0000050863", "Intel", "semiconductors", "diversified_compute_infrastructure", "CPU demand, foundry investment, manufacturing intensity, and turnaround risk"),
		company("0000804328", "Qualcomm", "semiconductors", "diversified_compute_infrastructure", "wireless semiconductors, licensing economics, and edge computing"),
		company("0000723125", "Micron Technology", "semiconductors", "specialized_semiconductor_economics", "memory cycles, pricing, inventories, and capital intensity"),
		company("0000097476", "Texas Instruments", "semiconductors", "specialized_semiconductor_economics", "analog semiconductors, industrial exposure, and long-cycle manufacturing"),
		company("0000006951", "Applied Materials", "semiconductors", "specialized_semiconductor_economics", "semiconductor equipment demand, fab investment, and cycle exposure"),
		company("0001341439", "Oracle", "enterprise_software", "enterprise_applications_and_cloud", "database software, cloud infrastructure, and contracted revenue"),
		company("0001108524", "Salesforce", "enterprise_software", "enterprise_applications_and_cloud", "subscription software, remaining obligations, margins, and dilution"),
		company("0000796343", "Adobe", "enterprise_software", "enterprise_applications_and_cloud", "creative and document software, recurring revenue, and AI monetization"),
		company("0001373715", "ServiceNow", "enterprise_software", "enterprise_applications_and_cloud", "workflow software, contracted revenue, growth, and stock compensation"),
		company("0000858877", "Cisco Systems", "devices_and_infrastructure", "network_infrastructure", "enterprise networking, recurring mix, and AI infrastructure demand"),
		company("0000051143", "IBM", "enterprise_software", "enterprise_applications_and_cloud", "hybrid cloud, software, infrastructure, consulting, and capital allocation"),
		company("0001596532", "Arista Networks", "devices_and_infrastructure", "network_infrastructure", "cloud networking, AI clusters, customer concentration, and operating leverage"),
	}
	sort.Slice(result, func(i, j int) bool { return result[i].CompanyID < result[j].CompanyID })
	return result
}

func InitialPeerLanes(asOf time.Time, evidenceHash string) ([]contracts.PeerLane, error) {
	if asOf.IsZero() || evidenceHash == "" {
		return nil, errors.New("peer lanes require as_of and evidence hash")
	}
	definitions := []struct {
		id, left, right, kind, question string
		questions, metrics              []string
	}{
		{
			"nvidia-amd", cik("0001045810"), cik("0000002488"), "direct_accelerated_compute_peer",
			"Compare data-center exposure, platform economics, reinvestment, margins, and competitive execution.",
			[]string{"accelerated_compute_economics", "reinvestment_and_margins"},
			[]string{"financial.revenue_growth", "financial.operating_margin", "financial.free_cash_flow", "financial.capex_intensity"},
		},
		{
			"microsoft-alphabet", cik("0000789019"), cik("0001652044"), "guarded_hyperscale_platform_peer",
			"Compare cloud and AI infrastructure, capex transmission, operating leverage, cash generation, and platform mix.",
			[]string{"cloud_ai_economics", "capex_and_cash_generation"},
			[]string{"financial.revenue_growth", "financial.operating_margin", "financial.free_cash_flow", "financial.capex_intensity", "financial.cash_conversion"},
		},
		{
			"cisco-arista", cik("0000858877"), cik("0001596532"), "guarded_network_infrastructure_peer",
			"Compare AI networking, enterprise demand, cloud concentration, recurring mix, and operating leverage.",
			[]string{"ai_networking_economics", "demand_mix_and_leverage"},
			[]string{"financial.revenue_growth", "financial.operating_margin", "financial.free_cash_flow", "financial.cash_conversion"},
		},
		{
			"salesforce-servicenow", cik("0001108524"), cik("0001373715"), "guarded_enterprise_application_peer",
			"Compare subscription growth, contracted revenue, margins, stock compensation, and cash conversion.",
			[]string{"subscription_economics", "dilution_and_cash_conversion"},
			[]string{"financial.revenue_growth", "financial.operating_margin", "financial.dilution", "financial.cash_conversion"},
		},
		{
			"oracle-microsoft", cik("0001341439"), cik("0000789019"), "guarded_enterprise_cloud_peer",
			"Compare database and cloud infrastructure, contracted economics, capex, and enterprise software exposure.",
			[]string{"enterprise_cloud_economics", "contracted_revenue_and_capex"},
			[]string{"financial.revenue_growth", "financial.operating_margin", "financial.free_cash_flow", "financial.capex_intensity"},
		},
	}
	issuerByCompany := map[string]entityresolver.Issuer{}
	for _, issuer := range entityresolver.DefaultRegistry().Issuers() {
		issuerByCompany[issuer.CompanyID] = issuer
	}
	result := make([]contracts.PeerLane, 0, len(definitions))
	for _, definition := range definitions {
		left, leftOK := issuerByCompany[definition.left]
		right, rightOK := issuerByCompany[definition.right]
		if !leftOK || !rightOK || len(left.Securities) == 0 || len(right.Securities) == 0 {
			return nil, fmt.Errorf("peer lane %q references an unresolved issuer", definition.id)
		}
		lane, err := contracts.PopulatePeerLaneHash(contracts.PeerLane{
			SchemaVersion: contracts.PeerLaneSchemaV1, LaneID: definition.id, UniverseID: UniverseID,
			CompanyIDs:     []string{definition.left, definition.right},
			SecurityIDs:    []string{left.Securities[0].SecurityID, right.Securities[0].SecurityID},
			ComparisonType: definition.kind, DecisionQuestion: definition.question,
			AllowedQuestionIDs: definition.questions, AllowedMetricIDs: definition.metrics,
			PolicyVersion: PeerLanePolicyVersion, EvidenceHashes: []string{evidenceHash},
			Enabled: false, AsOf: asOf,
		})
		if err != nil {
			return nil, err
		}
		result = append(result, lane)
	}
	sort.Slice(result, func(i, j int) bool { return result[i].LaneID < result[j].LaneID })
	return result, nil
}

func ValidateCatalog() error {
	companies := Companies()
	if len(companies) != 20 {
		return fmt.Errorf("technology catalog requires 20 companies, found %d", len(companies))
	}
	issuerByCompany := map[string]entityresolver.Issuer{}
	for _, issuer := range entityresolver.DefaultRegistry().Issuers() {
		issuerByCompany[issuer.CompanyID] = issuer
	}
	for _, item := range companies {
		issuer, exists := issuerByCompany[item.CompanyID]
		if !exists || issuer.DisplayName != item.DisplayName || item.ResearchCluster == "" ||
			item.PeerGroup == "" || item.ResearchRole == "" || len(issuer.Securities) == 0 {
			return fmt.Errorf("technology company %q does not match entity authority", item.CompanyID)
		}
	}
	return nil
}

func company(cikValue, name, cluster, peerGroup, role string) CompanyPolicy {
	return CompanyPolicy{
		CompanyID: cik(cikValue), DisplayName: name, ResearchCluster: cluster,
		PeerGroup: peerGroup, ResearchRole: role,
	}
}

func cik(value string) string {
	return "sec-cik:" + value
}
