package producteval

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/localagent"
	"github.com/rvbernucci/signalforge/internal/numericalcontext"
	"github.com/rvbernucci/signalforge/internal/productscope"
	"github.com/rvbernucci/signalforge/internal/roles"
)

// Provider exposes only governed, value-silent material to local agents. Exact values remain in
// immutable calculation receipts and numerical variables, never in model-visible prose.
type Provider struct {
	catalog   productscope.PublicCatalog
	companies map[string]productscope.PublicCompany
	reports   map[string]productscope.CompanyFinancialActivation
	peers     productscope.PeerEvaluationSuite
}

func LoadProvider(catalogPath, financialDirectory, peerPath string) (*Provider, error) {
	var catalog productscope.PublicCatalog
	if err := readJSON(catalogPath, &catalog); err != nil {
		return nil, fmt.Errorf("load product catalog: %w", err)
	}
	if err := productscope.ValidatePublicCatalog(catalog); err != nil {
		return nil, err
	}
	var peers productscope.PeerEvaluationSuite
	if err := readJSON(peerPath, &peers); err != nil {
		return nil, fmt.Errorf("load peer authority: %w", err)
	}
	if err := productscope.ValidatePeerEvaluationSuite(peers); err != nil {
		return nil, err
	}
	entries, err := os.ReadDir(financialDirectory)
	if err != nil {
		return nil, fmt.Errorf("read financial authority directory: %w", err)
	}
	reports := map[string]productscope.CompanyFinancialActivation{}
	for _, entry := range entries {
		if entry.IsDir() || filepath.Ext(entry.Name()) != ".json" || entry.Name() == "manifest.json" {
			continue
		}
		var report productscope.CompanyFinancialActivation
		if err := readJSON(filepath.Join(financialDirectory, entry.Name()), &report); err != nil {
			return nil, err
		}
		if err := productscope.ValidateCompanyFinancialActivation(report); err != nil {
			return nil, fmt.Errorf("validate %s: %w", entry.Name(), err)
		}
		if _, exists := reports[report.CompanyID]; exists {
			return nil, fmt.Errorf("duplicate financial authority for %s", report.CompanyID)
		}
		reports[report.CompanyID] = report
	}
	if len(reports) != len(catalog.Companies) {
		return nil, fmt.Errorf("financial authority covers %d companies, want %d", len(reports), len(catalog.Companies))
	}
	companies := make(map[string]productscope.PublicCompany, len(catalog.Companies))
	for _, company := range catalog.Companies {
		if _, ok := reports[company.CompanyID]; !ok {
			return nil, fmt.Errorf("missing financial authority for %s", company.CompanyID)
		}
		companies[company.CompanyID] = company
	}
	return &Provider{catalog: catalog, companies: companies, reports: reports, peers: peers}, nil
}

