package productscope

import (
	"errors"
	"sort"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

func BindRequestAuthority(
	request contracts.ResearchRequest,
	catalog PublicCatalog,
	peers PeerEvaluationSuite,
) (contracts.ResearchRequest, error) {
	if err := contracts.ValidateResearchRequest(request); err != nil {
		return contracts.ResearchRequest{}, err
	}
	if err := ValidatePublicCatalog(catalog); err != nil {
		return contracts.ResearchRequest{}, err
	}
	if err := ValidatePeerEvaluationSuite(peers); err != nil {
		return contracts.ResearchRequest{}, err
	}
	companies := map[string]PublicCompany{}
	for _, company := range catalog.Companies {
		companies[company.CompanyID] = company
	}
	entityIDs := []string{}
	for _, entity := range request.Entities {
		if entity.EntityType != "company" || !entity.Resolved {
			continue
		}
		company, ok := companies[entity.EntityID]
		if !ok {
			return contracts.ResearchRequest{}, errors.New("request company is outside the governed product universe")
		}
		entityIDs = append(entityIDs, entity.EntityID)
		request.AuthorityRefs = append(request.AuthorityRefs, "company-profile-sha256:"+company.ProfileSHA256)
		request.AuthorityReasonCodes = append(request.AuthorityReasonCodes, company.ReasonCodes...)
	}
	if len(entityIDs) == 0 {
		return contracts.ResearchRequest{}, errors.New("product request requires a governed company")
	}
	request.AuthorityState = "data_ready"
	if request.Comparison.Mode == "peer" {
		if len(entityIDs) != 2 {
			return contracts.ResearchRequest{}, errors.New("peer request requires exactly two governed companies")
		}
		lane := findPeerEvaluation(entityIDs, peers)
		if lane == nil {
			request.AuthorityState = "limited"
			request.AuthorityReasonCodes = append(request.AuthorityReasonCodes, "peer_lane_not_defined")
		} else {
			request.AuthorityRefs = append(request.AuthorityRefs, peerReceiptRefs(*lane)...)
			request.AuthorityReasonCodes = append(request.AuthorityReasonCodes, lane.ReasonCodes...)
			if lane.Promoted {
				request.AuthorityState = "comparison_ready"
			} else {
				request.AuthorityState = "limited"
			}
		}
	} else if len(entityIDs) == 1 && companies[entityIDs[0]].ResearchEnabled {
		request.AuthorityState = "research_ready"
	}
	request.AuthorityRefs = sortedUnique(request.AuthorityRefs)
	request.AuthorityReasonCodes = sortedUnique(request.AuthorityReasonCodes)
	if err := contracts.ValidateResearchRequest(request); err != nil {
		return contracts.ResearchRequest{}, err
	}
	return request, nil
}

func findPeerEvaluation(companyIDs []string, peers PeerEvaluationSuite) *PeerEvaluationResult {
	for index := range peers.Lanes {
		if sameCompanySet(companyIDs, peers.Lanes[index].CompanyIDs) {
			return &peers.Lanes[index]
		}
	}
	return nil
}

func peerReceiptRefs(lane PeerEvaluationResult) []string {
	result := []string{}
	for _, receipt := range lane.Receipts {
		result = append(result, "comparability-receipt-sha256:"+receipt.ReceiptSHA256)
	}
	return result
}

func sameCompanySet(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	a, b := append([]string(nil), left...), append([]string(nil), right...)
	sort.Strings(a)
	sort.Strings(b)
	for index := range a {
		if a[index] != b[index] {
			return false
		}
	}
	return true
}

func sortedUnique(values []string) []string {
	sort.Strings(values)
	if len(values) == 0 {
		return []string{}
	}
	result := values[:0]
	for _, value := range values {
		if value != "" && (len(result) == 0 || result[len(result)-1] != value) {
			result = append(result, value)
		}
	}
	return result
}
