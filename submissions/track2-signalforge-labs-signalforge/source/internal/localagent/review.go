package localagent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
	"github.com/rvbernucci/signalforge/internal/roles"
)

type critiqueBody struct {
	Decision       contracts.CritiqueDecision `json:"decision"`
	ApprovedClaims []string                   `json:"approved_claims,omitempty"`
	RejectedClaims []string                   `json:"rejected_claims,omitempty"`
	Issues         []contracts.CritiqueIssue  `json:"issues,omitempty"`
}

type reviewEvidenceView struct {
	EvidenceID      string    `json:"evidence_id"`
	SourceType      string    `json:"source_type"`
	DocumentSection string    `json:"document_section,omitempty"`
	State           string    `json:"state,omitempty"`
	Statement       string    `json:"statement,omitempty"`
	Warnings        []string  `json:"warnings,omitempty"`
	AsOf            time.Time `json:"as_of"`
	ContentSHA      string    `json:"content_sha256"`
}

type reviewPacketView struct {
	PacketID            string                 `json:"packet_id"`
	SpecialistRole      string                 `json:"specialist_role"`
	Findings            []contracts.Finding    `json:"findings"`
	Counterevidence     []contracts.Finding    `json:"counterevidence,omitempty"`
	Assumptions         []string               `json:"assumptions,omitempty"`
	MissingEvidence     []string               `json:"missing_evidence,omitempty"`
	Conflicts           []string               `json:"conflicts,omitempty"`
	Uncertainties       []string               `json:"uncertainties,omitempty"`
	Evidence            []reviewEvidenceView   `json:"evidence,omitempty"`
	ValidatedOperations []string               `json:"validated_operations,omitempty"`
	CalculationReceipts []synthesisReceiptView `json:"calculation_receipts,omitempty"`
	NumericalContext    *numericalContextView  `json:"numerical_context,omitempty"`
}

type reviewPriorView struct {
	ReportID string                     `json:"report_id"`
	Decision contracts.CritiqueDecision `json:"decision"`
	Issues   []reviewPriorIssueView     `json:"issues,omitempty"`
}

type reviewPriorIssueView struct {
	IssueID     string `json:"issue_id"`
	Severity    string `json:"severity"`
	Description string `json:"description"`
	RepairHint  string `json:"repair_hint,omitempty"`
}

type reviewPromptInput struct {
	Question     string             `json:"question"`
	AsOf         time.Time          `json:"as_of"`
	Assumptions  []string           `json:"request_assumptions,omitempty"`
	ReviewerRole string             `json:"reviewer_role"`
	RepairPass   int                `json:"repair_pass"`
	Packets      []reviewPacketView `json:"packets"`
	Prior        []reviewPriorView  `json:"prior_critiques,omitempty"`
}

