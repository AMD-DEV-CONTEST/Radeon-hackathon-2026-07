package productscope

import (
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/comparability"
	"github.com/rvbernucci/signalforge/internal/contracts"
)

const PeerEvaluationSuiteSchemaV1 = "signalforge/technology20-peer-evaluation/v1"

type PeerEvaluationSuite struct {
	SchemaVersion string                 `json:"schema_version"`
	UniverseID    string                 `json:"universe_id"`
	AsOf          time.Time              `json:"as_of"`
	PolicyVersion string                 `json:"policy_version"`
	Lanes         []PeerEvaluationResult `json:"lanes"`
	ClaimBoundary string                 `json:"claim_boundary"`
}

type PeerEvaluationResult struct {
	LaneID      string                                 `json:"lane_id"`
	CompanyIDs  []string                               `json:"company_ids"`
	Receipts    []contracts.MetricComparabilityReceipt `json:"receipts"`
	Abstentions []contracts.TypedAbstention            `json:"abstentions"`
	Releasable  []string                               `json:"releasable_metric_ids"`
	Withheld    []string                               `json:"withheld_metric_ids"`
	Promoted    bool                                   `json:"promoted"`
	ReasonCodes []string                               `json:"reason_codes"`
}

func BuildPeerEvaluationSuite(
	catalog PublicCatalog,
	reports map[string]CompanyFinancialActivation,
	generatedAt time.Time,
) (PeerEvaluationSuite, error) {
	if err := ValidatePublicCatalog(catalog); err != nil {
		return PeerEvaluationSuite{}, err
	}
	if generatedAt.Before(catalog.AsOf) {
		return PeerEvaluationSuite{}, errors.New("peer evaluation cannot precede catalog authority")
	}
	reportByCompany := map[string]map[string]contracts.CalculationReceipt{}
	for companyID, report := range reports {
		if err := ValidateCompanyFinancialActivation(report); err != nil {
			return PeerEvaluationSuite{}, err
		}
		reportByCompany[companyID] = map[string]contracts.CalculationReceipt{}
		for _, receipt := range report.Receipts {
			reportByCompany[companyID][receipt.OperationID] = receipt
		}
	}
	companyByID := map[string]PublicCompany{}
	for _, company := range catalog.Companies {
		companyByID[company.CompanyID] = company
	}
	suite := PeerEvaluationSuite{
		SchemaVersion: PeerEvaluationSuiteSchemaV1, UniverseID: UniverseID,
		AsOf: catalog.AsOf, PolicyVersion: comparability.AnnualPolicyVersionV1,
		ClaimBoundary: "Candidate peer lanes are evaluated metric by metric. A releasable receipt authorizes only that metric and caveats; this report does not promote any pair without separate journeys and professional review.",
	}
	for _, lane := range catalog.PeerLanes {
		result := PeerEvaluationResult{
			LaneID: lane.LaneID, CompanyIDs: append([]string(nil), lane.CompanyIDs...),
			Receipts: []contracts.MetricComparabilityReceipt{}, Abstentions: []contracts.TypedAbstention{},
			Releasable: []string{}, Withheld: []string{},
			ReasonCodes: []string{"peer_journeys_and_professional_review_pending"},
		}
		leftReport, leftOK := reports[lane.CompanyIDs[0]]
		rightReport, rightOK := reports[lane.CompanyIDs[1]]
		if !leftOK || !rightOK {
			return PeerEvaluationSuite{}, errors.New("peer evaluation is missing company authority")
		}
		for _, metricID := range lane.AllowedMetricIDs {
			left, leftFound := reportByCompany[lane.CompanyIDs[0]][metricID]
			right, rightFound := reportByCompany[lane.CompanyIDs[1]][metricID]
			if !leftFound || !rightFound {
				result.Abstentions = append(result.Abstentions, comparisonAbstention(
					lane, metricID, generatedAt, "comparison_operand_unavailable",
				))
				result.Withheld = append(result.Withheld, metricID)
				continue
			}
			request, err := contracts.PopulateMetricComparabilityRequestHash(contracts.MetricComparabilityRequest{
				SchemaVersion: contracts.ComparabilityRequestSchemaV1,
				RequestID:     "comparison-" + lane.LaneID + "-" + sanitizeMetricID(metricID),
				RunID:         "peer-evaluation-" + lane.LaneID, LaneID: lane.LaneID,
				AsOf: catalog.AsOf, ReviewerPolicyVersion: comparability.AnnualPolicyVersionV1,
				Operands: []contracts.MetricComparisonOperand{
					financialOperand(companyByID[lane.CompanyIDs[0]], leftReport, left),
					financialOperand(companyByID[lane.CompanyIDs[1]], rightReport, right),
				},
			})
			if err != nil {
				return PeerEvaluationSuite{}, err
			}
			receipt, err := comparability.Evaluate(request, generatedAt, comparability.AnnualDurationPolicy())
			if err != nil {
				return PeerEvaluationSuite{}, err
			}
			result.Receipts = append(result.Receipts, receipt)
			if comparability.IsReleasable(receipt.Disposition) {
				result.Releasable = append(result.Releasable, metricID)
			} else {
				result.Withheld = append(result.Withheld, metricID)
			}
		}
		sort.Strings(result.Releasable)
		sort.Strings(result.Withheld)
		suite.Lanes = append(suite.Lanes, result)
	}
	sort.Slice(suite.Lanes, func(i, j int) bool { return suite.Lanes[i].LaneID < suite.Lanes[j].LaneID })
	return suite, ValidatePeerEvaluationSuite(suite)
}

