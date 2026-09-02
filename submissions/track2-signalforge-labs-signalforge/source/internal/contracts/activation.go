package contracts

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"
)

const (
	CompanyActivationSchemaV1    = "signalforge/company-activation/v1"
	CompanyResearchProfileV1     = "signalforge/company-research-profile/v1"
	PeerLaneSchemaV1             = "signalforge/peer-lane/v1"
	ComparabilityRequestSchemaV1 = "signalforge/metric-comparability-request/v1"
	ComparabilityReceiptSchemaV1 = "signalforge/metric-comparability-receipt/v1"
	ComparisonBundleSchemaV1     = "signalforge/comparison-bundle/v1"
	TypedAbstentionSchemaV1      = "signalforge/typed-abstention/v1"
)

type ActivationState string

const (
	ActivationIdentityValidated ActivationState = "identity_validated"
	ActivationDataReady         ActivationState = "data_ready"
	ActivationMetricReady       ActivationState = "metric_ready"
	ActivationResearchReady     ActivationState = "research_ready"
	ActivationComparisonReady   ActivationState = "comparison_ready"
	ActivationLimited           ActivationState = "limited"
	ActivationQuarantined       ActivationState = "quarantined"
)

type ActivationScope string

const (
	ActivationScopeCompany  ActivationScope = "company"
	ActivationScopePeerLane ActivationScope = "peer_lane"
)

type AvailabilityState string

const (
	AvailabilityCovered       AvailabilityState = "covered"
	AvailabilityPartial       AvailabilityState = "partial"
	AvailabilityUnknown       AvailabilityState = "unknown"
	AvailabilityNotApplicable AvailabilityState = "not_applicable"
	AvailabilityMissing       AvailabilityState = "missing"
	AvailabilityStale         AvailabilityState = "stale"
	AvailabilityNotComparable AvailabilityState = "not_comparable"
	AvailabilityQuarantined   AvailabilityState = "quarantined"
)

type SecurityIdentity struct {
	SecurityID string `json:"security_id"`
	Ticker     string `json:"ticker"`
	Exchange   string `json:"exchange"`
	ShareClass string `json:"share_class,omitempty"`
	Primary    bool   `json:"primary"`
}

type CompanyActivation struct {
	SchemaVersion  string          `json:"schema_version"`
	ActivationID   string          `json:"activation_id"`
	UniverseID     string          `json:"universe_id"`
	Scope          ActivationScope `json:"scope"`
	SubjectID      string          `json:"subject_id"`
	CompanyIDs     []string        `json:"company_ids"`
	PreviousState  ActivationState `json:"previous_state,omitempty"`
	State          ActivationState `json:"state"`
	PolicyVersion  string          `json:"policy_version"`
	EvidenceHashes []string        `json:"evidence_hashes"`
	ReasonCodes    []string        `json:"reason_codes,omitempty"`
	EffectiveAsOf  time.Time       `json:"effective_as_of"`
	GeneratedAt    time.Time       `json:"generated_at"`
	RecordSHA256   string          `json:"record_sha256"`
}

type MetricAvailability struct {
	MetricID       string            `json:"metric_id"`
	State          AvailabilityState `json:"state"`
	ReasonCodes    []string          `json:"reason_codes,omitempty"`
	EvidenceHashes []string          `json:"evidence_hashes,omitempty"`
	AvailableAt    *time.Time        `json:"available_at,omitempty"`
	FreshUntil     *time.Time        `json:"fresh_until,omitempty"`
}