func (adapters *Adapters) Review(ctx context.Context, input orchestrator.ReviewInput) (contracts.CritiqueReport, error) {
	prompt, ok := adapters.Prompts.Get(input.Step.RoleID)
	if !ok {
		return contracts.CritiqueReport{}, fmt.Errorf("no prompt for role %q", input.Step.RoleID)
	}
	role, ok := roles.DefaultRegistry().Get(input.Step.RoleID)
	if !ok || role.Class != roles.ClassReview {
		return contracts.CritiqueReport{}, fmt.Errorf("role %q is not a reviewer", input.Step.RoleID)
	}
	material, err := adapters.reviewMaterialForPrompt(ctx, input)
	if err != nil {
		return contracts.CritiqueReport{}, err
	}
	payload, err := json.Marshal(material)
	if err != nil {
		return contracts.CritiqueReport{}, err
	}
	completion, err := adapters.complete(ctx, prompt, string(payload))
	if err != nil {
		return contracts.CritiqueReport{}, err
	}
	var body critiqueBody
	if decodeErr := decodeJSONObject(completion.Answer, &body); decodeErr != nil {
		if !isIncompleteJSON(decodeErr) {
			return contracts.CritiqueReport{}, fmt.Errorf("decode critique body: %w", decodeErr)
		}
		retryPrompt := prompt
		retryPrompt.MaxTokens *= 2
		if retryPrompt.MaxTokens > 3200 {
			retryPrompt.MaxTokens = 3200
		}
		completion, err = adapters.complete(ctx, retryPrompt, string(payload))
		if err != nil {
			return contracts.CritiqueReport{}, err
		}
		body = critiqueBody{}
		if err := decodeJSONObject(completion.Answer, &body); err != nil {
			return contracts.CritiqueReport{}, fmt.Errorf("decode critique body after bounded truncation retry: %w", err)
		}
	}
	normalizeCritiqueForInput(&body, input.Packets)
	if missing := unclassifiedCritiqueClaims(body, input.Packets); len(missing) > 0 {
		retryPrompt := prompt
		retryPrompt.System += " The previous review violated the completeness contract by omitting these claim IDs: " + strings.Join(missing, ", ") + ". Classify every supplied claim ID exactly once as approved or rejected. If rejecting a claim, include a claim-specific issue. Never treat omission as a decision."
		if hasUnclassifiedCounterevidence(missing, input.Packets) && requestsCounterevidence(input.Request.RequestedOutputs) {
			retryPrompt.System += " Do not silently omit every counterevidence claim. Approve a supported counterevidence claim or reject it explicitly with a material reason."
		}
		completion, err = adapters.complete(ctx, retryPrompt, string(payload))
		if err != nil {
			return contracts.CritiqueReport{}, err
		}
		body = critiqueBody{}
		if err := decodeJSONObject(completion.Answer, &body); err != nil {
			return contracts.CritiqueReport{}, fmt.Errorf("decode critique body after bounded counterevidence retry: %w", err)
		}
		normalizeCritiqueForInput(&body, input.Packets)
		if stillMissing := unclassifiedCritiqueClaims(body, input.Packets); len(stillMissing) > 0 {
			return contracts.CritiqueReport{}, fmt.Errorf("review omitted claim IDs after bounded completeness retry: %s", strings.Join(stillMissing, ", "))
		}
	}
	report := contracts.CritiqueReport{
		SchemaVersion: contracts.SchemaVersionV1,
		ReportID:      fmt.Sprintf("critique-%s-p%d", input.Step.StepID, input.RepairPass),
		RunID:         input.Request.RunID, ReviewerRole: input.Step.RoleID,
		Decision: body.Decision, ApprovedClaims: body.ApprovedClaims,
		RejectedClaims: body.RejectedClaims, Issues: body.Issues,
		RepairPass: input.RepairPass, CreatedAt: input.Request.AsOf,
	}
	if err := authorizeCritiqueClaims(report, input.Packets); err != nil {
		return contracts.CritiqueReport{}, err
	}
	if err := contracts.ValidateCritiqueReport(report); err != nil {
		return contracts.CritiqueReport{}, err
	}
	return report, nil
}

func normalizeCritiqueForInput(body *critiqueBody, packets []contracts.ContextPacket) {
	normalizeCritiqueBody(body)
	dropUnauthorizedCritiqueReferences(body, packets)
	protectDeterministicFindings(body, packets)
	protectAuthorizedScenarioHypotheses(body, packets)
	completeApprovedComplement(body, packets)
	normalizeCritiqueAgainstPackets(body, packets)
}

// Rejections and their issues are the critic's material semantic output. Go derives the approved
// complement, avoiding a lossy transcription of every long claim ID. An approval must contain at
// least one authorized ID, while a non-approval must contain an authorized rejection; therefore an
// invented or empty model decision cannot be expanded into authority.
func completeApprovedComplement(body *critiqueBody, packets []contracts.ContextPacket) {
	switch body.Decision {
	case contracts.CritiqueApprove:
		if len(body.ApprovedClaims) == 0 || len(body.RejectedClaims) > 0 || len(body.Issues) > 0 {
			return
		}
	case contracts.CritiqueRepair, contracts.CritiqueNarrow, contracts.CritiqueReject:
		if len(body.RejectedClaims) == 0 || !issuesHaveAuthorizedClaimRefs(body.Issues) {
			return
		}
	default:
		return
	}
	rejected := make(map[string]bool, len(body.RejectedClaims))
	for _, claimID := range body.RejectedClaims {
		rejected[claimID] = true
	}
	approved := make([]string, 0)
	for _, packet := range packets {
		for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
			if !rejected[finding.ClaimID] {
				approved = append(approved, finding.ClaimID)
			}
		}
	}
	body.ApprovedClaims = uniqueNonEmpty(approved)
}

