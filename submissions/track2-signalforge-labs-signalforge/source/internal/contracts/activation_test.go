package contracts

import (
	"encoding/json"
	"testing"
	"testing/quick"
	"time"
)

const testHash = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

func TestActivationTransitionGraphFailsClosed(t *testing.T) {
	allowed := map[[2]ActivationState]bool{
		{ActivationIdentityValidated, ActivationDataReady}:   true,
		{ActivationDataReady, ActivationMetricReady}:         true,
		{ActivationMetricReady, ActivationResearchReady}:     true,
		{ActivationResearchReady, ActivationComparisonReady}: true,
		{ActivationLimited, ActivationIdentityValidated}:     true,
	}
	states := []ActivationState{
		ActivationIdentityValidated, ActivationDataReady, ActivationMetricReady,
		ActivationResearchReady, ActivationComparisonReady, ActivationLimited, ActivationQuarantined,
	}
	property := func(left, right uint8) bool {
		from, to := states[int(left)%len(states)], states[int(right)%len(states)]
		actual := ValidActivationTransition(from, to)
		expected := from == to || to == ActivationLimited || to == ActivationQuarantined || allowed[[2]ActivationState{from, to}]
		return actual == expected
	}
	if err := quick.Check(property, &quick.Config{MaxCount: 500}); err != nil {
		t.Fatal(err)
	}
}

func TestCompanyActivationPromotionRequiresEvidenceAndRoundTrips(t *testing.T) {
	now := time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC)
	record, err := PopulateCompanyActivationHash(CompanyActivation{
		SchemaVersion: CompanyActivationSchemaV1, ActivationID: "activation-msft-data",
		UniverseID: "us-technology-20-v2", Scope: ActivationScopeCompany,
		SubjectID: "sec-cik:0000789019", CompanyIDs: []string{"sec-cik:0000789019"},
		PreviousState: ActivationIdentityValidated, State: ActivationDataReady,
		PolicyVersion: "company-activation/v1", EvidenceHashes: []string{testHash},
		EffectiveAsOf: now.Add(-time.Hour), GeneratedAt: now,
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateCompanyActivation(record); err != nil {
		t.Fatalf("valid activation rejected: %v", err)
	}
	payload, err := json.Marshal(record)
	if err != nil {
		t.Fatal(err)
	}
	var decoded CompanyActivation
	if err := json.Unmarshal(payload, &decoded); err != nil {
		t.Fatal(err)
	}
	if err := ValidateCompanyActivation(decoded); err != nil {
		t.Fatalf("round-tripped activation rejected: %v", err)
	}

	record.EvidenceHashes = nil
	record, _ = PopulateCompanyActivationHash(record)
	if err := ValidateCompanyActivation(record); err == nil {
		t.Fatal("promotion without evidence was accepted")
	}
}

func TestCompanyResearchProfileRejectsFutureAndStaleWithoutBoundary(t *testing.T) {
	now := time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC)
	activation := validActivation(t, now, "sec-cik:0001652044", ActivationMetricReady)
	profile := CompanyResearchProfile{
		SchemaVersion: CompanyResearchProfileV1, ProfileID: "profile-alphabet",
		UniverseID: "us-technology-20-v2", CompanyID: "sec-cik:0001652044",
		CIK: "0001652044", DisplayName: "Alphabet",
		Securities: []SecurityIdentity{
			{SecurityID: "sec-cik:0001652044/nasdaq:GOOGL", Ticker: "GOOGL", Exchange: "NASDAQ", ShareClass: "Class A", Primary: true},
			{SecurityID: "sec-cik:0001652044/nasdaq:GOOG", Ticker: "GOOG", Exchange: "NASDAQ", ShareClass: "Class C"},
		},
		ResearchCluster: "platforms_and_cloud", PeerGroup: "hyperscale_platforms",
		ResearchRole: "digital advertising, cloud, AI infrastructure, and platform economics",
		Activation:   activation,
		Metrics: []MetricAvailability{
			{MetricID: "revenue", State: AvailabilityCovered, EvidenceHashes: []string{testHash}, AvailableAt: timePointer(now.Add(-time.Hour))},
		},
		SourceRegistryHash: testHash, PolicyVersion: "company-profile/v1", AsOf: now,
	}
	profile, _ = PopulateCompanyResearchProfileHash(profile)
	if err := ValidateCompanyResearchProfile(profile); err != nil {
		t.Fatalf("valid profile rejected: %v", err)
	}

	profile.Metrics[0].AvailableAt = timePointer(now.Add(time.Second))
	profile, _ = PopulateCompanyResearchProfileHash(profile)
	if err := ValidateCompanyResearchProfile(profile); err == nil {
		t.Fatal("future source observation was accepted")
	}

	profile.Metrics[0] = MetricAvailability{
		MetricID: "revenue", State: AvailabilityStale, ReasonCodes: []string{"freshness_window_expired"},
	}
	profile, _ = PopulateCompanyResearchProfileHash(profile)
	if err := ValidateCompanyResearchProfile(profile); err == nil {
		t.Fatal("stale state without fresh_until was accepted")
	}
}