type CompanyResearchProfile struct {
	SchemaVersion      string               `json:"schema_version"`
	ProfileID          string               `json:"profile_id"`
	UniverseID         string               `json:"universe_id"`
	CompanyID          string               `json:"company_id"`
	CIK                string               `json:"cik"`
	DisplayName        string               `json:"display_name"`
	Securities         []SecurityIdentity   `json:"securities"`
	ResearchCluster    string               `json:"research_cluster"`
	PeerGroup          string               `json:"peer_group"`
	ResearchRole       string               `json:"research_role"`
	Activation         CompanyActivation    `json:"activation"`
	Metrics            []MetricAvailability `json:"metrics"`
	SourceRegistryHash string               `json:"source_registry_sha256"`
	PolicyVersion      string               `json:"policy_version"`
	AsOf               time.Time            `json:"as_of"`
	ProfileSHA256      string               `json:"profile_sha256"`
}

type PeerLane struct {
	SchemaVersion      string    `json:"schema_version"`
	LaneID             string    `json:"lane_id"`
	UniverseID         string    `json:"universe_id"`
	CompanyIDs         []string  `json:"company_ids"`
	SecurityIDs        []string  `json:"security_ids,omitempty"`
	ComparisonType     string    `json:"comparison_type"`
	DecisionQuestion   string    `json:"decision_question"`
	AllowedQuestionIDs []string  `json:"allowed_question_ids"`
	AllowedMetricIDs   []string  `json:"allowed_metric_ids"`
	PolicyVersion      string    `json:"policy_version"`
	EvidenceHashes     []string  `json:"evidence_hashes"`
	Enabled            bool      `json:"enabled"`
	AsOf               time.Time `json:"as_of"`
	LaneSHA256         string    `json:"lane_sha256"`
}

type ComparisonDisposition string

const (
	ComparisonComparable           ComparisonDisposition = "comparable"
	ComparisonComparableWithCaveat ComparisonDisposition = "comparable_with_caveat"
	ComparisonNotComparable        ComparisonDisposition = "not_comparable"
)

type MetricComparisonOperand struct {
	CompanyID             string     `json:"company_id"`
	SecurityID            string     `json:"security_id,omitempty"`
	SourceObservationIDs  []string   `json:"source_observation_ids"`
	FilingAccessions      []string   `json:"filing_accessions,omitempty"`
	SourceHashes          []string   `json:"source_hashes"`
	AvailableAt           time.Time  `json:"available_at"`
	RetrievedAt           time.Time  `json:"retrieved_at"`
	CanonicalMetricID     string     `json:"canonical_metric_id"`
	MetricVersion         string     `json:"metric_version"`
	TaxonomyConcept       string     `json:"taxonomy_concept"`
	ExtensionMappingID    string     `json:"extension_mapping_id,omitempty"`
	Value                 string     `json:"value"`
	Numerator             string     `json:"numerator,omitempty"`
	Denominator           string     `json:"denominator,omitempty"`
	Unit                  string     `json:"unit"`
	Currency              string     `json:"currency,omitempty"`
	Scale                 int32      `json:"scale"`
	SignPolicy            string     `json:"sign_policy"`
	DimensionalIdentity   string     `json:"dimensional_identity"`
	PeriodType            string     `json:"period_type"`
	FiscalStart           *time.Time `json:"fiscal_start,omitempty"`
	FiscalEnd             time.Time  `json:"fiscal_end"`
	FilingDate            time.Time  `json:"filing_date"`
	MarketObservationDate *time.Time `json:"market_observation_date,omitempty"`
	AccountingPerimeter   string     `json:"accounting_perimeter"`
	DefinitionID          string     `json:"definition_id"`
	RestatementState      string     `json:"restatement_state"`
	SupersessionState     string     `json:"supersession_state"`
}

type MetricComparabilityRequest struct {
	SchemaVersion         string                    `json:"schema_version"`
	RequestID             string                    `json:"request_id"`
	RunID                 string                    `json:"run_id"`
	LaneID                string                    `json:"lane_id"`
	AsOf                  time.Time                 `json:"as_of"`
	ReviewerPolicyVersion string                    `json:"reviewer_policy_version"`
	Operands              []MetricComparisonOperand `json:"operands"`
	RequestSHA256         string                    `json:"request_sha256"`
}