func (provider *Provider) Load(ctx context.Context, request contracts.ContextRequest) (localagent.Material, error) {
	select {
	case <-ctx.Done():
		return localagent.Material{}, ctx.Err()
	default:
	}
	if provider == nil || len(request.Scope.CompanyIDs) == 0 {
		return localagent.Material{}, errors.New("product evaluation requires explicit company authority")
	}
	receipts := []contracts.CalculationReceipt{}
	evidence := []contracts.EvidenceItem{}
	missing := []string{}
	comparisonAllowed, comparisonScoped := provider.comparisonOperationPolicy(request.Scope.CompanyIDs)
	for _, companyID := range request.Scope.CompanyIDs {
		company, ok := provider.companies[companyID]
		if !ok {
			return localagent.Material{}, fmt.Errorf("company %q is outside the governed product universe", companyID)
		}
		report := provider.reports[companyID]
		selected, unavailable := selectFinancialAuthority(report, request)
		if comparisonScoped {
			selected, unavailable = filterComparisonReceipts(selected, unavailable, comparisonAllowed)
		}
		receipts = append(receipts, selected...)
		missing = append(missing, unavailable...)
		evidence = append(evidence, receiptEvidence(company, selected)...)
		if request.SpecialistRole == roles.AccountingReporting {
			evidence = append(evidence, accountingAuthorityEvidence(company, report, selected, request.Scope.AsOf))
		}
	}
	if request.Scope.AsOf.After(provider.catalog.AsOf) {
		missing = append(missing, "The governed Technology 20 dataset is frozen before the requested as-of boundary; no later observation was inferred.")
	}
	missing = normalizeModelVisibleMissing(missing)
	roleMissing := roleMissingEvidence(request.SpecialistRole)
	missing = append(missing, roleMissing...)
	evidence = append(evidence, roleScopePolicyEvidence(request, roleMissing)...)
	comparisonEvidence, comparisonMissing := provider.comparisonMaterial(request)
	evidence = append(evidence, comparisonEvidence...)
	missing = append(missing, comparisonMissing...)
	evidence = append(evidence, governedMissingEvidence(request, missing)...)
	sort.Slice(receipts, func(i, j int) bool {
		if receipts[i].OperationID != receipts[j].OperationID {
			return receipts[i].OperationID < receipts[j].OperationID
		}
		return receipts[i].Scope.CompanyIDs[0] < receipts[j].Scope.CompanyIDs[0]
	})
	material := localagent.Material{
		Evidence: contracts.EvidenceBundle{
			SchemaVersion: contracts.SchemaVersionV1,
			BundleID:      "bundle-" + request.ContextRequestID,
			RunID:         request.RunID,
			StepID:        request.StepID,
			AsOf:          minTime(request.Scope.AsOf, provider.catalog.AsOf),
			Items:         uniqueEvidence(evidence),
			Missing:       uniqueStrings(missing),
		},
		CalculationReceipts: receipts,
		Retrieval: localagent.RetrievalTrace{
			Method: "governed_receipt_selection/v1",
		},
	}
	if numericalcontext.HasEligibleOutputs(receipts) {
		numerical, err := numericalcontext.Compile(numericalcontext.Options{
			ContextID:           "numerical-" + request.ContextRequestID,
			RunID:               request.RunID,
			AsOf:                minTime(request.Scope.AsOf, provider.catalog.AsOf),
			EntityNames:         provider.entityNames(request.Scope.CompanyIDs),
			EntityFiscalPeriods: fiscalPeriods(receipts),
		}, receipts)
		if err != nil {
			return localagent.Material{}, err
		}
		material.NumericalContext = &numerical
	}
	if err := contracts.ValidateEvidenceBundle(material.Evidence); err != nil {
		return localagent.Material{}, err
	}
	return material, nil
}

func (provider *Provider) comparisonOperationPolicy(companyIDs []string) (map[string]bool, bool) {
	if len(companyIDs) != 2 {
		return nil, false
	}
	allowed := map[string]bool{}
	for _, lane := range provider.peers.Lanes {
		if !sameCompanySet(lane.CompanyIDs, companyIDs) {
			continue
		}
		for _, receipt := range lane.Receipts {
			if receipt.Disposition == contracts.ComparisonComparable ||
				receipt.Disposition == contracts.ComparisonComparableWithCaveat {
				allowed[receipt.Operands[0].CanonicalMetricID] = true
			}
		}
		return allowed, true
	}
	// A two-company request without a governed lane is still comparison-scoped and therefore
	// receives no cross-company numerical authority.
	return allowed, true
}

func filterComparisonReceipts(
	receipts []contracts.CalculationReceipt,
	missing []string,
	allowed map[string]bool,
) ([]contracts.CalculationReceipt, []string) {
	filtered := make([]contracts.CalculationReceipt, 0, len(receipts))
	for _, receipt := range receipts {
		if allowed[receipt.OperationID] {
			filtered = append(filtered, receipt)
			continue
		}
		missing = append(missing,
			"SignalForge withheld "+receipt.OperationID+
				" because the governed peer policy did not authorize a cross-company direction.")
	}
	return filtered, uniqueStrings(missing)
}