func issuesHaveAuthorizedClaimRefs(issues []contracts.CritiqueIssue) bool {
	if len(issues) == 0 {
		return false
	}
	for _, issue := range issues {
		if len(issue.ClaimRefs) == 0 {
			return false
		}
	}
	return true
}

func unclassifiedCritiqueClaims(body critiqueBody, packets []contracts.ContextPacket) []string {
	classified := map[string]bool{}
	for _, claimID := range body.ApprovedClaims {
		classified[claimID] = true
	}
	for _, claimID := range body.RejectedClaims {
		classified[claimID] = true
	}
	missing := []string{}
	for _, packet := range packets {
		for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
			if !classified[finding.ClaimID] {
				missing = append(missing, finding.ClaimID)
			}
		}
	}
	sort.Strings(missing)
	return missing
}

func hasUnclassifiedCounterevidence(missing []string, packets []contracts.ContextPacket) bool {
	wanted := make(map[string]bool, len(missing))
	for _, claimID := range missing {
		wanted[claimID] = true
	}
	for _, packet := range packets {
		for _, finding := range packet.Counterevidence {
			if wanted[finding.ClaimID] {
				return true
			}
		}
	}
	return false
}

func requestsCounterevidence(outputs []string) bool {
	for _, output := range outputs {
		if output == "counterevidence" || output == "invalidation_conditions" {
			return true
		}
	}
	return false
}

func (adapters *Adapters) reviewMaterialForPrompt(ctx context.Context, input orchestrator.ReviewInput) (reviewPromptInput, error) {
	result := reviewPromptInput{
		Question: input.Request.UserText, AsOf: input.Request.AsOf,
		Assumptions:  append([]string(nil), input.Request.Assumptions...),
		ReviewerRole: input.Step.RoleID, RepairPass: input.RepairPass,
	}
	for _, prior := range input.Prior {
		view := reviewPriorView{ReportID: prior.ReportID, Decision: prior.Decision}
		for _, issue := range prior.Issues {
			view.Issues = append(view.Issues, reviewPriorIssueView{
				IssueID: issue.IssueID, Severity: issue.Severity, Description: issue.Description,
				RepairHint: issue.RepairHint,
			})
		}
		result.Prior = append(result.Prior, view)
	}
	for _, packet := range input.Packets {
		authority, err := adapters.loadReviewEvidence(ctx, input, packet)
		if err != nil {
			return reviewPromptInput{}, fmt.Errorf("reload review evidence for %s: %w", packet.PacketID, err)
		}
		findings := reviewableFindings(packet.Findings)
		counterevidence := reviewableFindings(packet.Counterevidence)
		view := reviewPacketView{
			PacketID: packet.PacketID, SpecialistRole: packet.SpecialistRole,
			Findings:        findings,
			Counterevidence: counterevidence,
			Assumptions:     append([]string(nil), packet.Assumptions...),
			MissingEvidence: append([]string(nil), packet.MissingEvidence...),
			Conflicts:       append([]string(nil), packet.Conflicts...),
			Uncertainties:   append([]string(nil), packet.Uncertainties...),
		}
		usedEvidence := map[string]bool{}
		usedReceipts := map[string]bool{}
		usedNumerical := map[string]bool{}
		for _, finding := range append(append([]contracts.Finding(nil), findings...), counterevidence...) {
			for _, evidenceID := range finding.EvidenceRefs {
				usedEvidence[evidenceID] = true
			}
			for _, receiptID := range finding.CalculationRefs {
				usedReceipts[receiptID] = true
			}
			for _, numericalID := range finding.NumericalRefs {
				usedNumerical[numericalID] = true
			}
		}
		for _, evidence := range packet.Evidence {
			if !usedEvidence[evidence.EvidenceID] {
				continue
			}
			evidenceView := reviewEvidenceView{
				EvidenceID: evidence.EvidenceID, SourceType: evidence.SourceType,
				DocumentSection: evidence.DocumentSection,
				AsOf:            evidence.AsOf, ContentSHA: evidence.ContentSHA,
			}
			if item, ok := authority[evidence.EvidenceID]; ok && item.EvidenceRef.ContentSHA == evidence.ContentSHA {
				evidenceView.State = string(item.State)
				evidenceView.Statement = redactFinancialNumerics(item.Statement)
				evidenceView.Warnings = append([]string(nil), item.Warnings...)
			}
			view.Evidence = append(view.Evidence, evidenceView)
		}
		view.ValidatedOperations = validatedOperations(packet)
		for _, receipt := range packet.CalculationReceipts {
			if !usedReceipts[receipt.ReceiptID] {
				continue
			}
			receiptView := synthesisReceiptView{
				ReceiptID: receipt.ReceiptID, OperationID: receipt.OperationID,
				Warnings: append([]string(nil), receipt.Warnings...), ReceiptSHA: receipt.ReceiptSHA,
			}
			for _, output := range receipt.Outputs {
				receiptView.Outputs = append(receiptView.Outputs, calculationOutputView{
					OutputID: output.OutputID, Unit: output.Quantity.Unit, Currency: output.Quantity.Currency,
					Period: output.Quantity.Period, Status: output.Status,
				})
			}
			view.CalculationReceipts = append(view.CalculationReceipts, receiptView)
		}
		view.NumericalContext = numericalViewForReferences(packet.NumericalContext, usedNumerical)
		result.Packets = append(result.Packets, view)
	}
	return result, nil
}