type ComparabilityInvariant struct {
	InvariantID string `json:"invariant_id"`
	Passed      bool   `json:"passed"`
	Detail      string `json:"detail,omitempty"`
}

type MetricComparabilityReceipt struct {
	SchemaVersion         string                    `json:"schema_version"`
	ReceiptID             string                    `json:"receipt_id"`
	RequestID             string                    `json:"request_id"`
	RunID                 string                    `json:"run_id"`
	LaneID                string                    `json:"lane_id"`
	AsOf                  time.Time                 `json:"as_of"`
	Operands              []MetricComparisonOperand `json:"operands"`
	Disposition           ComparisonDisposition     `json:"disposition"`
	Invariants            []ComparabilityInvariant  `json:"invariants"`
	RequiredCaveatIDs     []string                  `json:"required_caveat_ids,omitempty"`
	ReasonCodes           []string                  `json:"reason_codes,omitempty"`
	ReviewerPolicyVersion string                    `json:"reviewer_policy_version"`
	RequestSHA256         string                    `json:"request_sha256"`
	GeneratedAt           time.Time                 `json:"generated_at"`
	ReceiptSHA256         string                    `json:"receipt_sha256"`
}

type TypedAbstention struct {
	SchemaVersion string    `json:"schema_version"`
	AbstentionID  string    `json:"abstention_id"`
	RequestID     string    `json:"request_id"`
	RunID         string    `json:"run_id"`
	Code          string    `json:"code"`
	Message       string    `json:"message"`
	CompanyIDs    []string  `json:"company_ids,omitempty"`
	MetricIDs     []string  `json:"metric_ids,omitempty"`
	EvidenceRefs  []string  `json:"evidence_refs,omitempty"`
	GeneratedAt   time.Time `json:"generated_at"`
}

type ComparisonBundle struct {
	SchemaVersion     string                       `json:"schema_version"`
	BundleID          string                       `json:"bundle_id"`
	RequestID         string                       `json:"request_id"`
	RunID             string                       `json:"run_id"`
	PeerLane          PeerLane                     `json:"peer_lane"`
	ActivationRefs    []string                     `json:"activation_refs"`
	Receipts          []MetricComparabilityReceipt `json:"receipts"`
	Abstentions       []TypedAbstention            `json:"abstentions,omitempty"`
	ReleasedMetricIDs []string                     `json:"released_metric_ids"`
	GeneratedAt       time.Time                    `json:"generated_at"`
	BundleSHA256      string                       `json:"bundle_sha256"`
}

func ValidateCompanyActivation(record CompanyActivation) error {
	if record.SchemaVersion != CompanyActivationSchemaV1 || record.ActivationID == "" ||
		record.UniverseID == "" || record.SubjectID == "" || record.PolicyVersion == "" {
		return errors.New("company activation envelope is incomplete")
	}
	if record.EffectiveAsOf.IsZero() || record.GeneratedAt.IsZero() || record.GeneratedAt.Before(record.EffectiveAsOf) {
		return errors.New("company activation timestamps are invalid")
	}
	if !validActivationState(record.State) || !validActivationScope(record.Scope) {
		return errors.New("company activation state or scope is invalid")
	}
	if record.Scope == ActivationScopeCompany && len(record.CompanyIDs) != 1 {
		return errors.New("company activation requires exactly one company")
	}
	if record.Scope == ActivationScopePeerLane && len(record.CompanyIDs) != 2 {
		return errors.New("peer-lane activation requires exactly two companies")
	}
	if !allUniqueNonEmpty(record.CompanyIDs) {
		return errors.New("company activation contains duplicate or empty company IDs")
	}
	if record.PreviousState != "" && !ValidActivationTransition(record.PreviousState, record.State) {
		return fmt.Errorf("illegal activation transition %q -> %q", record.PreviousState, record.State)
	}
	if isPromotion(record.PreviousState, record.State) && !validHashes(record.EvidenceHashes) {
		return errors.New("activation promotion requires valid evidence hashes")
	}
	if (record.State == ActivationLimited || record.State == ActivationQuarantined) && len(record.ReasonCodes) == 0 {
		return errors.New("limited or quarantined activation requires reason codes")
	}
	return verifyStructHash(record, record.RecordSHA256, func(value *CompanyActivation) { value.RecordSHA256 = "" })
}