func financialOperand(
	company PublicCompany,
	report CompanyFinancialActivation,
	receipt contracts.CalculationReceipt,
) contracts.MetricComparisonOperand {
	currentPeriod := receipt.Scope.Periods[len(receipt.Scope.Periods)-1]
	start, end := parseReceiptPeriod(currentPeriod)
	output := receipt.Outputs[0].Quantity
	concepts := operationConcepts(report, receipt)
	return contracts.MetricComparisonOperand{
		CompanyID: company.CompanyID, SecurityID: "ticker:" + company.PrimaryTicker,
		SourceObservationIDs: append([]string(nil), receipt.EvidenceRefs...),
		SourceHashes:         sourceHashes(receipt.EvidenceRefs),
		AvailableAt:          receipt.SourceAsOf, RetrievedAt: report.AsOf,
		CanonicalMetricID: receipt.OperationID, MetricVersion: receipt.FormulaVersion,
		TaxonomyConcept: strings.Join(concepts, "+"),
		Value:           output.Value, Unit: output.Unit, Currency: output.Currency, Scale: output.Scale,
		SignPolicy: "formula_defined", DimensionalIdentity: "consolidated",
		PeriodType: periodType(start, end), FiscalStart: &start, FiscalEnd: end,
		FilingDate: receipt.SourceAsOf, AccountingPerimeter: "consolidated_periodic_filing",
		DefinitionID:     receipt.OperationID + "/" + receipt.FormulaVersion,
		RestatementState: "active_amendment_chain", SupersessionState: "active",
	}
}

func operationConcepts(report CompanyFinancialActivation, receipt contracts.CalculationReceipt) []string {
	concepts := []string{}
	for _, input := range receipt.NormalizedInputs {
		for _, spec := range companyOperationSpecs {
			if spec.OperationID != receipt.OperationID {
				continue
			}
			canonical := spec.Inputs[input.InputID]
			concepts = append(concepts, report.SourceConcepts[canonical]...)
		}
	}
	sort.Strings(concepts)
	return uniqueStrings(concepts)
}

func parseReceiptPeriod(value string) (time.Time, time.Time) {
	parts := strings.Split(value, "/")
	if len(parts) != 2 {
		return time.Time{}, time.Time{}
	}
	start, _ := time.Parse("2006-01-02", parts[0])
	end, _ := time.Parse("2006-01-02", parts[1])
	return start, end
}

func periodType(start, end time.Time) string {
	if start.Equal(end) {
		return "instant"
	}
	return "duration"
}

func sourceHashes(refs []string) []string {
	hashes := make([]string, 0, len(refs))
	for _, ref := range refs {
		parts := strings.Split(ref, ":")
		hashes = append(hashes, parts[len(parts)-1])
	}
	sort.Strings(hashes)
	return uniqueStrings(hashes)
}

func comparisonAbstention(
	lane PublicPeerLane,
	metricID string,
	generatedAt time.Time,
	code string,
) contracts.TypedAbstention {
	return contracts.TypedAbstention{
		SchemaVersion: contracts.TypedAbstentionSchemaV1,
		AbstentionID:  "abstention-" + lane.LaneID + "-" + sanitizeMetricID(metricID),
		RequestID:     "comparison-" + lane.LaneID + "-" + sanitizeMetricID(metricID),
		RunID:         "peer-evaluation-" + lane.LaneID, Code: code,
		Message:    fmt.Sprintf("SignalForge withheld %s for %s because the required authorized operands are unavailable.", metricID, lane.LaneID),
		CompanyIDs: append([]string(nil), lane.CompanyIDs...), MetricIDs: []string{metricID},
		GeneratedAt: generatedAt,
	}
}

func sanitizeMetricID(value string) string {
	return strings.NewReplacer(".", "-", "_", "-").Replace(value)
}

func ValidatePeerEvaluationSuite(suite PeerEvaluationSuite) error {
	if suite.SchemaVersion != PeerEvaluationSuiteSchemaV1 || suite.UniverseID != UniverseID ||
		suite.AsOf.IsZero() || suite.PolicyVersion != comparability.AnnualPolicyVersionV1 ||
		len(suite.Lanes) != 5 || suite.ClaimBoundary == "" {
		return errors.New("peer evaluation suite envelope is invalid")
	}
	for _, lane := range suite.Lanes {
		if lane.LaneID == "" || len(lane.CompanyIDs) != 2 || lane.Promoted ||
			len(lane.ReasonCodes) == 0 ||
			len(lane.Receipts)+len(lane.Abstentions) == 0 {
			return errors.New("peer evaluation lane is invalid or over-promoted")
		}
		for _, receipt := range lane.Receipts {
			if err := contracts.ValidateMetricComparabilityReceipt(receipt); err != nil {
				return err
			}
		}
	}
	return nil
}
