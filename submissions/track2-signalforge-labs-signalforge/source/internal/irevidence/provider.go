package irevidence

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/localagent"
	"github.com/rvbernucci/signalforge/internal/retrieval"
	"github.com/rvbernucci/signalforge/internal/roles"
)

var irDocumentTypes = []string{
	"corporate_profile_and_history",
	"business_products_and_segments",
	"earnings_release",
	"prepared_remarks",
	"official_earnings_transcript",
	"shareholder_letter",
	"investor_presentation",
	"investor_day_and_conference_material",
	"guidance_and_outlook",
	"capital_allocation_update",
	"governance_document",
	"board_and_committee_material",
	"annual_meeting_material",
	"official_strategy_or_risk_update",
}

type Provider struct {
	index       *retrieval.LexicalIndex
	projections map[string]SemanticProjection
	resolvers   map[string]*retrieval.Resolver
	rights      map[string]string
}

func NewProvider(
	registry SourceRegistryV2,
	chunks []retrieval.Chunk,
	projections map[string]SemanticProjection,
	evaluationOnly bool,
) (*Provider, error) {
	if err := ValidateSourceRegistryV2(registry); err != nil {
		return nil, err
	}
	companySources := make(map[string]SourceDefinitionV2, len(registry.Sources))
	for _, source := range registry.Sources {
		if strings.HasSuffix(source.RightsClass, "pending_review") && !evaluationOnly {
			return nil, fmt.Errorf("source rights are pending for %s", source.CompanyID)
		}
		companySources[source.CompanyID] = source
	}
	byCompany := make(map[string][]retrieval.Chunk)
	for _, chunk := range chunks {
		if _, ok := companySources[chunk.CompanyID]; !ok {
			return nil, fmt.Errorf("chunk %q is outside the source registry", chunk.ChunkID)
		}
		projection, ok := projections[chunk.ChunkID]
		if !ok || projection.CompanyID != chunk.CompanyID || projection.SourceContentSHA256 != chunk.ContentSHA256 {
			return nil, fmt.Errorf("projection for chunk %q is missing or does not resolve", chunk.ChunkID)
		}
		byCompany[chunk.CompanyID] = append(byCompany[chunk.CompanyID], chunk)
	}
	index, err := retrieval.NewLexicalIndex(chunks)
	if err != nil {
		return nil, err
	}
	provider := &Provider{
		index: index, projections: projections,
		resolvers: make(map[string]*retrieval.Resolver, len(byCompany)),
		rights:    make(map[string]string, len(companySources)),
	}
	for companyID, source := range companySources {
		policy, err := registry.CitationPolicy([]string{companyID})
		if err != nil {
			return nil, err
		}
		companyChunks := byCompany[companyID]
		if len(companyChunks) > 0 {
			resolver, err := retrieval.NewResolverWithPolicy(companyChunks, policy.AllowedHosts, policy.RestrictedHostPrefixes)
			if err != nil {
				return nil, fmt.Errorf("build resolver for %s: %w", companyID, err)
			}
			for _, chunk := range companyChunks {
				if _, err := resolver.OpenTarget(chunk.ChunkID, 0); err != nil {
					return nil, fmt.Errorf("validate source for chunk %q: %w", chunk.ChunkID, err)
				}
			}
			provider.resolvers[companyID] = resolver
		}
		provider.rights[companyID] = source.RightsClass
	}
	return provider, nil
}