func ValidActivationTransition(from, to ActivationState) bool {
	if from == to {
		return true
	}
	if to == ActivationLimited || to == ActivationQuarantined {
		return validActivationState(from)
	}
	allowed := map[ActivationState]ActivationState{
		ActivationIdentityValidated: ActivationDataReady,
		ActivationDataReady:         ActivationMetricReady,
		ActivationMetricReady:       ActivationResearchReady,
		ActivationResearchReady:     ActivationComparisonReady,
		ActivationLimited:           ActivationIdentityValidated,
	}
	return allowed[from] == to
}

func ValidateCompanyResearchProfile(profile CompanyResearchProfile) error {
	if profile.SchemaVersion != CompanyResearchProfileV1 || profile.ProfileID == "" ||
		profile.CompanyID == "" || profile.CIK == "" || profile.DisplayName == "" ||
		profile.ResearchCluster == "" || profile.PeerGroup == "" || profile.ResearchRole == "" ||
		profile.PolicyVersion == "" || profile.AsOf.IsZero() || len(profile.Securities) == 0 {
		return errors.New("company research profile is incomplete")
	}
	if profile.Activation.Scope != ActivationScopeCompany || len(profile.Activation.CompanyIDs) != 1 ||
		profile.Activation.CompanyIDs[0] != profile.CompanyID || profile.Activation.UniverseID != profile.UniverseID {
		return errors.New("company research profile activation scope does not match company")
	}
	if err := ValidateCompanyActivation(profile.Activation); err != nil {
		return fmt.Errorf("activation: %w", err)
	}
	if !validHash(profile.SourceRegistryHash) {
		return errors.New("company research profile requires a source registry hash")
	}
	primary := 0
	securityIDs := map[string]bool{}
	for _, security := range profile.Securities {
		if security.SecurityID == "" || security.Ticker == "" || security.Exchange == "" || securityIDs[security.SecurityID] {
			return errors.New("company research profile contains invalid security identity")
		}
		securityIDs[security.SecurityID] = true
		if security.Primary {
			primary++
		}
	}
	if primary != 1 {
		return errors.New("company research profile requires exactly one primary security")
	}
	metrics := map[string]bool{}
	for _, metric := range profile.Metrics {
		if metric.MetricID == "" || metrics[metric.MetricID] || !validAvailabilityState(metric.State) {
			return errors.New("company research profile contains invalid metric availability")
		}
		metrics[metric.MetricID] = true
		if (metric.State == AvailabilityCovered || metric.State == AvailabilityPartial) &&
			!validHashes(metric.EvidenceHashes) {
			return errors.New("covered or partial metric requires evidence hashes")
		}
		if metric.AvailableAt != nil && metric.AvailableAt.After(profile.AsOf) {
			return errors.New("metric availability leaks information after profile as_of")
		}
		if metric.State == AvailabilityStale && metric.FreshUntil == nil {
			return errors.New("stale metric requires fresh_until")
		}
		if metric.State != AvailabilityCovered && len(metric.ReasonCodes) == 0 {
			return errors.New("non-covered metric state requires reason codes")
		}
	}
	return verifyStructHash(profile, profile.ProfileSHA256, func(value *CompanyResearchProfile) { value.ProfileSHA256 = "" })
}

