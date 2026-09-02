package comparability

import (
	"errors"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

const (
	PolicyVersionV1       = "metric-comparability/v1"
	AnnualPolicyVersionV1 = "metric-comparability-annual-duration/v1"
)

type Policy struct {
	Version                 string
	RequireExactPeriod      bool
	AllowAnnualPeriodCaveat bool
	MaxFiscalEndDeltaDays   int
	RequireExactMarketDate  bool
}

func DefaultPolicy() Policy {
	return Policy{
		Version:                PolicyVersionV1,
		RequireExactPeriod:     true,
		RequireExactMarketDate: true,
	}
}

func AnnualDurationPolicy() Policy {
	return Policy{
		Version:                 AnnualPolicyVersionV1,
		AllowAnnualPeriodCaveat: true,
		MaxFiscalEndDeltaDays:   190,
		RequireExactMarketDate:  true,
	}
}

func Evaluate(request contracts.MetricComparabilityRequest, generatedAt time.Time, policy Policy) (contracts.MetricComparabilityReceipt, error) {
	if err := contracts.ValidateMetricComparabilityRequest(request); err != nil {
		return contracts.MetricComparabilityReceipt{}, err
	}
	if policy.Version == "" || request.ReviewerPolicyVersion != policy.Version {
		return contracts.MetricComparabilityReceipt{}, errors.New("comparison policy version is missing or mismatched")
	}
	if generatedAt.IsZero() || generatedAt.Before(request.AsOf) {
		return contracts.MetricComparabilityReceipt{}, errors.New("receipt generation time cannot precede request as_of")
	}
	left, right := request.Operands[0], request.Operands[1]
	invariants := []contracts.ComparabilityInvariant{
		check("distinct_issuers", left.CompanyID != right.CompanyID, "comparison operands must belong to distinct issuers"),
		check("same_metric", left.CanonicalMetricID == right.CanonicalMetricID, "canonical metric IDs differ"),
		check("same_metric_version", left.MetricVersion == right.MetricVersion, "metric policy versions differ"),
		check("same_unit", left.Unit == right.Unit, "units differ"),
		check("same_currency", left.Currency == right.Currency, "currencies differ"),
		check("same_scale", left.Scale == right.Scale, "scales differ"),
		check("same_sign_policy", left.SignPolicy == right.SignPolicy, "sign policies differ"),
		check("same_dimensions", left.DimensionalIdentity == right.DimensionalIdentity, "dimensional identities differ"),
		check("consolidated_dimensions", left.DimensionalIdentity == "consolidated", "comparison is not based on consolidated dimensionless observations"),
		check("same_period_type", left.PeriodType == right.PeriodType, "instant and duration semantics differ"),
		check("same_definition", left.DefinitionID == right.DefinitionID, "metric definitions differ"),
		check("same_accounting_perimeter", left.AccountingPerimeter == right.AccountingPerimeter, "accounting perimeters differ"),
		check("reviewed_accounting_perimeter", reviewedAccountingPerimeter(left.AccountingPerimeter) &&
			reviewedAccountingPerimeter(right.AccountingPerimeter), "accounting perimeter was not independently constrained"),
		check("same_restatement_state", left.RestatementState == right.RestatementState, "restatement states differ"),
		check("active_restatement_chain", activeRestatementState(left.RestatementState) &&
			activeRestatementState(right.RestatementState), "amendment or restatement chain is not active"),
		check("active_supersession", left.SupersessionState == "active" && right.SupersessionState == "active", "one source observation is superseded"),
	}
	caveats := []string{}
	if policy.RequireExactPeriod {
		invariants = append(invariants,
			check("same_fiscal_end", left.FiscalEnd.Equal(right.FiscalEnd), "fiscal period ends differ"),
			check("same_fiscal_start", sameOptionalTime(left.FiscalStart, right.FiscalStart), "fiscal period starts differ"),
		)
	} else if policy.AllowAnnualPeriodCaveat {
		annualPeriods := annualDuration(left) && annualDuration(right)
		endDelta := absoluteDuration(left.FiscalEnd.Sub(right.FiscalEnd))
		invariants = append(invariants,
			check("annual_duration_periods", annualPeriods, "one or both fiscal periods are not annual durations"),
			check("bounded_fiscal_end_delta", endDelta <= time.Duration(policy.MaxFiscalEndDeltaDays)*24*time.Hour, "fiscal period ends are too far apart"),
		)
		if annualPeriods && (!left.FiscalEnd.Equal(right.FiscalEnd) || !sameOptionalTime(left.FiscalStart, right.FiscalStart)) {
			caveats = append(caveats, "different_fiscal_periods")
		}
	}
	if policy.RequireExactMarketDate && (left.MarketObservationDate != nil || right.MarketObservationDate != nil) {
		invariants = append(invariants,
			check("same_market_observation_date", sameOptionalTime(left.MarketObservationDate, right.MarketObservationDate), "market observation dates differ"),
			check("security_identity_present", left.SecurityID != "" && right.SecurityID != "", "market comparison requires both security identities"),
		)
	}

	if !left.FilingDate.Equal(right.FilingDate) {
		caveats = append(caveats, "different_filing_dates")
	}
	if left.TaxonomyConcept != right.TaxonomyConcept {
		reviewedMapping := left.ExtensionMappingID != "" && left.ExtensionMappingID == right.ExtensionMappingID
		invariants = append(invariants, check("reviewed_taxonomy_mapping", reviewedMapping, "taxonomy concepts differ without one reviewed mapping"))
		if reviewedMapping {
			caveats = append(caveats, "reviewed_taxonomy_mapping_applied")
		}
	}

	reasons := failedInvariantIDs(invariants)
	disposition := contracts.ComparisonComparable
	if len(reasons) > 0 {
		disposition = contracts.ComparisonNotComparable
		caveats = nil
	} else if len(caveats) > 0 {
		disposition = contracts.ComparisonComparableWithCaveat
	}
	sort.Strings(caveats)
	sort.Strings(reasons)
	receipt := contracts.MetricComparabilityReceipt{
		SchemaVersion: contracts.ComparabilityReceiptSchemaV1,
		ReceiptID:     "comparability-" + request.RequestSHA256[:24],
		RequestID:     request.RequestID, RunID: request.RunID, LaneID: request.LaneID,
		AsOf: request.AsOf, Operands: append([]contracts.MetricComparisonOperand(nil), request.Operands...),
		Disposition: disposition, Invariants: invariants, RequiredCaveatIDs: caveats,
		ReasonCodes: reasons, ReviewerPolicyVersion: policy.Version,
		RequestSHA256: request.RequestSHA256, GeneratedAt: generatedAt,
	}
	return contracts.PopulateMetricComparabilityReceiptHash(receipt)
}

func check(id string, passed bool, detail string) contracts.ComparabilityInvariant {
	result := contracts.ComparabilityInvariant{InvariantID: id, Passed: passed}
	if !passed {
		result.Detail = detail
	}
	return result
}

func failedInvariantIDs(invariants []contracts.ComparabilityInvariant) []string {
	result := make([]string, 0)
	for _, invariant := range invariants {
		if !invariant.Passed {
			result = append(result, invariant.InvariantID)
		}
	}
	return result
}

func sameOptionalTime(left, right *time.Time) bool {
	if left == nil || right == nil {
		return left == nil && right == nil
	}
	return left.Equal(*right)
}

func activeRestatementState(value string) bool {
	return value == "not_restated" || value == "restated_current" || value == "active_amendment_chain"
}

func reviewedAccountingPerimeter(value string) bool {
	return value == "consolidated" || value == "consolidated_periodic_filing"
}

func annualDuration(operand contracts.MetricComparisonOperand) bool {
	if operand.PeriodType != "duration" || operand.FiscalStart == nil {
		return false
	}
	days := operand.FiscalEnd.Sub(*operand.FiscalStart).Hours() / 24
	return days >= 330 && days <= 380
}

func absoluteDuration(value time.Duration) time.Duration {
	if value < 0 {
		return -value
	}
	return value
}

func IsReleasable(disposition contracts.ComparisonDisposition) bool {
	return disposition == contracts.ComparisonComparable ||
		disposition == contracts.ComparisonComparableWithCaveat
}

func ExplainRefusal(receipt contracts.MetricComparabilityReceipt) string {
	if receipt.Disposition != contracts.ComparisonNotComparable {
		return ""
	}
	return "Comparison withheld because: " + strings.Join(receipt.ReasonCodes, ", ") + "."
}