func (provider *Provider) Load(ctx context.Context, request contracts.ContextRequest) (localagent.Material, error) {
	select {
	case <-ctx.Done():
		return localagent.Material{}, ctx.Err()
	default:
	}
	if len(request.Scope.CompanyIDs) == 0 || request.Scope.AsOf.IsZero() {
		return localagent.Material{}, errors.New("IR retrieval requires explicit company and as_of scope")
	}
	documentTypes := documentTypesForRole(request.SpecialistRole)
	if len(documentTypes) == 0 {
		return localagent.Material{}, fmt.Errorf("role %q cannot consume IR evidence", request.SpecialistRole)
	}
	perCompany := max(1, min(4, 8/len(request.Scope.CompanyIDs)))
	items := make([]contracts.EvidenceItem, 0, perCompany*len(request.Scope.CompanyIDs))
	missing := make([]string, 0)
	seen := make(map[string]bool)
	retrievalStats := retrieval.SearchStats{}
	for _, companyID := range request.Scope.CompanyIDs {
		if _, ok := provider.rights[companyID]; !ok {
			return localagent.Material{}, fmt.Errorf("company %q is outside the IR registry", companyID)
		}
		resolver := provider.resolvers[companyID]
		if resolver == nil {
			missing = append(missing, "No eligible official investor-relations evidence was collected for "+companyID+".")
			continue
		}
		hits, stats, err := provider.index.SearchWithStats(retrieval.Query{
			Text: request.ResearchQuestion + " " + request.Objective + " " + retrievalProfile(request.SpecialistRole),
			AsOf: request.Scope.AsOf, CompanyIDs: []string{companyID}, DocumentTypes: documentTypes, TopK: perCompany,
		})
		if err != nil {
			return localagent.Material{}, err
		}
		retrievalStats.EligibleCandidates += stats.EligibleCandidates
		retrievalStats.MatchedCandidates += stats.MatchedCandidates
		retrievalStats.SelectedCandidates += stats.SelectedCandidates
		retrievalStats.RejectedCandidates += stats.RejectedCandidates
		if len(hits) == 0 {
			missing = append(missing, "No point-in-time official investor-relations evidence matched "+companyID+".")
			continue
		}
		for _, hit := range hits {
			if seen[hit.Chunk.ChunkID] {
				continue
			}
			seen[hit.Chunk.ChunkID] = true
			projection := provider.projections[hit.Chunk.ChunkID]
			target, err := resolver.OpenTarget(hit.Chunk.ChunkID, request.Scope.AsOf.Unix())
			if err != nil {
				return localagent.Material{}, err
			}
			warnings := []string{
				"authority_tier=" + hit.Chunk.AuthorityTier,
				"rights_class=" + provider.rights[companyID],
				"numerically_silent_projection",
				"source_content_sha256=" + hit.Chunk.ContentSHA256,
			}
			if hit.Chunk.ForwardLooking {
				warnings = append(warnings, "forward_looking")
			}
			if hit.Chunk.Promotional {
				warnings = append(warnings, "issuer_promotional_material")
			}
			items = append(items, contracts.EvidenceItem{
				EvidenceRef: contracts.EvidenceRef{
					EvidenceID: hit.Chunk.ChunkID, SourceType: "official_investor_relations",
					DocumentSection: hit.Chunk.Section, Locator: target.SourceURI + "#" + target.Locator,
					ContentSHA: projection.ProjectionSHA256, AsOf: hit.Chunk.AvailableAt,
				},
				State: contracts.EvidenceAvailable, Statement: projection.Text, Warnings: warnings,
			})
		}
	}
	sort.Slice(items, func(left, right int) bool {
		return items[left].EvidenceRef.EvidenceID < items[right].EvidenceRef.EvidenceID
	})
	bundle := contracts.EvidenceBundle{
		SchemaVersion: contracts.SchemaVersionV1,
		BundleID:      "bundle-ir-" + request.ContextRequestID,
		RunID:         request.RunID,
		StepID:        request.StepID,
		AsOf:          request.Scope.AsOf,
		Items:         items,
		Missing:       missing,
	}
	if err := contracts.ValidateEvidenceBundle(bundle); err != nil {
		return localagent.Material{}, err
	}
	return localagent.Material{
		Evidence: bundle,
		Retrieval: localagent.RetrievalTrace{
			Method:                 "bm25/v1",
			CandidateCount:         retrievalStats.MatchedCandidates,
			SelectedCandidateCount: retrievalStats.SelectedCandidates,
			RejectedCandidateCount: retrievalStats.RejectedCandidates,
			CandidateCountsKnown:   true,
		},
	}, nil
}

func documentTypesForRole(roleID string) []string {
	if roleID == roles.EvidenceCritic {
		return append([]string(nil), irDocumentTypes...)
	}
	result := make([]string, 0)
	for _, documentType := range irDocumentTypes {
		if containsRole(roles.IRConsumerRoles(documentType), roleID) {
			result = append(result, documentType)
		}
	}
	return result
}

func containsRole(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func retrievalProfile(roleID string) string {
	return map[string]string{
		roles.BusinessStrategy:    "business history products segments strategy priorities",
		roles.AccountingReporting: "earnings reporting non-GAAP reconciliation comparability",
		roles.FinancialQuality:    "revenue earnings cash generation reinvestment margins capital allocation",
		roles.RiskContrarian:      "risk uncertainty governance conflict adverse evidence",
		roles.EvidenceCritic:      "evidence authority risk governance results",
	}[roleID]
}

var _ localagent.MaterialProvider = (*Provider)(nil)