func ValidatePeerLane(lane PeerLane) error {
	if lane.SchemaVersion != PeerLaneSchemaV1 || lane.LaneID == "" || lane.UniverseID == "" ||
		lane.ComparisonType == "" || lane.DecisionQuestion == "" || lane.PolicyVersion == "" || lane.AsOf.IsZero() {
		return errors.New("peer lane is incomplete")
	}
	if len(lane.CompanyIDs) != 2 || !allUniqueNonEmpty(lane.CompanyIDs) ||
		len(lane.AllowedQuestionIDs) == 0 || len(lane.AllowedMetricIDs) == 0 || !validHashes(lane.EvidenceHashes) {
		return errors.New("peer lane requires two companies, bounded questions, metrics, and evidence")
	}
	if len(lane.SecurityIDs) > 0 && (len(lane.SecurityIDs) != 2 || !allUniqueNonEmpty(lane.SecurityIDs)) {
		return errors.New("peer lane security scope must contain two unique securities")
	}
	return verifyStructHash(lane, lane.LaneSHA256, func(value *PeerLane) { value.LaneSHA256 = "" })
}

func ValidateMetricComparabilityRequest(request MetricComparabilityRequest) error {
	if request.SchemaVersion != ComparabilityRequestSchemaV1 || request.RequestID == "" ||
		request.RunID == "" || request.LaneID == "" || request.AsOf.IsZero() ||
		request.ReviewerPolicyVersion == "" || len(request.Operands) != 2 {
		return errors.New("metric comparability request is incomplete")
	}
	if err := validateComparisonOperands(request.Operands, request.AsOf); err != nil {
		return err
	}
	return verifyStructHash(request, request.RequestSHA256, func(value *MetricComparabilityRequest) { value.RequestSHA256 = "" })
}

func ValidateMetricComparabilityReceipt(receipt MetricComparabilityReceipt) error {
	if receipt.SchemaVersion != ComparabilityReceiptSchemaV1 || receipt.ReceiptID == "" ||
		receipt.RequestID == "" || receipt.RunID == "" || receipt.LaneID == "" ||
		receipt.AsOf.IsZero() || receipt.GeneratedAt.IsZero() || receipt.GeneratedAt.Before(receipt.AsOf) ||
		receipt.ReviewerPolicyVersion == "" || len(receipt.Invariants) == 0 || !validHash(receipt.RequestSHA256) {
		return errors.New("metric comparability receipt is incomplete")
	}
	if err := validateComparisonOperands(receipt.Operands, receipt.AsOf); err != nil {
		return err
	}
	failed := 0
	for _, invariant := range receipt.Invariants {
		if invariant.InvariantID == "" {
			return errors.New("comparability invariant requires an ID")
		}
		if !invariant.Passed {
			failed++
		}
	}
	switch receipt.Disposition {
	case ComparisonComparable:
		if failed != 0 || len(receipt.RequiredCaveatIDs) != 0 || len(receipt.ReasonCodes) != 0 {
			return errors.New("comparable receipt cannot contain failed invariants or caveats")
		}
	case ComparisonComparableWithCaveat:
		if len(receipt.RequiredCaveatIDs) == 0 {
			return errors.New("qualified comparability requires visible caveats")
		}
	case ComparisonNotComparable:
		if failed == 0 || len(receipt.ReasonCodes) == 0 {
			return errors.New("not-comparable receipt requires a failed invariant and reason code")
		}
	default:
		return errors.New("unsupported comparison disposition")
	}
	return verifyStructHash(receipt, receipt.ReceiptSHA256, func(value *MetricComparabilityReceipt) { value.ReceiptSHA256 = "" })
}