func (adapters *Adapters) loadReviewEvidence(ctx context.Context, input orchestrator.ReviewInput, packet contracts.ContextPacket) (map[string]contracts.EvidenceItem, error) {
	step := contracts.PlanStep{ContextBudget: 1}
	for _, candidate := range input.Plan.Steps {
		if candidate.StepID == packet.StepID {
			step = candidate
			break
		}
	}
	material, err := adapters.Materials.Load(ctx, contracts.ContextRequest{
		SchemaVersion: contracts.SchemaVersionV1, ContextRequestID: "review-" + packet.PacketID,
		RunID: input.Request.RunID, StepID: packet.StepID, SpecialistRole: packet.SpecialistRole,
		Objective: packet.Objective, ResearchQuestion: input.Request.UserText, Scope: packet.Scope,
		CapabilityIDs: append([]string(nil), step.CapabilityIDs...),
		Assumptions:   append([]string(nil), input.Request.Assumptions...), TokenBudget: step.ContextBudget,
	})
	if err != nil {
		return nil, err
	}
	result := make(map[string]contracts.EvidenceItem, len(material.Evidence.Items))
	for _, item := range material.Evidence.Items {
		result[item.EvidenceRef.EvidenceID] = item
	}
	return result, nil
}

func validatedOperations(packet contracts.ContextPacket) []string {
	protectedReceipts := map[string]bool{}
	for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
		if finding.Origin != contracts.FindingOriginDeterministic {
			continue
		}
		for _, receiptID := range finding.CalculationRefs {
			protectedReceipts[receiptID] = true
		}
	}
	operations := []string{}
	seen := map[string]bool{}
	for _, receipt := range packet.CalculationReceipts {
		if protectedReceipts[receipt.ReceiptID] && !seen[receipt.OperationID] {
			seen[receipt.OperationID] = true
			operations = append(operations, receipt.OperationID)
		}
	}
	sort.Strings(operations)
	return operations
}

// Go-owned calculation findings have already passed schema, decimal, invariant, lineage, and
// temporal validation. They are deterministically approved after model review, so presenting them
// to a semantic critic only consumes context and output budget without delegating any real
// authority. Source-extracted and model-authored claims remain reviewable.
func reviewableFindings(findings []contracts.Finding) []contracts.Finding {
	result := make([]contracts.Finding, 0, len(findings))
	for _, finding := range findings {
		if finding.Origin == contracts.FindingOriginDeterministic || finding.Origin == contracts.FindingOriginSourceExtraction {
			continue
		}
		result = append(result, finding)
	}
	return result
}