func TestComparabilityReceiptRejectsCrossIssuerAndFutureInformation(t *testing.T) {
	now := time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC)
	left := validOperand(now, "sec-cik:0000789019", "nasdaq:MSFT")
	right := validOperand(now, "sec-cik:0001652044", "nasdaq:GOOGL")
	request := validComparisonRequest(t, now, left, right)
	if err := ValidateMetricComparabilityRequest(request); err != nil {
		t.Fatalf("valid comparison request rejected: %v", err)
	}

	contaminated := request
	contaminated.Operands[1].CompanyID = contaminated.Operands[0].CompanyID
	contaminated, _ = PopulateMetricComparabilityRequestHash(contaminated)
	if err := ValidateMetricComparabilityRequest(contaminated); err == nil {
		t.Fatal("cross-issuer contamination was accepted")
	}

	future := request
	future.Operands[1].AvailableAt = now.Add(time.Second)
	future.Operands[1].RetrievedAt = now.Add(2 * time.Second)
	future, _ = PopulateMetricComparabilityRequestHash(future)
	if err := ValidateMetricComparabilityRequest(future); err == nil {
		t.Fatal("future comparison evidence was accepted")
	}
}

func TestComparisonBundleRequiresReceiptForEveryReleasedMetric(t *testing.T) {
	now := time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC)
	left := validOperand(now, "sec-cik:0000789019", "nasdaq:MSFT")
	right := validOperand(now, "sec-cik:0001652044", "nasdaq:GOOGL")
	request := validComparisonRequest(t, now, left, right)
	receipt, err := PopulateMetricComparabilityReceiptHash(MetricComparabilityReceipt{
		SchemaVersion: ComparabilityReceiptSchemaV1, ReceiptID: "cmp-receipt-1",
		RequestID: request.RequestID, RunID: request.RunID, LaneID: request.LaneID,
		AsOf: now, Operands: request.Operands, Disposition: ComparisonComparable,
		Invariants: []ComparabilityInvariant{
			{InvariantID: "same_metric", Passed: true},
			{InvariantID: "same_period", Passed: true},
			{InvariantID: "same_unit", Passed: true},
			{InvariantID: "same_definition", Passed: true},
		},
		ReviewerPolicyVersion: request.ReviewerPolicyVersion,
		RequestSHA256:         request.RequestSHA256, GeneratedAt: now.Add(time.Minute),
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateMetricComparabilityReceipt(receipt); err != nil {
		t.Fatalf("valid receipt rejected: %v", err)
	}
	lane := validPeerLane(t, now)
	bundle, err := PopulateComparisonBundleHash(ComparisonBundle{
		SchemaVersion: ComparisonBundleSchemaV1, BundleID: "bundle-1",
		RequestID: request.RequestID, RunID: request.RunID, PeerLane: lane,
		ActivationRefs: []string{"activation-msft", "activation-alphabet"},
		Receipts:       receiptSlice(receipt), ReleasedMetricIDs: []string{"revenue"},
		GeneratedAt: now.Add(2 * time.Minute),
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateComparisonBundle(bundle); err != nil {
		t.Fatalf("valid comparison bundle rejected: %v", err)
	}

	bundle.ReleasedMetricIDs = append(bundle.ReleasedMetricIDs, "operating_margin")
	bundle, _ = PopulateComparisonBundleHash(bundle)
	if err := ValidateComparisonBundle(bundle); err == nil {
		t.Fatal("metric without comparability receipt was released")
	}
}

func TestShareClassIdentityCannotBeReusedAcrossIssuers(t *testing.T) {
	now := time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC)
	left := validOperand(now, "sec-cik:0000789019", "nasdaq:MSFT")
	right := validOperand(now, "sec-cik:0001652044", "nasdaq:MSFT")
	request := validComparisonRequest(t, now, left, right)
	if err := ValidateMetricComparabilityRequest(request); err == nil {
		t.Fatal("mismatched share-class identity was accepted")
	}
}

func validActivation(t *testing.T, now time.Time, companyID string, state ActivationState) CompanyActivation {
	t.Helper()
	record, err := PopulateCompanyActivationHash(CompanyActivation{
		SchemaVersion: CompanyActivationSchemaV1, ActivationID: "activation-" + companyID,
		UniverseID: "us-technology-20-v2", Scope: ActivationScopeCompany,
		SubjectID: companyID, CompanyIDs: []string{companyID},
		State: state, PolicyVersion: "company-activation/v1",
		EvidenceHashes: []string{testHash}, EffectiveAsOf: now.Add(-time.Hour), GeneratedAt: now,
	})
	if err != nil {
		t.Fatal(err)
	}
	return record
}

func validOperand(now time.Time, companyID, securityID string) MetricComparisonOperand {
	start := now.AddDate(-1, 0, 0)
	return MetricComparisonOperand{
		CompanyID: companyID, SecurityID: securityID,
		SourceObservationIDs: []string{"observation-" + companyID}, FilingAccessions: []string{"0000000000-26-000001"},
		SourceHashes: []string{testHash}, AvailableAt: now.Add(-time.Hour), RetrievedAt: now,
		CanonicalMetricID: "revenue", MetricVersion: "canonical-metrics/v1",
		TaxonomyConcept: "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
		Value:           "100", Unit: "USD", Currency: "USD", Scale: 0, SignPolicy: "as_reported",
		DimensionalIdentity: "consolidated", PeriodType: "duration", FiscalStart: &start,
		FiscalEnd: now.AddDate(0, 0, -1), FilingDate: now.Add(-2 * time.Hour),
		AccountingPerimeter: "consolidated", DefinitionID: "revenue/v1",
		RestatementState: "not_rested", SupersessionState: "active",
	}
}

func validComparisonRequest(t *testing.T, now time.Time, operands ...MetricComparisonOperand) MetricComparabilityRequest {
	t.Helper()
	request, err := PopulateMetricComparabilityRequestHash(MetricComparabilityRequest{
		SchemaVersion: ComparabilityRequestSchemaV1, RequestID: "request-1", RunID: "run-1",
		LaneID: "microsoft-alphabet", AsOf: now, ReviewerPolicyVersion: "comparability/v1",
		Operands: operands,
	})
	if err != nil {
		t.Fatal(err)
	}
	return request
}

func validPeerLane(t *testing.T, now time.Time) PeerLane {
	t.Helper()
	lane, err := PopulatePeerLaneHash(PeerLane{
		SchemaVersion: PeerLaneSchemaV1, LaneID: "microsoft-alphabet",
		UniverseID:         "us-technology-20-v2",
		CompanyIDs:         []string{"sec-cik:0000789019", "sec-cik:0001652044"},
		SecurityIDs:        []string{"nasdaq:MSFT", "nasdaq:GOOGL"},
		ComparisonType:     "guarded_hyperscale_platform_peer",
		DecisionQuestion:   "Compare cloud and AI infrastructure economics.",
		AllowedQuestionIDs: []string{"cloud_ai_economics"},
		AllowedMetricIDs:   []string{"revenue", "operating_margin"},
		PolicyVersion:      "peer-lanes/v1", EvidenceHashes: []string{testHash},
		Enabled: true, AsOf: now,
	})
	if err != nil {
		t.Fatal(err)
	}
	return lane
}

func receiptSlice(receipt MetricComparabilityReceipt) []MetricComparabilityReceipt {
	return []MetricComparabilityReceipt{receipt}
}

func timePointer(value time.Time) *time.Time {
	return &value
}