func ValidateComparisonBundle(bundle ComparisonBundle) error {
	if bundle.SchemaVersion != ComparisonBundleSchemaV1 || bundle.BundleID == "" ||
		bundle.RequestID == "" || bundle.RunID == "" || bundle.GeneratedAt.IsZero() ||
		len(bundle.ActivationRefs) != 2 || !allUniqueNonEmpty(bundle.ActivationRefs) {
		return errors.New("comparison bundle is incomplete")
	}
	if err := ValidatePeerLane(bundle.PeerLane); err != nil {
		return fmt.Errorf("peer_lane: %w", err)
	}
	releasable := map[string]bool{}
	for index, receipt := range bundle.Receipts {
		if err := ValidateMetricComparabilityReceipt(receipt); err != nil {
			return fmt.Errorf("receipts[%d]: %w", index, err)
		}
		if receipt.RequestID != bundle.RequestID || receipt.RunID != bundle.RunID || receipt.LaneID != bundle.PeerLane.LaneID {
			return errors.New("comparison bundle contains cross-request receipt contamination")
		}
		if receipt.Disposition != ComparisonNotComparable {
			releasable[receipt.Operands[0].CanonicalMetricID] = true
		}
	}
	for _, metricID := range bundle.ReleasedMetricIDs {
		if !releasable[metricID] {
			return fmt.Errorf("released metric %q lacks an approved comparability receipt", metricID)
		}
	}
	for index, abstention := range bundle.Abstentions {
		if err := ValidateTypedAbstention(abstention); err != nil {
			return fmt.Errorf("abstentions[%d]: %w", index, err)
		}
	}
	return verifyStructHash(bundle, bundle.BundleSHA256, func(value *ComparisonBundle) { value.BundleSHA256 = "" })
}

func ValidateTypedAbstention(abstention TypedAbstention) error {
	if abstention.SchemaVersion != TypedAbstentionSchemaV1 || abstention.AbstentionID == "" ||
		abstention.RequestID == "" || abstention.RunID == "" || abstention.Code == "" ||
		strings.TrimSpace(abstention.Message) == "" || abstention.GeneratedAt.IsZero() {
		return errors.New("typed abstention is incomplete")
	}
	return nil
}

func PopulateCompanyActivationHash(record CompanyActivation) (CompanyActivation, error) {
	record.RecordSHA256 = ""
	digest, err := structHash(record)
	record.RecordSHA256 = digest
	return record, err
}

func PopulateCompanyResearchProfileHash(profile CompanyResearchProfile) (CompanyResearchProfile, error) {
	profile.ProfileSHA256 = ""
	digest, err := structHash(profile)
	profile.ProfileSHA256 = digest
	return profile, err
}

func PopulatePeerLaneHash(lane PeerLane) (PeerLane, error) {
	lane.LaneSHA256 = ""
	digest, err := structHash(lane)
	lane.LaneSHA256 = digest
	return lane, err
}

func PopulateMetricComparabilityRequestHash(request MetricComparabilityRequest) (MetricComparabilityRequest, error) {
	request.RequestSHA256 = ""
	digest, err := structHash(request)
	request.RequestSHA256 = digest
	return request, err
}

func PopulateMetricComparabilityReceiptHash(receipt MetricComparabilityReceipt) (MetricComparabilityReceipt, error) {
	receipt.ReceiptSHA256 = ""
	digest, err := structHash(receipt)
	receipt.ReceiptSHA256 = digest
	return receipt, err
}

func PopulateComparisonBundleHash(bundle ComparisonBundle) (ComparisonBundle, error) {
	bundle.BundleSHA256 = ""
	digest, err := structHash(bundle)
	bundle.BundleSHA256 = digest
	return bundle, err
}