// Exact duplicate references do not change a review decision. Canonicalizing them keeps the
// authority boundary strict while preventing harmless structured-output repetition from turning
// an otherwise valid local review into a runtime failure. For repair, narrow, and reject decisions,
// rejection conservatively wins an overlap. An approve decision with an overlap remains invalid.
func normalizeCritiqueBody(body *critiqueBody) {
	body.ApprovedClaims = uniqueNonEmpty(body.ApprovedClaims)
	body.RejectedClaims = uniqueNonEmpty(body.RejectedClaims)
	for index := range body.Issues {
		body.Issues[index].ClaimRefs = uniqueNonEmpty(body.Issues[index].ClaimRefs)
	}
	if body.Decision == contracts.CritiqueApprove {
		return
	}
	for _, issue := range body.Issues {
		body.RejectedClaims = append(body.RejectedClaims, issue.ClaimRefs...)
	}
	body.RejectedClaims = uniqueNonEmpty(body.RejectedClaims)
	rejected := make(map[string]bool, len(body.RejectedClaims))
	for _, claimID := range body.RejectedClaims {
		rejected[claimID] = true
	}
	approved := make([]string, 0, len(body.ApprovedClaims))
	for _, claimID := range body.ApprovedClaims {
		if !rejected[claimID] {
			approved = append(approved, claimID)
		}
	}
	body.ApprovedClaims = approved
	if body.Decision == contracts.CritiqueReject && len(body.ApprovedClaims) > 0 && len(body.RejectedClaims) > 0 {
		body.Decision = contracts.CritiqueNarrow
	}
}

// A reviewer may omit the unchanged claims from approved_claims while explicitly rejecting only a
// strict subset. That output is a narrowing proposal, not a total rejection. The remaining claims
// are not approved here; they must pass the configured second review after deterministic pruning.
func normalizeCritiqueAgainstPackets(body *critiqueBody, packets []contracts.ContextPacket) {
	if body.Decision != contracts.CritiqueReject || len(body.RejectedClaims) == 0 {
		return
	}
	allClaims := map[string]bool{}
	for _, packet := range packets {
		for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
			allClaims[finding.ClaimID] = true
		}
	}
	if len(body.RejectedClaims) < len(allClaims) {
		body.Decision = contracts.CritiqueNarrow
	}
}

// Review models may repeat a removed historical ID or synthesize a plausible sequential ID. Such
// references are never authorized. Valid siblings survive, while an approval containing only
// invented IDs remains invalid because approved_claims becomes empty.
func dropUnauthorizedCritiqueReferences(body *critiqueBody, packets []contracts.ContextPacket) {
	allowed := map[string]bool{}
	for _, packet := range packets {
		for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
			allowed[finding.ClaimID] = true
		}
	}
	filter := func(values []string) []string {
		result := make([]string, 0, len(values))
		for _, value := range values {
			if allowed[value] {
				result = append(result, value)
			}
		}
		return result
	}
	body.ApprovedClaims = filter(body.ApprovedClaims)
	body.RejectedClaims = filter(body.RejectedClaims)
	for index := range body.Issues {
		body.Issues[index].ClaimRefs = filter(body.Issues[index].ClaimRefs)
	}
}

// Deterministic findings assert only that a validated calculation or relation exists. Their
// arithmetic, lineage, temporal boundary, and invariants have already passed Go-owned checks, so
// a language-model reviewer cannot invalidate them because exact values are intentionally absent
// from its prompt. Reviewers remain authoritative over every model-authored semantic claim.
func protectDeterministicFindings(body *critiqueBody, packets []contracts.ContextPacket) {
	protected := map[string]bool{}
	for _, packet := range packets {
		for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
			if finding.Origin == contracts.FindingOriginDeterministic || finding.Origin == contracts.FindingOriginSourceExtraction {
				protected[finding.ClaimID] = true
			}
		}
	}
	protectClaimSet(body, protected)
}