func selectFinancialAuthority(
	report productscope.CompanyFinancialActivation,
	request contracts.ContextRequest,
) ([]contracts.CalculationReceipt, []string) {
	allowed := map[string]bool{}
	for _, operationID := range request.CapabilityIDs {
		allowed[operationID] = true
	}
	if allowed["financial.margin"] {
		allowed["financial.operating_margin"] = true
	}
	selected := []contracts.CalculationReceipt{}
	for _, receipt := range report.Receipts {
		if allowed[receipt.OperationID] {
			selected = append(selected, receipt)
		}
	}
	missing := []string{}
	for _, abstention := range report.Abstentions {
		if len(abstention.MetricIDs) == 1 && allowed[abstention.MetricIDs[0]] {
			missing = append(missing, abstention.Message)
		}
	}
	return selected, missing
}

func receiptEvidence(
	company productscope.PublicCompany,
	receipts []contracts.CalculationReceipt,
) []contracts.EvidenceItem {
	result := []contracts.EvidenceItem{}
	for _, receipt := range receipts {
		for _, input := range receipt.NormalizedInputs {
			statement := fmt.Sprintf(
				"%s has an authorized normalized SEC input for %s in %s; the exact value remains in deterministic receipt %s.",
				company.DisplayName, input.InputID, input.Quantity.Period, receipt.ReceiptID,
			)
			for _, evidenceID := range input.EvidenceRefs {
				result = append(result, contracts.EvidenceItem{
					EvidenceRef: contracts.EvidenceRef{
						EvidenceID: evidenceID,
						SourceType: "sec_companyfacts_normalized_input",
						Locator:    "signalforge://sec-companyfacts/" + company.CompanyID + "#" + evidenceID,
						ContentSHA: hashText(statement),
						AsOf:       receipt.SourceAsOf,
					},
					State:     contracts.EvidenceAvailable,
					Statement: statement,
					Warnings: []string{
						"exact_value_withheld_from_model_prompt",
						"deterministic_receipt_required_for_numeric_release",
					},
				})
			}
		}
	}
	return result
}

func accountingAuthorityEvidence(
	company productscope.PublicCompany,
	report productscope.CompanyFinancialActivation,
	receipts []contracts.CalculationReceipt,
	asOf time.Time,
) contracts.EvidenceItem {
	periods := []string{}
	for _, receipt := range receipts {
		periods = append(periods, receipt.Scope.Periods...)
	}
	concepts := []string{}
	for _, values := range report.SourceConcepts {
		concepts = append(concepts, values...)
	}
	periods = uniqueStrings(periods)
	concepts = uniqueStrings(concepts)
	statement := company.DisplayName +
		"'s accounting authority is limited to consolidated, dimensionless periodic SEC facts. " +
		"Exact fiscal periods and US GAAP concepts remain attached to deterministic receipts; " +
		"cross-company use requires a metric comparability receipt."
	warnings := []string{
		"accounting_perimeter:" + report.ConsolidationPolicy,
		"capex_perimeter:" + report.CapexPerimeterPolicy,
		"comparability_requires_metric_receipt",
	}
	if len(periods) > 0 {
		warnings = append(warnings, "authorized_periods:"+strings.Join(periods, ","))
	}
	if len(concepts) > 0 {
		warnings = append(warnings, "authorized_taxonomy_concepts:"+strings.Join(concepts, ","))
	}
	return contracts.EvidenceItem{
		EvidenceRef: contracts.EvidenceRef{
			EvidenceID:      "accounting-authority:" + company.CompanyID,
			SourceType:      "accounting_authority_policy",
			DocumentSection: "period-taxonomy-perimeter-comparability",
			Locator:         "signalforge://accounting-authority/" + company.CompanyID,
			ContentSHA:      hashText(statement + "\n" + strings.Join(warnings, "\n")),
			AsOf:            asOf,
		},
		State:     contracts.EvidenceAvailable,
		Statement: statement,
		Warnings:  warnings,
	}
}