func validateComparisonOperands(operands []MetricComparisonOperand, asOf time.Time) error {
	companies := map[string]bool{}
	metricID := ""
	for index, operand := range operands {
		if operand.CompanyID == "" || companies[operand.CompanyID] || operand.CanonicalMetricID == "" ||
			operand.MetricVersion == "" || operand.TaxonomyConcept == "" || operand.Value == "" ||
			operand.Unit == "" || operand.SignPolicy == "" || operand.DimensionalIdentity == "" ||
			operand.PeriodType == "" || operand.FiscalEnd.IsZero() || operand.FilingDate.IsZero() ||
			operand.AccountingPerimeter == "" || operand.DefinitionID == "" ||
			operand.RestatementState == "" || operand.SupersessionState == "" ||
			len(operand.SourceObservationIDs) == 0 || !validHashes(operand.SourceHashes) {
			return fmt.Errorf("operands[%d] is incomplete or duplicates an issuer", index)
		}
		companies[operand.CompanyID] = true
		if metricID == "" {
			metricID = operand.CanonicalMetricID
		} else if operand.CanonicalMetricID != metricID {
			return errors.New("comparison operands must use one canonical metric")
		}
		if operand.AvailableAt.IsZero() || operand.RetrievedAt.IsZero() ||
			operand.RetrievedAt.Before(operand.AvailableAt) || operand.AvailableAt.After(asOf) ||
			operand.FilingDate.After(asOf) || operand.FiscalEnd.After(asOf) {
			return fmt.Errorf("operands[%d] violates point-in-time availability", index)
		}
		if operand.PeriodType == "duration" && (operand.FiscalStart == nil || !operand.FiscalEnd.After(*operand.FiscalStart)) {
			return fmt.Errorf("operands[%d] duration period is invalid", index)
		}
		if operand.PeriodType == "instant" && operand.FiscalStart != nil {
			return fmt.Errorf("operands[%d] instant metric cannot have fiscal_start", index)
		}
	}
	if len(operands) == 2 && operands[0].SecurityID != "" && operands[0].SecurityID == operands[1].SecurityID {
		return errors.New("comparison operands reuse a security across issuers")
	}
	return nil
}

func validActivationState(state ActivationState) bool {
	switch state {
	case ActivationIdentityValidated, ActivationDataReady, ActivationMetricReady,
		ActivationResearchReady, ActivationComparisonReady, ActivationLimited, ActivationQuarantined:
		return true
	default:
		return false
	}
}

func validActivationScope(scope ActivationScope) bool {
	return scope == ActivationScopeCompany || scope == ActivationScopePeerLane
}

func validAvailabilityState(state AvailabilityState) bool {
	switch state {
	case AvailabilityCovered, AvailabilityPartial, AvailabilityUnknown, AvailabilityNotApplicable,
		AvailabilityMissing, AvailabilityStale, AvailabilityNotComparable, AvailabilityQuarantined:
		return true
	default:
		return false
	}
}

func isPromotion(from, to ActivationState) bool {
	if from == "" {
		return to != ActivationLimited && to != ActivationQuarantined
	}
	return from != to && to != ActivationLimited && to != ActivationQuarantined
}

func validHashes(values []string) bool {
	if len(values) == 0 {
		return false
	}
	for _, value := range values {
		if !validHash(value) {
			return false
		}
	}
	return true
}

func validHash(value string) bool {
	if len(value) != sha256.Size*2 || strings.ToLower(value) != value {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

func allUniqueNonEmpty(values []string) bool {
	seen := map[string]bool{}
	for _, value := range values {
		if strings.TrimSpace(value) == "" || seen[value] {
			return false
		}
		seen[value] = true
	}
	return true
}

func structHash(value any) (string, error) {
	payload, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(payload)
	return hex.EncodeToString(digest[:]), nil
}

func verifyStructHash[T any](value T, expected string, clear func(*T)) error {
	if !validHash(expected) {
		return errors.New("record requires a lowercase SHA-256 content hash")
	}
	clear(&value)
	actual, err := structHash(value)
	if err != nil {
		return err
	}
	if actual != expected {
		return errors.New("record content hash does not match payload")
	}
	return nil
}

func sortedUnique(values []string) []string {
	result := append([]string(nil), values...)
	sort.Strings(result)
	if len(result) == 0 {
		return result
	}
	write := 1
	for _, value := range result[1:] {
		if value != result[write-1] {
			result[write] = value
			write++
		}
	}
	return result[:write]
}