var conditionalScenarioPattern = regexp.MustCompile(`(?i)\b(?:if|under|scenario|assuming|conditional|may|might|could|would)\b`)
var companyMentionPattern = regexp.MustCompile(`(?i)\b(?:microsoft|nvidia|msft|nvda)\b`)

// An assumption-grounded hypothesis is not an observed fact. Go may preserve it against a critic
// that rejects it solely for lacking observational evidence, but only when its typed structure and
// language keep the scenario boundary explicit. Company-specific hypotheses still require evidence.
func protectAuthorizedScenarioHypotheses(body *critiqueBody, packets []contracts.ContextPacket) {
	protected := map[string]bool{}
	for _, packet := range packets {
		allowedAssumptions := make(map[string]bool, len(packet.Assumptions))
		for _, assumption := range packet.Assumptions {
			allowedAssumptions[assumption] = true
		}
		for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
			if finding.ClaimType != contracts.ClaimHypothesis || len(finding.AssumptionRefs) == 0 ||
				!conditionalScenarioPattern.MatchString(finding.Statement) || unsupportedCausalAssertionPattern.MatchString(finding.Statement) {
				continue
			}
			authorized := true
			for _, assumption := range finding.AssumptionRefs {
				if !allowedAssumptions[assumption] {
					authorized = false
					break
				}
			}
			if !authorized || (companyMentionPattern.MatchString(finding.Statement) && len(finding.EvidenceRefs) == 0) {
				continue
			}
			protected[finding.ClaimID] = true
		}
	}
	protectClaimSet(body, protected)
}

func protectClaimSet(body *critiqueBody, protected map[string]bool) {
	if len(protected) == 0 {
		return
	}
	filterProtected := func(values []string) []string {
		result := make([]string, 0, len(values))
		for _, value := range values {
			if !protected[value] {
				result = append(result, value)
			}
		}
		return result
	}
	body.RejectedClaims = filterProtected(body.RejectedClaims)
	issues := make([]contracts.CritiqueIssue, 0, len(body.Issues))
	for _, issue := range body.Issues {
		issue.ClaimRefs = filterProtected(issue.ClaimRefs)
		if len(issue.ClaimRefs) == 0 {
			continue
		}
		issues = append(issues, issue)
	}
	body.Issues = issues
	for claimID := range protected {
		body.ApprovedClaims = append(body.ApprovedClaims, claimID)
	}
	body.ApprovedClaims = uniqueNonEmpty(body.ApprovedClaims)
	if len(body.RejectedClaims) == 0 && len(body.Issues) == 0 && body.Decision != contracts.CritiqueApprove {
		body.Decision = contracts.CritiqueApprove
	}
}

func uniqueNonEmpty(values []string) []string {
	seen := make(map[string]bool, len(values))
	result := make([]string, 0, len(values))
	for _, value := range values {
		if value == "" || seen[value] {
			continue
		}
		seen[value] = true
		result = append(result, value)
	}
	return result
}

func authorizeCritiqueClaims(report contracts.CritiqueReport, packets []contracts.ContextPacket) error {
	allowed := map[string]bool{}
	for _, packet := range packets {
		for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
			allowed[finding.ClaimID] = true
		}
	}
	seen := map[string]string{}
	for _, group := range []struct {
		name   string
		claims []string
	}{{"approved", report.ApprovedClaims}, {"rejected", report.RejectedClaims}} {
		for _, claimID := range group.claims {
			if !allowed[claimID] {
				return fmt.Errorf("reviewer invented claim %q", claimID)
			}
			if prior, duplicate := seen[claimID]; duplicate {
				return fmt.Errorf("claim %q appears in both %s and %s sets", claimID, prior, group.name)
			}
			seen[claimID] = group.name
		}
	}
	for _, issue := range report.Issues {
		for _, claimID := range issue.ClaimRefs {
			if !allowed[claimID] {
				return fmt.Errorf("critique issue invented claim %q", claimID)
			}
		}
	}
	if len(allowed) == 0 {
		return errors.New("review requires at least one packet claim")
	}
	return nil
}

var _ orchestrator.Reviewer = (*Adapters)(nil)