func (provider *Provider) comparisonMaterial(request contracts.ContextRequest) ([]contracts.EvidenceItem, []string) {
	if len(request.Scope.CompanyIDs) != 2 {
		return nil, nil
	}
	for _, lane := range provider.peers.Lanes {
		if !sameCompanySet(lane.CompanyIDs, request.Scope.CompanyIDs) {
			continue
		}
		items := []contracts.EvidenceItem{}
		missing := []string{}
		for _, receipt := range lane.Receipts {
			metricID := receipt.Operands[0].CanonicalMetricID
			if receipt.AsOf.After(request.Scope.AsOf) {
				missing = append(missing,
					"SignalForge withheld "+metricID+
						" because its governed comparability authority is later than the requested as-of boundary.")
				continue
			}
			state := contracts.EvidenceAvailable
			evidenceID := "comparison:" + receipt.ReceiptID
			if receipt.Disposition == contracts.ComparisonNotComparable {
				state = contracts.EvidenceIncomparable
			}
			statement := fmt.Sprintf(
				"Metric %s has deterministic comparison disposition %s under policy %s.",
				metricID, receipt.Disposition, receipt.ReviewerPolicyVersion,
			)
			items = append(items, contracts.EvidenceItem{
				EvidenceRef: contracts.EvidenceRef{
					EvidenceID: evidenceID,
					SourceType: "metric_comparability_receipt",
					Locator:    "signalforge://comparability/" + receipt.ReceiptID,
					ContentSHA: receipt.ReceiptSHA256,
					// The receipt's as-of is the governed factual boundary. GeneratedAt is
					// processing lineage and may legitimately be later than the request.
					AsOf: receipt.AsOf,
				},
				State:        state,
				Statement:    statement,
				Warnings:     append(append([]string(nil), receipt.RequiredCaveatIDs...), receipt.ReasonCodes...),
				ConflictRefs: comparisonConflictRefs(receipt),
			})
		}
		for _, abstention := range lane.Abstentions {
			missing = append(missing, abstention.Message)
		}
		if !lane.Promoted {
			missing = append(missing, "This peer lane is evaluation-only and has not been promoted for product release.")
		}
		return items, missing
	}
	return nil, []string{"No governed peer lane exists for the requested company pair."}
}

func comparisonConflictRefs(receipt contracts.MetricComparabilityReceipt) []string {
	if receipt.Disposition != contracts.ComparisonNotComparable {
		return nil
	}
	result := make([]string, 0, len(receipt.Operands))
	for _, operand := range receipt.Operands {
		result = append(result, operand.CompanyID+":"+operand.CanonicalMetricID)
	}
	return result
}

func roleMissingEvidence(roleID string) []string {
	switch roleID {
	case roles.BusinessStrategy:
		return []string{"Rights-approved company narrative is not activated; business-model claims must abstain or remain limited to SEC-derived authority."}
	case roles.EconomicsTransmission:
		return []string{"No frozen FRED vintage is activated; macro transmission remains an explicit conditional hypothesis, not an observed causal claim."}
	case roles.Valuation:
		return []string{"No point-in-time market price or reviewed FCFF scenario authority is activated; price-implied valuation must abstain."}
	case roles.MarketBehavior:
		return []string{"No point-in-time market series is activated; beta, volatility, drawdown, and price-behavior claims must abstain."}
	default:
		return nil
	}
}

func roleScopePolicyEvidence(request contracts.ContextRequest, missing []string) []contracts.EvidenceItem {
	if len(missing) == 0 {
		return nil
	}
	statement := "The governed product scope does not activate the source authority required by " +
		request.SpecialistRole + "; related company claims must abstain."
	return []contracts.EvidenceItem{{
		EvidenceRef: contracts.EvidenceRef{
			EvidenceID:      "product-scope:" + request.SpecialistRole,
			SourceType:      "product_scope_policy",
			DocumentSection: "governed release scope",
			Locator:         "signalforge://product-scope/" + request.SpecialistRole,
			ContentSHA:      hashText(statement),
			AsOf:            request.Scope.AsOf,
		},
		State:     contracts.EvidenceAvailable,
		Statement: statement,
		Warnings:  []string{"scope_boundary_only", "not_company_evidence"},
	}}
}

func governedMissingEvidence(request contracts.ContextRequest, missing []string) []contracts.EvidenceItem {
	result := make([]contracts.EvidenceItem, 0, len(missing))
	for _, statement := range uniqueStrings(missing) {
		statement = strings.TrimSpace(statement)
		if statement == "" {
			continue
		}
		digest := hashText(statement)
		result = append(result, contracts.EvidenceItem{
			EvidenceRef: contracts.EvidenceRef{
				EvidenceID:      "product-scope:" + request.SpecialistRole + ":" + digest[:16],
				SourceType:      "product_scope_policy",
				DocumentSection: "governed release scope",
				Locator:         "signalforge://product-scope/" + request.SpecialistRole + "/" + digest[:16],
				ContentSHA:      digest,
				AsOf:            request.Scope.AsOf,
			},
			State:     contracts.EvidenceAvailable,
			Statement: statement,
			Warnings:  []string{"scope_boundary_only", "not_company_evidence"},
		})
	}
	return result
}

func (provider *Provider) entityNames(companyIDs []string) map[string]string {
	result := make(map[string]string, len(companyIDs))
	for _, companyID := range companyIDs {
		result[companyID] = provider.companies[companyID].PrimaryTicker
	}
	return result
}

func fiscalPeriods(receipts []contracts.CalculationReceipt) map[string]numericalcontext.FiscalPeriod {
	result := map[string]numericalcontext.FiscalPeriod{}
	for _, receipt := range receipts {
		if len(receipt.Scope.CompanyIDs) != 1 {
			continue
		}
		for _, period := range receipt.Scope.Periods {
			start, end, ok := parseDuration(period)
			if !ok {
				continue
			}
			current, exists := result[receipt.Scope.CompanyIDs[0]]
			if !exists || end.After(current.End) {
				result[receipt.Scope.CompanyIDs[0]] = numericalcontext.FiscalPeriod{Start: start, End: end}
			}
		}
	}
	return result
}

func parseDuration(value string) (time.Time, time.Time, bool) {
	parts := strings.Split(value, "/")
	if len(parts) != 2 {
		return time.Time{}, time.Time{}, false
	}
	start, startErr := time.Parse("2006-01-02", parts[0])
	end, endErr := time.Parse("2006-01-02", parts[1])
	return start, end, startErr == nil && endErr == nil && end.After(start)
}

func uniqueEvidence(values []contracts.EvidenceItem) []contracts.EvidenceItem {
	byID := map[string]contracts.EvidenceItem{}
	for _, value := range values {
		if existing, ok := byID[value.EvidenceRef.EvidenceID]; ok {
			existing.Warnings = uniqueStrings(append(existing.Warnings, value.Warnings...))
			byID[value.EvidenceRef.EvidenceID] = existing
			continue
		}
		value.Warnings = uniqueStrings(value.Warnings)
		byID[value.EvidenceRef.EvidenceID] = value
	}
	result := make([]contracts.EvidenceItem, 0, len(byID))
	for _, value := range byID {
		result = append(result, value)
	}
	sort.Slice(result, func(i, j int) bool {
		return result[i].EvidenceRef.EvidenceID < result[j].EvidenceRef.EvidenceID
	})
	return result
}

func uniqueStrings(values []string) []string {
	set := map[string]bool{}
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value != "" {
			set[value] = true
		}
	}
	result := make([]string, 0, len(set))
	for value := range set {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}

// Private activation records retain their exact reason codes and messages. The prompt projection
// removes only bounded cardinal wording that the numerical-silence guard would otherwise treat as
// a model-owned quantity; this never upgrades availability or changes lineage.
func normalizeModelVisibleMissing(values []string) []string {
	result := make([]string, 0, len(values))
	replacements := []struct {
		old string
		new string
	}{
		{
			old: "two annual standardized revenue periods unavailable",
			new: "the required annual standardized revenue history is unavailable",
		},
		{
			old: "one or both authorized operands are unavailable",
			new: "the required authorized operands are unavailable",
		},
	}
	for _, value := range values {
		for _, replacement := range replacements {
			value = strings.ReplaceAll(value, replacement.old, replacement.new)
		}
		result = append(result, value)
	}
	return uniqueStrings(result)
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

func minTime(left, right time.Time) time.Time {
	if left.Before(right) {
		return left
	}
	return right
}

func hashText(value string) string {
	digest := sha256.Sum256([]byte(value))
	return hex.EncodeToString(digest[:])
}

func readJSON(path string, target any) error {
	payload, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(payload, target)
}
