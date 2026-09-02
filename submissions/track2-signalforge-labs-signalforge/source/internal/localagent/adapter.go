package localagent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/benchmark"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/engine"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
	"github.com/rvbernucci/signalforge/internal/roles"
)

const maxModelResponseBytes = 1 << 20

type Completer interface {
	Complete(context.Context, benchmark.Request) (benchmark.Completion, error)
}

type Material struct {
	Evidence            contracts.EvidenceBundle       `json:"evidence_bundle"`
	ToolReceipts        []contracts.ToolReceipt        `json:"tool_receipts,omitempty"`
	CalculationReceipts []contracts.CalculationReceipt `json:"calculation_receipts,omitempty"`
	NumericalContext    *contracts.NumericalContext    `json:"numerical_context,omitempty"`
	Retrieval           RetrievalTrace                 `json:"-"`
}

type RetrievalTrace struct {
	Method                 string
	CandidateCount         int
	SelectedCandidateCount int
	RejectedCandidateCount int
	CandidateCountsKnown   bool
}

type calculationInputView struct {
	InputID  string `json:"input_id"`
	Unit     string `json:"unit"`
	Currency string `json:"currency,omitempty"`
	Period   string `json:"period,omitempty"`
	Status   string `json:"status"`
}

type calculationOutputView struct {
	OutputID string `json:"output_id"`
	Unit     string `json:"unit"`
	Currency string `json:"currency,omitempty"`
	Period   string `json:"period,omitempty"`
	Status   string `json:"status"`
}

type calculationReceiptView struct {
	ReceiptID    string                  `json:"receipt_id"`
	OperationID  string                  `json:"operation_id"`
	Status       contracts.ReceiptStatus `json:"status"`
	Inputs       []calculationInputView  `json:"inputs"`
	Assumptions  []string                `json:"assumptions,omitempty"`
	Outputs      []calculationOutputView `json:"outputs"`
	Warnings     []string                `json:"warnings,omitempty"`
	EvidenceRefs []string                `json:"evidence_refs,omitempty"`
	ReceiptSHA   string                  `json:"receipt_sha256"`
}

type numericalVariableView struct {
	VariableID  string                         `json:"variable_id"`
	EntityID    string                         `json:"entity_id"`
	EntityLabel string                         `json:"entity_label,omitempty"`
	MetricID    string                         `json:"metric_id"`
	Period      string                         `json:"period"`
	PeriodBasis contracts.NumericalPeriodBasis `json:"period_basis"`
	PeriodStart *time.Time                     `json:"period_start,omitempty"`
	PeriodEnd   *time.Time                     `json:"period_end,omitempty"`
	Method      contracts.NormalizationMethod  `json:"method"`
	ReceiptRefs []string                       `json:"receipt_refs"`
	Warnings    []string                       `json:"warnings,omitempty"`
}

type numericalRelationView struct {
	RelationID      string                     `json:"relation_id"`
	MetricID        string                     `json:"metric_id"`
	LeftVariableID  string                     `json:"left_variable_id"`
	Operator        contracts.RelationOperator `json:"operator"`
	RightVariableID string                     `json:"right_variable_id"`
	Comparable      bool                       `json:"comparable"`
	ReceiptRefs     []string                   `json:"receipt_refs"`
	Warnings        []string                   `json:"warnings,omitempty"`
}

type numericalContextView struct {
	Version   string                  `json:"version"`
	Variables []numericalVariableView `json:"variables"`
	Relations []numericalRelationView `json:"relations,omitempty"`
}

type promptMaterial struct {
	Evidence            contracts.EvidenceBundle `json:"evidence_bundle"`
	ToolReceipts        []contracts.ToolReceipt  `json:"tool_receipts,omitempty"`
	CalculationReceipts []calculationReceiptView `json:"calculation_receipts,omitempty"`
	NumericalContext    *numericalContextView    `json:"numerical_context,omitempty"`
}

type MaterialProvider interface {
	Load(context.Context, contracts.ContextRequest) (Material, error)
}

type Adapters struct {
	Client    Completer
	Model     string
	Prompts   PromptRegistry
	Materials MaterialProvider
}

func New(client Completer, model string, materials MaterialProvider) (*Adapters, error) {
	return NewWithPromptRegistry(client, model, materials, DefaultPromptRegistry())
}

// NewWithPromptRegistry is reserved for hash-pinned evaluation candidates. Production callers use
// New, which always constructs the frozen default registry.
func NewWithPromptRegistry(client Completer, model string, materials MaterialProvider, prompts PromptRegistry) (*Adapters, error) {
	if client == nil || strings.TrimSpace(model) == "" || materials == nil {
		return nil, errors.New("local model client, model ID, and material provider are required")
	}
	if err := prompts.Validate(roles.DefaultRegistry()); err != nil {
		return nil, err
	}
	return &Adapters{Client: client, Model: model, Prompts: prompts, Materials: materials}, nil
}

type packetBody struct {
	Findings        []contracts.Finding `json:"findings"`
	Counterevidence []contracts.Finding `json:"counterevidence,omitempty"`
	Assumptions     []string            `json:"assumptions,omitempty"`
	MissingEvidence []string            `json:"missing_evidence,omitempty"`
	Conflicts       []string            `json:"conflicts,omitempty"`
	Uncertainties   []string            `json:"uncertainties,omitempty"`
	HandoffNotes    []string            `json:"handoff_notes,omitempty"`
}

func (adapters *Adapters) Run(ctx context.Context, request contracts.ContextRequest) (contracts.ContextPacket, error) {
	return adapters.run(ctx, request, nil, 0)
}

func (adapters *Adapters) RunAttempt(ctx context.Context, request contracts.ContextRequest, attempt int) (contracts.ContextPacket, error) {
	return adapters.run(ctx, request, nil, attempt)
}

func (adapters *Adapters) RunObserved(ctx context.Context, request contracts.ContextRequest, observer orchestrator.SpecialistLifecycleObserver) (contracts.ContextPacket, error) {
	return adapters.run(ctx, request, observer, 0)
}

func (adapters *Adapters) RunObservedAttempt(ctx context.Context, request contracts.ContextRequest, observer orchestrator.SpecialistLifecycleObserver, attempt int) (contracts.ContextPacket, error) {
	return adapters.run(ctx, request, observer, attempt)
}

func (adapters *Adapters) run(ctx context.Context, request contracts.ContextRequest, observer orchestrator.SpecialistLifecycleObserver, attempt int) (contracts.ContextPacket, error) {
	if attempt < 0 || attempt > 1 {
		return contracts.ContextPacket{}, fmt.Errorf("specialist attempt %d is outside the bounded retry contract", attempt)
	}
	if err := contracts.ValidateContextRequest(request); err != nil {
		return contracts.ContextPacket{}, err
	}
	prompt, ok := adapters.Prompts.Get(request.SpecialistRole)
	if !ok {
		return contracts.ContextPacket{}, fmt.Errorf("no prompt for role %q", request.SpecialistRole)
	}
	if attempt == 1 {
		prompt.MaxTokens *= 2
		if prompt.MaxTokens > 3200 {
			prompt.MaxTokens = 3200
		}
	}
	role, ok := roles.DefaultRegistry().Get(request.SpecialistRole)
	if !ok || role.Class != roles.ClassContext {
		return contracts.ContextPacket{}, fmt.Errorf("role %q is not a context specialist", request.SpecialistRole)
	}
	retrieval := orchestrator.RetrievalLifecycle{RetrievalID: "retrieval-" + request.ContextRequestID}
	if observer != nil {
		observer.RetrievalStarted(retrieval)
		ctx = context.WithValue(ctx, lifecycleObserverContextKey{}, observer)
	}
	material, err := adapters.Materials.Load(ctx, request)
	if err != nil {
		if observer != nil {
			retrieval.FailureCode = retrievalFailureCode(err, "material_load_failed")
			observer.RetrievalFailed(retrieval)
		}
		return contracts.ContextPacket{}, fmt.Errorf("load context material: %w", err)
	}
	if err := validateMaterial(material, request); err != nil {
		if observer != nil {
			retrieval.FailureCode = retrievalFailureCode(err, "evidence_contract_failed")
			observer.RetrievalFailed(retrieval)
		}
		return contracts.ContextPacket{}, err
	}
	if observer != nil {
		retrieval = retrievalLifecycle(request, material)
		if len(material.Evidence.Missing) > 0 {
			observer.RetrievalDegraded(retrieval)
		} else {
			observer.RetrievalPassed(retrieval)
		}
	}
	input, err := json.Marshal(struct {
		Request  contracts.ContextRequest `json:"context_request"`
		Material promptMaterial           `json:"authorized_material"`
	}{Request: request, Material: materialForPrompt(material)})
	if err != nil {
		return contracts.ContextPacket{}, err
	}
	completion, err := adapters.complete(ctx, prompt, string(input))
	if err != nil {
		return contracts.ContextPacket{}, err
	}
	var body packetBody
	if decodeErr := decodeJSONObject(completion.Answer, &body); decodeErr != nil {
		if !isIncompleteJSON(decodeErr) {
			return contracts.ContextPacket{}, fmt.Errorf("decode context packet body: %w", decodeErr)
		}
		retryPrompt := prompt
		retryPrompt.MaxTokens = prompt.MaxTokens * 2
		if retryPrompt.MaxTokens > 3200 {
			retryPrompt.MaxTokens = 3200
		}
		completion, err = adapters.complete(ctx, retryPrompt, string(input))
		if err != nil {
			return contracts.ContextPacket{}, err
		}
		body = packetBody{}
		if err := decodeJSONObject(completion.Answer, &body); err != nil {
			return contracts.ContextPacket{}, fmt.Errorf("decode context packet body after bounded truncation retry: %w", err)
		}
	}
	return buildContextPacket(request, material, body)
}

func buildContextPacket(request contracts.ContextRequest, material Material, body packetBody) (contracts.ContextPacket, error) {
	packet := contracts.ContextPacket{
		SchemaVersion: contracts.SchemaVersionV1, PacketID: "packet-" + request.ContextRequestID,
		RunID: request.RunID, StepID: request.StepID, SpecialistRole: request.SpecialistRole,
		Objective: request.Objective, Scope: request.Scope,
		Findings: body.Findings, Counterevidence: body.Counterevidence,
		Assumptions: body.Assumptions, MissingEvidence: body.MissingEvidence,
		Conflicts: body.Conflicts, Uncertainties: body.Uncertainties, HandoffNotes: body.HandoffNotes,
	}
	assignCanonicalClaimIDs(&packet, request.ContextRequestID)
	normalizeUnavailableMaterial(&packet, material)
	expandFindingNumericalRelations(&packet, material.NumericalContext)
	quarantineModelOwnedNumericalDirections(&packet)
	quarantineIncomparableDirections(&packet, material.NumericalContext)
	for index := range packet.Findings {
		normalizeOptionalAssumptionRefs(&packet.Findings[index], packet.Assumptions)
		packet.Findings[index].ValidAsOf = request.Scope.AsOf
	}
	for index := range packet.Counterevidence {
		normalizeOptionalAssumptionRefs(&packet.Counterevidence[index], packet.Assumptions)
		packet.Counterevidence[index].ValidAsOf = request.Scope.AsOf
	}
	quarantinePlaceholderClaims(&packet)
	quarantineStructurallyInvalidClaims(&packet)
	quarantineUnauthorizedClaims(&packet, material)
	appendSourceBackedRiskCounterevidence(&packet, material)
	appendSourceBackedBusinessFacts(&packet, material)
	appendScopeBoundaryFindings(&packet, material)
	appendAccountingAuthorityFindings(&packet, material)
	appendGovernedAbstentionFindings(&packet, material, request)
	appendMarketPriceFindings(&packet, material)
	if request.SpecialistRole == roles.EconomicsTransmission {
		appendCanonicalTransmissionHypotheses(&packet, request.Assumptions)
	}
	appendDeterministicNumericalVariableFindings(&packet, material.NumericalContext)
	appendDeterministicNumericalRelationFindings(&packet, material.NumericalContext)
	if request.SpecialistRole == roles.Valuation {
		appendMissingValuationReceiptFindings(&packet, material.CalculationReceipts, material.NumericalContext)
	}
	assignCanonicalClaimIDs(&packet, request.ContextRequestID)
	for index := range packet.Findings {
		packet.Findings[index].ValidAsOf = request.Scope.AsOf
	}
	for index := range packet.Counterevidence {
		packet.Counterevidence[index].ValidAsOf = request.Scope.AsOf
	}
	quarantineModelSemanticViolations(&packet)
	var err error
	packet.Evidence, packet.CalculationReceipts, packet.NumericalContext, err = authorizePacketReferences(packet, material)
	if err != nil {
		return contracts.ContextPacket{}, err
	}
	if err := contracts.ValidateContextPacket(packet); err != nil {
		return contracts.ContextPacket{}, err
	}
	if err := validateSpecialistSemantics(packet); err != nil {
		return contracts.ContextPacket{}, err
	}
	return packet, nil
}

// Request assumptions need a bounded transmission mechanism even when the model proposes an
// unsupported company ranking. These canonical hypotheses remain general, explicitly conditional,
// and silent on observed causality, direction magnitude, and company-specific relative effects.
func appendCanonicalTransmissionHypotheses(packet *contracts.ContextPacket, assumptions []string) {
	for _, assumption := range assumptions {
		assumption = strings.TrimSpace(assumption)
		if assumption == "" {
			continue
		}
		statement := "Under the explicit request scenario, the stated variable could affect operating and valuation outcomes through financing, demand, or discount-rate channels; direction and magnitude require evidence."
		lower := strings.ToLower(assumption)
		switch {
		case strings.Contains(lower, "interest rate") || strings.Contains(lower, "higher-for-longer"):
			statement = "Under the explicit higher-rate scenario, a higher discount-rate input would reduce otherwise identical present-value outputs; this is a scenario mechanism, not observed causality."
		case strings.Contains(lower, "infrastructure spending") || strings.Contains(lower, "slower spending"):
			statement = "Under the explicit slower-spending scenario, lower demand could pressure utilization, margins, or inventory; direction and magnitude remain unobserved."
		}
		packet.Assumptions = appendUnique(packet.Assumptions, assumption)
		packet.Findings = append(packet.Findings, contracts.Finding{
			ClaimType: contracts.ClaimHypothesis, Statement: statement,
			AssumptionRefs: []string{assumption}, Confidence: 0.5, ValidAsOf: packet.Scope.AsOf,
		})
	}
}

func quarantinePlaceholderClaims(packet *contracts.ContextPacket) {
	filter := func(findings []contracts.Finding) []contracts.Finding {
		kept := make([]contracts.Finding, 0, len(findings))
		for _, finding := range findings {
			if strings.Contains(finding.Statement, "[value withheld]") {
				packet.Uncertainties = appendUnique(packet.Uncertainties,
					fmt.Sprintf("Dropped claim %s because semantic prose contained a numerical placeholder; Go retains any authorized receipt separately.", finding.ClaimID))
				continue
			}
			kept = append(kept, finding)
		}
		return kept
	}
	packet.Findings = filter(packet.Findings)
	packet.Counterevidence = filter(packet.Counterevidence)
}

// A model may select a typed relation for interpretation, but only Go may state its
// quantitative ordering. The deterministic relation finding is appended later.
func quarantineModelOwnedNumericalDirections(packet *contracts.ContextPacket) {
	filter := func(findings []contracts.Finding) []contracts.Finding {
		kept := make([]contracts.Finding, 0, len(findings))
		for _, finding := range findings {
			if finding.Origin != contracts.FindingOriginDeterministic &&
				modelOwnedDirectionPattern.MatchString(finding.Statement) &&
				numericalConceptPattern.MatchString(finding.Statement) {
				packet.Uncertainties = appendUnique(packet.Uncertainties,
					fmt.Sprintf("Dropped claim %s because only Go may state a quantitative direction.", finding.ClaimID))
				continue
			}
			kept = append(kept, finding)
		}
		return kept
	}
	packet.Findings = filter(packet.Findings)
	packet.Counterevidence = filter(packet.Counterevidence)
}

// A point-in-time scope check is application-owned evidence, not model arithmetic. Promoting the
// already validated incomparable boundary to a concise fact prevents a model from silently
// discarding the reason a cross-company historical direction was withheld.
func appendScopeBoundaryFindings(packet *contracts.ContextPacket, material Material) {
	if packet.SpecialistRole != roles.AccountingReporting {
		return
	}
	for _, item := range material.Evidence.Items {
		if item.State != contracts.EvidenceIncomparable || !strings.HasPrefix(item.EvidenceRef.EvidenceID, "comparison:") {
			continue
		}
		packet.Findings = append(packet.Findings, contracts.Finding{
			ClaimType: contracts.ClaimFact, Origin: contracts.FindingOriginSourceExtraction,
			Statement:    "The companies' nominal fiscal periods end on different calendar dates, so a concurrent historical direction is withheld.",
			EvidenceRefs: []string{item.EvidenceRef.EvidenceID}, Confidence: 1,
		})
		return
	}
}

func appendAccountingAuthorityFindings(packet *contracts.ContextPacket, material Material) {
	if packet.SpecialistRole != roles.AccountingReporting {
		return
	}
	for _, item := range material.Evidence.Items {
		if item.State != contracts.EvidenceAvailable ||
			item.EvidenceRef.SourceType != "accounting_authority_policy" {
			continue
		}
		packet.Findings = append(packet.Findings, contracts.Finding{
			ClaimType: contracts.ClaimFact, Origin: contracts.FindingOriginSourceExtraction,
			Statement:    strings.TrimSpace(item.Statement),
			EvidenceRefs: []string{item.EvidenceRef.EvidenceID},
			Confidence:   1,
		})
	}
}

func appendGovernedAbstentionFindings(
	packet *contracts.ContextPacket,
	material Material,
	request contracts.ContextRequest,
) {
	counterevidenceRequested := researchQuestionRequestsCounterevidence(request.ResearchQuestion)
	for _, item := range material.Evidence.Items {
		if item.State != contracts.EvidenceAvailable ||
			item.EvidenceRef.SourceType != "product_scope_policy" ||
			!contains(item.Warnings, "scope_boundary_only") {
			continue
		}
		finding := contracts.Finding{
			ClaimType: contracts.ClaimFact, Origin: contracts.FindingOriginSourceExtraction,
			Statement:    strings.TrimSpace(item.Statement),
			EvidenceRefs: []string{item.EvidenceRef.EvidenceID},
			Confidence:   1,
		}
		// A counterevidence answer contract still needs an approved claim when the governed
		// disposition is "unavailable". Put one source-backed abstention on that channel rather
		// than asking the model to invent disconfirming evidence or failing synthesis.
		if counterevidenceRequested && len(packet.Counterevidence) == 0 {
			packet.Counterevidence = append(packet.Counterevidence, finding)
			continue
		}
		packet.Findings = append(packet.Findings, finding)
	}
}

func researchQuestionRequestsCounterevidence(question string) bool {
	lower := strings.ToLower(question)
	if strings.Contains(lower, "challenge") && strings.Contains(lower, "thesis") {
		return true
	}
	for _, phrase := range []string{
		"counterevidence",
		"counter-evidence",
		"challenge the thesis",
		"challenge my thesis",
		"invalidate the thesis",
		"would invalidate",
		"could invalidate",
		"weakens the thesis",
		"weaken the thesis",
	} {
		if strings.Contains(lower, phrase) {
			return true
		}
	}
	return false
}

func appendMarketPriceFindings(packet *contracts.ContextPacket, material Material) {
	if packet.SpecialistRole != roles.MarketBehavior {
		return
	}
	for _, item := range material.Evidence.Items {
		if item.State != contracts.EvidenceAvailable || item.EvidenceRef.SourceType != "official_exchange_close" {
			continue
		}
		ticker := strings.TrimPrefix(item.EvidenceRef.EvidenceID, "market-price:")
		if ticker == "" {
			continue
		}
		packet.Findings = append(packet.Findings, contracts.Finding{
			ClaimType: contracts.ClaimFact, Origin: contracts.FindingOriginSourceExtraction,
			Statement:    "An official point-in-time exchange close is available for " + strings.ToUpper(ticker) + ".",
			EvidenceRefs: []string{item.EvidenceRef.EvidenceID}, Confidence: 1,
		})
	}
}

// Item 1A is an issuer-authored risk disclosure, not a model inference. The business-strategy
// packet may carry one exact, non-numerical disclosure as counterevidence so a later critic can
// assess it rather than discovering at synthesis time that every contrarian claim disappeared.
// The extraction remains reviewable and fails closed when the source section is ambiguous or the
// source statement contains an authoritative quantity.
func appendSourceBackedRiskCounterevidence(packet *contracts.ContextPacket, material Material) {
	if packet.SpecialistRole != roles.BusinessStrategy {
		return
	}
	candidates := make([]contracts.EvidenceItem, 0)
	for _, item := range material.Evidence.Items {
		if evidenceIsQuarantined(item) || item.State != contracts.EvidenceAvailable || !isSECItem1ARiskSection(item.EvidenceRef.DocumentSection) {
			continue
		}
		statement := strings.TrimSpace(item.Statement)
		if statement == "" || containsAuthoritativeNumericalLiteral(statement) {
			continue
		}
		candidates = append(candidates, item)
	}
	if len(candidates) == 0 {
		return
	}
	sort.Slice(candidates, func(i, j int) bool {
		return candidates[i].EvidenceRef.EvidenceID < candidates[j].EvidenceRef.EvidenceID
	})
	selected := candidates[0]
	packet.Counterevidence = append(packet.Counterevidence, contracts.Finding{
		ClaimType:    contracts.ClaimFact,
		Origin:       contracts.FindingOriginSourceExtraction,
		Statement:    strings.TrimSpace(selected.Statement),
		EvidenceRefs: []string{selected.EvidenceRef.EvidenceID},
		Confidence:   1,
	})
}

func isSECItem1ARiskSection(section string) bool {
	normalized := strings.ToLower(strings.Join(strings.Fields(section), " "))
	return strings.HasPrefix(normalized, "item 1a") && strings.Contains(normalized, "risk")
}

// Item 1 business descriptions are issuer-authored facts. Carrying a bounded exact extraction for
// each available issuer prevents a contrarian review from replacing business-model authority with
// an unrelated risk disclosure merely because model-authored prose was narrowed.
func appendSourceBackedBusinessFacts(packet *contracts.ContextPacket, material Material) {
	if packet.SpecialistRole != roles.BusinessStrategy {
		return
	}
	candidates := make([]contracts.EvidenceItem, 0)
	for _, item := range material.Evidence.Items {
		statement := strings.TrimSpace(item.Statement)
		if evidenceIsQuarantined(item) || item.State != contracts.EvidenceAvailable ||
			!isSECItem1BusinessSection(item.EvidenceRef.DocumentSection) ||
			statement == "" || containsAuthoritativeNumericalLiteral(statement) {
			continue
		}
		candidates = append(candidates, item)
	}
	sort.Slice(candidates, func(i, j int) bool {
		return candidates[i].EvidenceRef.EvidenceID < candidates[j].EvidenceRef.EvidenceID
	})
	for _, item := range candidates {
		packet.Findings = append(packet.Findings, contracts.Finding{
			ClaimType:    contracts.ClaimFact,
			Origin:       contracts.FindingOriginSourceExtraction,
			Statement:    strings.TrimSpace(item.Statement),
			EvidenceRefs: []string{item.EvidenceRef.EvidenceID},
			Confidence:   1,
		})
	}
}

func isSECItem1BusinessSection(section string) bool {
	normalized := strings.ToLower(strings.Join(strings.Fields(section), " "))
	return strings.HasPrefix(normalized, "item 1") &&
		!strings.HasPrefix(normalized, "item 1a") &&
		strings.Contains(normalized, "business")
}

func appendDeterministicNumericalVariableFindings(packet *contracts.ContextPacket, numerical *contracts.NumericalContext) {
	if numerical == nil {
		return
	}
	used := map[string]bool{}
	for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
		if finding.Origin != contracts.FindingOriginDeterministic {
			continue
		}
		for _, numericalID := range finding.NumericalRefs {
			used[numericalID] = true
		}
	}
	inRelation := map[string]bool{}
	for _, relation := range numerical.Relations {
		inRelation[relation.LeftVariableID] = true
		inRelation[relation.RightVariableID] = true
	}
	for _, variable := range numerical.Variables {
		if used[variable.VariableID] || inRelation[variable.VariableID] {
			continue
		}
		label := variable.EntityLabel
		if label == "" {
			label = variable.EntityID
		}
		packet.Findings = append(packet.Findings, contracts.Finding{
			ClaimType: contracts.ClaimCalculation, Origin: contracts.FindingOriginDeterministic,
			Statement: fmt.Sprintf(
				"A deterministic %s result for %s is available for presentation by the trusted numerical renderer.",
				modelFacingMetricLabel(variable.MetricID), label,
			),
			CalculationRefs: append([]string(nil), variable.ReceiptRefs...),
			NumericalRefs:   []string{variable.VariableID},
			Confidence:      1,
		})
	}
}

func appendDeterministicNumericalRelationFindings(packet *contracts.ContextPacket, numerical *contracts.NumericalContext) {
	if numerical == nil {
		return
	}
	used := map[string]bool{}
	for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
		if finding.Origin != contracts.FindingOriginDeterministic {
			continue
		}
		for _, numericalID := range finding.NumericalRefs {
			used[numericalID] = true
		}
	}
	for _, relation := range numerical.Relations {
		if used[relation.RelationID] {
			continue
		}
		packet.Findings = append(packet.Findings, contracts.Finding{
			ClaimType: contracts.ClaimCalculation, Origin: contracts.FindingOriginDeterministic,
			Statement: fmt.Sprintf(
				"A deterministic %s relation is available for presentation by the trusted numerical renderer.",
				modelFacingMetricLabel(relation.MetricID),
			),
			CalculationRefs: append([]string(nil), relation.ReceiptRefs...),
			NumericalRefs:   []string{relation.RelationID},
			Confidence:      1,
		})
	}
}

var directionalSemanticPattern = regexp.MustCompile(`(?i)\b(?:higher|lower|greater|less|more|smaller)\s+than\b|\b(?:above|below|exceeded|outpaced)\b`)

func quarantineIncomparableDirections(packet *contracts.ContextPacket, numerical *contracts.NumericalContext) {
	if numerical == nil {
		return
	}
	incomparable := map[string]bool{}
	for _, relation := range numerical.Relations {
		if !relation.Comparable || relation.Operator == contracts.RelationIncomparable {
			incomparable[relation.RelationID] = true
		}
	}
	filter := func(findings []contracts.Finding) []contracts.Finding {
		kept := make([]contracts.Finding, 0, len(findings))
		for _, finding := range findings {
			contradiction := false
			for _, reference := range finding.NumericalRefs {
				if incomparable[reference] && directionalSemanticPattern.MatchString(finding.Statement) {
					contradiction = true
					break
				}
			}
			if contradiction {
				packet.Uncertainties = appendUnique(packet.Uncertainties,
					fmt.Sprintf("Dropped claim %s because it assigned direction to an incomparable numerical relation.", finding.ClaimID))
				continue
			}
			kept = append(kept, finding)
		}
		return kept
	}
	packet.Findings = filter(packet.Findings)
	packet.Counterevidence = filter(packet.Counterevidence)
}

func isIncompleteJSON(err error) bool {
	return errors.Is(err, io.ErrUnexpectedEOF) || strings.Contains(strings.ToLower(err.Error()), "unexpected eof") || strings.Contains(strings.ToLower(err.Error()), "unexpected end of json")
}

func expandFindingNumericalRelations(packet *contracts.ContextPacket, numerical *contracts.NumericalContext) {
	if numerical == nil {
		return
	}
	expand := func(findings []contracts.Finding) {
		for index := range findings {
			refs := stringSet(findings[index].NumericalRefs)
			for _, relation := range numerical.Relations {
				if !refs[relation.LeftVariableID] && !refs[relation.RightVariableID] {
					continue
				}
				delete(refs, relation.LeftVariableID)
				delete(refs, relation.RightVariableID)
				refs[relation.RelationID] = true
			}
			findings[index].NumericalRefs = sortedStringSet(refs)
		}
	}
	expand(packet.Findings)
	expand(packet.Counterevidence)
}

func sortedStringSet(values map[string]bool) []string {
	result := make([]string, 0, len(values))
	for value := range values {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}

func appendMissingValuationReceiptFindings(packet *contracts.ContextPacket, receipts []contracts.CalculationReceipt, numerical *contracts.NumericalContext) {
	used := map[string]bool{}
	usedNumerical := map[string]bool{}
	for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
		if finding.Origin != contracts.FindingOriginDeterministic {
			continue
		}
		for _, receiptID := range finding.CalculationRefs {
			used[receiptID] = true
		}
		for _, numericalID := range finding.NumericalRefs {
			usedNumerical[numericalID] = true
		}
	}
	receiptByID := make(map[string]contracts.CalculationReceipt, len(receipts))
	for _, receipt := range receipts {
		receiptByID[receipt.ReceiptID] = receipt
	}
	if numerical != nil {
		for _, relation := range numerical.Relations {
			if usedNumerical[relation.RelationID] {
				continue
			}
			relationReceipts := []string{}
			for _, receiptID := range relation.ReceiptRefs {
				receipt, ok := receiptByID[receiptID]
				if !ok || !isRequiredValuationReceipt(receipt.OperationID) {
					continue
				}
				relationReceipts = append(relationReceipts, receiptID)
			}
			if len(relationReceipts) == 0 {
				continue
			}
			sort.Strings(relationReceipts)
			packet.Findings = append(packet.Findings, contracts.Finding{
				ClaimType: contracts.ClaimCalculation, Origin: contracts.FindingOriginDeterministic,
				Statement: fmt.Sprintf(
					"A deterministic %s comparison is available for presentation by the trusted numerical renderer.",
					modelFacingMetricLabel(relation.MetricID),
				),
				CalculationRefs: relationReceipts,
				NumericalRefs:   []string{relation.RelationID},
				Confidence:      1,
			})
			for _, receiptID := range relationReceipts {
				used[receiptID] = true
			}
		}
	}
	for _, receipt := range receipts {
		if used[receipt.ReceiptID] || !isRequiredValuationReceipt(receipt.OperationID) {
			continue
		}
		numericalRefs := []string{}
		if numerical != nil {
			for _, variable := range numerical.Variables {
				if contains(variable.ReceiptRefs, receipt.ReceiptID) {
					numericalRefs = append(numericalRefs, variable.VariableID)
				}
			}
		}
		packet.Findings = append(packet.Findings, contracts.Finding{
			ClaimType:       contracts.ClaimCalculation,
			Origin:          contracts.FindingOriginDeterministic,
			Statement:       fmt.Sprintf("A deterministic %s result is available for presentation by the trusted numerical renderer.", modelFacingMetricLabel(receipt.OperationID)),
			CalculationRefs: []string{receipt.ReceiptID}, NumericalRefs: numericalRefs, Confidence: 1,
		})
	}
}

func modelFacingMetricLabel(metricID string) string {
	parts := strings.Split(strings.TrimSpace(metricID), ".")
	label := strings.ReplaceAll(parts[len(parts)-1], "_", " ")
	if strings.EqualFold(label, "fcff dcf") {
		return "FCFF DCF"
	}
	return label
}

func isRequiredValuationReceipt(operationID string) bool {
	switch operationID {
	case "valuation.fcff_dcf", "scenario.sensitivity_matrix", "valuation.peer_multiple":
		return true
	default:
		return false
	}
}

// Claim identifiers are orchestration metadata, not model-authored research content. Go assigns
// globally unambiguous IDs so reviewers can address one exact claim even when several local
// specialists independently emit placeholders such as claim-001 or null.
func assignCanonicalClaimIDs(packet *contracts.ContextPacket, contextRequestID string) {
	sequence := 0
	assign := func(findings []contracts.Finding) {
		for index := range findings {
			sequence++
			findings[index].ClaimID = fmt.Sprintf("claim-%s-%03d", contextRequestID, sequence)
		}
	}
	assign(packet.Findings)
	assign(packet.Counterevidence)
}

func materialForPrompt(material Material) promptMaterial {
	evidence := material.Evidence
	evidence.Items = append([]contracts.EvidenceItem(nil), material.Evidence.Items...)
	for index := range evidence.Items {
		evidence.Items[index].Statement = redactFinancialNumerics(evidence.Items[index].Statement)
		quarantineEvidenceForPrompt(&evidence.Items[index])
	}
	evidence.Missing = append([]string(nil), material.Evidence.Missing...)
	for index := range evidence.Missing {
		evidence.Missing[index] = redactFinancialNumerics(evidence.Missing[index])
	}
	result := promptMaterial{Evidence: evidence, ToolReceipts: material.ToolReceipts}
	for _, receipt := range material.CalculationReceipts {
		result.CalculationReceipts = append(result.CalculationReceipts, calculationReceiptForPrompt(receipt))
	}
	if material.NumericalContext != nil {
		view := &numericalContextView{Version: material.NumericalContext.Version}
		for _, variable := range material.NumericalContext.Variables {
			view.Variables = append(view.Variables, numericalVariableView{
				VariableID: variable.VariableID, EntityID: variable.EntityID, EntityLabel: variable.EntityLabel,
				MetricID: variable.MetricID, Period: variable.Period, PeriodBasis: variable.PeriodBasis,
				PeriodStart: variable.PeriodStart, PeriodEnd: variable.PeriodEnd, Method: variable.Method,
				ReceiptRefs: append([]string(nil), variable.ReceiptRefs...), Warnings: append([]string(nil), variable.Warnings...),
			})
		}
		for _, relation := range material.NumericalContext.Relations {
			view.Relations = append(view.Relations, numericalRelationView{
				RelationID: relation.RelationID, MetricID: relation.MetricID,
				LeftVariableID: relation.LeftVariableID, Operator: relation.Operator,
				RightVariableID: relation.RightVariableID, Comparable: relation.Comparable,
				ReceiptRefs: append([]string(nil), relation.ReceiptRefs...), Warnings: append([]string(nil), relation.Warnings...),
			})
		}
		result.NumericalContext = view
	}
	return result
}

func calculationReceiptForPrompt(receipt contracts.CalculationReceipt) calculationReceiptView {
	view := calculationReceiptView{
		ReceiptID: receipt.ReceiptID, OperationID: receipt.OperationID, Status: receipt.Status,
		Assumptions:  append([]string(nil), receipt.Assumptions...),
		Warnings:     append([]string(nil), receipt.Warnings...),
		EvidenceRefs: append([]string(nil), receipt.EvidenceRefs...), ReceiptSHA: receipt.ReceiptSHA,
	}
	for index := range view.Assumptions {
		view.Assumptions[index] = redactFinancialNumerics(view.Assumptions[index])
	}
	for _, input := range receipt.NormalizedInputs {
		view.Inputs = append(view.Inputs, calculationInputView{
			InputID: input.InputID, Unit: input.Quantity.Unit,
			Currency: input.Quantity.Currency, Period: input.Quantity.Period, Status: input.Status,
		})
	}
	for _, output := range receipt.Outputs {
		view.Outputs = append(view.Outputs, calculationOutputView{
			OutputID: output.OutputID, Unit: output.Quantity.Unit, Currency: output.Quantity.Currency,
			Period: output.Quantity.Period, Status: output.Status,
		})
	}
	return view
}

// Availability state is deterministic source metadata. A missing or incomparable item may explain
// why no answer is possible, but it cannot become affirmative claim evidence. Go propagates the
// source gap and drops claims supported exclusively by unavailable markers before authorization.
func normalizeUnavailableMaterial(packet *contracts.ContextPacket, material Material) {
	states := make(map[string]contracts.EvidenceState, len(material.Evidence.Items))
	for _, item := range material.Evidence.Items {
		state := evidenceStateForModel(item)
		states[item.EvidenceRef.EvidenceID] = state
		if state == contracts.EvidenceMissing || state == contracts.EvidenceIncomparable {
			statement := item.Statement
			if evidenceIsQuarantined(item) {
				statement = quarantinedEvidenceStatement
			}
			packet.MissingEvidence = appendUnique(packet.MissingEvidence, statement)
		}
	}
	packet.MissingEvidence = appendUnique(packet.MissingEvidence, material.Evidence.Missing...)
	packet.Findings = dropUnavailableOnlyFindings(packet.Findings, states)
	packet.Counterevidence = dropUnavailableOnlyFindings(packet.Counterevidence, states)
}

func dropUnavailableOnlyFindings(findings []contracts.Finding, states map[string]contracts.EvidenceState) []contracts.Finding {
	result := make([]contracts.Finding, 0, len(findings))
	for _, finding := range findings {
		unavailable, authorized := 0, 0
		for _, evidenceID := range finding.EvidenceRefs {
			switch states[evidenceID] {
			case contracts.EvidenceMissing, contracts.EvidenceIncomparable:
				unavailable++
			case contracts.EvidenceAvailable, contracts.EvidenceConflicting, contracts.EvidenceStale:
				authorized++
			}
		}
		if unavailable > 0 && authorized == 0 && len(finding.CalculationRefs) == 0 {
			continue
		}
		result = append(result, finding)
	}
	return result
}

func appendUnique(values []string, additions ...string) []string {
	for _, addition := range additions {
		if strings.TrimSpace(addition) != "" && !contains(values, addition) {
			values = append(values, addition)
		}
	}
	return values
}

// Facts, calculations, and hypotheses do not require assumption references. Removing an
// unauthorized optional reference is safer than allowing a model-created alias into the packet;
// inferences remain fail-closed because their explicit assumptions are semantically material.
func normalizeOptionalAssumptionRefs(finding *contracts.Finding, assumptions []string) {
	if finding.ClaimType == contracts.ClaimInference {
		return
	}
	valid := make([]string, 0, len(finding.AssumptionRefs))
	for _, reference := range finding.AssumptionRefs {
		if contains(assumptions, reference) {
			valid = append(valid, reference)
		}
	}
	finding.AssumptionRefs = valid
}

// A model-created reference never gains authority. Quarantining only the affected claim keeps
// unrelated, independently supported findings available while making the loss visible downstream.
func quarantineUnauthorizedClaims(packet *contracts.ContextPacket, material Material) {
	allowedEvidence := map[string]bool{}
	for _, item := range material.Evidence.Items {
		if evidenceIsQuarantined(item) {
			continue
		}
		if item.State == contracts.EvidenceAvailable || item.State == contracts.EvidenceConflicting || item.State == contracts.EvidenceStale {
			allowedEvidence[item.EvidenceRef.EvidenceID] = true
		}
	}
	allowedReceipts := map[string]bool{}
	for _, receipt := range material.CalculationReceipts {
		allowedReceipts[receipt.ReceiptID] = true
	}
	allowedNumerical := map[string]bool{}
	if material.NumericalContext != nil {
		for _, variable := range material.NumericalContext.Variables {
			allowedNumerical[variable.VariableID] = true
		}
		for _, relation := range material.NumericalContext.Relations {
			allowedNumerical[relation.RelationID] = true
		}
	}
	allowedAssumptions := map[string]bool{}
	for _, assumption := range packet.Assumptions {
		allowedAssumptions[assumption] = true
	}
	filter := func(findings []contracts.Finding) []contracts.Finding {
		kept := make([]contracts.Finding, 0, len(findings))
		for _, finding := range findings {
			reason := ""
			for _, evidenceID := range finding.EvidenceRefs {
				if !allowedEvidence[evidenceID] {
					reason = "unauthorized evidence reference"
					break
				}
			}
			if reason == "" {
				for _, receiptID := range finding.CalculationRefs {
					if !allowedReceipts[receiptID] {
						reason = "unauthorized calculation receipt"
						break
					}
				}
			}
			if reason == "" {
				for _, numericalID := range finding.NumericalRefs {
					if !allowedNumerical[numericalID] {
						reason = "unauthorized numerical reference"
						break
					}
				}
			}
			if reason == "" {
				for _, assumption := range finding.AssumptionRefs {
					if !allowedAssumptions[assumption] {
						reason = "unauthorized assumption reference"
						break
					}
				}
			}
			if reason != "" {
				packet.Uncertainties = appendUnique(packet.Uncertainties,
					fmt.Sprintf("Dropped claim %s because it contained an %s.", finding.ClaimID, reason))
				continue
			}
			kept = append(kept, finding)
		}
		return kept
	}
	packet.Findings = filter(packet.Findings)
	packet.Counterevidence = filter(packet.Counterevidence)
}

func quarantineStructurallyInvalidClaims(packet *contracts.ContextPacket) {
	filter := func(findings []contracts.Finding) []contracts.Finding {
		kept := make([]contracts.Finding, 0, len(findings))
		for _, finding := range findings {
			reason := structuralClaimReason(finding)
			if reason != "" {
				packet.Uncertainties = appendUnique(packet.Uncertainties,
					fmt.Sprintf("Dropped claim %s because %s.", finding.ClaimID, reason))
				continue
			}
			kept = append(kept, finding)
		}
		return kept
	}
	packet.Findings = filter(packet.Findings)
	packet.Counterevidence = filter(packet.Counterevidence)
}

func structuralClaimReason(finding contracts.Finding) string {
	statement := strings.TrimSpace(finding.Statement)
	if statement == "" || strings.EqualFold(statement, "null") || strings.EqualFold(statement, "n/a") {
		return "its statement was empty"
	}
	if containsAuthoritativeNumericalLiteral(finding.Statement) {
		return "its model-authored statement crossed the numerical-silence boundary"
	}
	if finding.Confidence < 0 || finding.Confidence > 1 {
		return "its confidence was outside the allowed range"
	}
	switch finding.ClaimType {
	case contracts.ClaimFact:
		if len(finding.EvidenceRefs) == 0 {
			return "a fact had no evidence reference"
		}
	case contracts.ClaimCalculation:
		if len(finding.CalculationRefs) == 0 {
			return "a calculation had no receipt reference"
		}
	case contracts.ClaimInference:
		if len(finding.EvidenceRefs)+len(finding.CalculationRefs)+len(finding.NumericalRefs) == 0 || len(finding.AssumptionRefs) == 0 {
			return "an inference lacked support or an explicit assumption"
		}
	case contracts.ClaimHypothesis:
		if len(finding.EvidenceRefs)+len(finding.CalculationRefs)+len(finding.NumericalRefs)+len(finding.AssumptionRefs) == 0 {
			return "an unsupported hypothesis had no explicit assumption"
		}
	default:
		return "its claim type was unsupported"
	}
	return ""
}

func (adapters *Adapters) complete(ctx context.Context, prompt Prompt, input string) (benchmark.Completion, error) {
	seed := 42
	chatTemplateKwargs, thinking := modelGenerationControls(adapters.Model)
	return adapters.Client.Complete(ctx, benchmark.Request{
		Model:     adapters.Model,
		Messages:  []benchmark.Message{{Role: "system", Content: prompt.System}, {Role: "user", Content: input}},
		MaxTokens: prompt.MaxTokens, Temperature: prompt.Temperature, Seed: &seed,
		ResponseFormat:     prompt.ResponseFormat(),
		ChatTemplateKwargs: chatTemplateKwargs,
		Thinking:           thinking,
	})
}

func modelGenerationControls(model string) (map[string]any, map[string]any) {
	if strings.Contains(strings.ToLower(model), "deepseek") {
		return nil, map[string]any{"type": "disabled"}
	}
	return map[string]any{"enable_thinking": false}, nil
}

type lifecycleObserverContextKey struct{}

func retrievalLifecycle(request contracts.ContextRequest, material Material) orchestrator.RetrievalLifecycle {
	sourceSet := map[string]bool{}
	for _, item := range material.Evidence.Items {
		sourceType := strings.TrimSpace(item.EvidenceRef.SourceType)
		if sourceType != "" {
			sourceSet[sourceType] = true
		}
	}
	sourceClasses := make([]string, 0, len(sourceSet))
	for sourceType := range sourceSet {
		sourceClasses = append(sourceClasses, sourceType)
	}
	sort.Strings(sourceClasses)
	return orchestrator.RetrievalLifecycle{
		RetrievalID:            "retrieval-" + request.ContextRequestID,
		BundleID:               material.Evidence.BundleID,
		Method:                 material.Retrieval.Method,
		EvidenceCount:          len(material.Evidence.Items),
		SourceClasses:          sourceClasses,
		AsOf:                   material.Evidence.AsOf,
		MissingEvidenceCount:   len(material.Evidence.Missing),
		CandidateCount:         material.Retrieval.CandidateCount,
		SelectedCandidateCount: material.Retrieval.SelectedCandidateCount,
		RejectedCandidateCount: material.Retrieval.RejectedCandidateCount,
		CandidateCountsKnown:   material.Retrieval.CandidateCountsKnown,
	}
}

func retrievalFailureCode(err error, fallback string) string {
	switch {
	case errors.Is(err, context.DeadlineExceeded):
		return "retrieval_deadline_exceeded"
	case errors.Is(err, context.Canceled):
		return "retrieval_cancelled"
	default:
		return fallback
	}
}

// ObserveToolStarted, ObserveToolPassed, and ObserveToolFailed bridge deterministic engines to the
// optional orchestration observer without exposing values or source bodies.
func ObserveToolStarted(ctx context.Context, request contracts.EngineRequest) {
	if observer := lifecycleObserver(ctx); observer != nil {
		observer.ToolStarted(toolLifecycleFromRequest(request))
	}
}

func ObserveToolPassed(ctx context.Context, receipt contracts.CalculationReceipt) {
	if observer := lifecycleObserver(ctx); observer != nil {
		observer.ToolPassed(toolLifecycleFromReceipt(receipt))
	}
}

func ObserveToolFailed(ctx context.Context, request contracts.EngineRequest, code string) {
	if observer := lifecycleObserver(ctx); observer != nil {
		lifecycle := toolLifecycleFromRequest(request)
		lifecycle.FailureCode = code
		observer.ToolFailed(lifecycle)
	}
}

func lifecycleObserver(ctx context.Context) orchestrator.SpecialistLifecycleObserver {
	if ctx == nil {
		return nil
	}
	observer, _ := ctx.Value(lifecycleObserverContextKey{}).(orchestrator.SpecialistLifecycleObserver)
	return observer
}

func toolLifecycleFromRequest(request contracts.EngineRequest) orchestrator.ToolLifecycle {
	inputIDs := make([]string, 0, len(request.Inputs))
	for _, input := range request.Inputs {
		inputIDs = append(inputIDs, input.InputID)
	}
	return orchestrator.ToolLifecycle{
		ToolExecutionID: request.RequestID,
		EngineID:        request.EngineID,
		OperationID:     request.OperationID,
		FormulaVersion:  request.FormulaVersion,
		InputRefIDs:     inputIDs,
		InputCount:      len(request.Inputs),
		OutputCount:     len(request.RequestedOutputs),
	}
}

func toolLifecycleFromReceipt(receipt contracts.CalculationReceipt) orchestrator.ToolLifecycle {
	inputIDs := make([]string, 0, len(receipt.NormalizedInputs))
	for _, input := range receipt.NormalizedInputs {
		inputIDs = append(inputIDs, input.InputID)
	}
	outputIDs := make([]string, 0, len(receipt.Outputs))
	for _, output := range receipt.Outputs {
		outputIDs = append(outputIDs, output.OutputID)
	}
	invariantsPassed := true
	for _, invariant := range receipt.InvariantResults {
		if !invariant.Passed {
			invariantsPassed = false
			break
		}
	}
	verification := "metadata_only"
	if engine.VerifyReceipt(receipt) == nil {
		verification = "canonical_verified"
	}
	return orchestrator.ToolLifecycle{
		ToolExecutionID:     receipt.RequestID,
		ReceiptID:           receipt.ReceiptID,
		ReceiptSHA:          receipt.ReceiptSHA,
		ReceiptVerification: verification,
		EngineID:            receipt.EngineID,
		OperationID:         receipt.OperationID,
		FormulaVersion:      receipt.FormulaVersion,
		InputRefIDs:         inputIDs,
		OutputRefIDs:        outputIDs,
		InputCount:          len(receipt.NormalizedInputs),
		OutputCount:         len(receipt.Outputs),
		InvariantCount:      len(receipt.InvariantResults),
		InvariantsPassed:    invariantsPassed,
		WarningCount:        len(receipt.Warnings),
	}
}

func validateMaterial(material Material, request contracts.ContextRequest) error {
	if material.Evidence.SchemaVersion != contracts.SchemaVersionV1 || material.Evidence.RunID != request.RunID ||
		material.Evidence.StepID != request.StepID || material.Evidence.AsOf.IsZero() || material.Evidence.AsOf.After(request.Scope.AsOf) {
		return errors.New("evidence bundle does not match the context request")
	}
	if err := contracts.ValidateEvidenceBundle(material.Evidence); err != nil {
		return err
	}
	for _, receipt := range material.ToolReceipts {
		if receipt.RunID != request.RunID || receipt.StepID != request.StepID || receipt.Status != contracts.ReceiptSuccess {
			return fmt.Errorf("receipt %q is not an authorized successful result for this step", receipt.ReceiptID)
		}
		if err := contracts.ValidateToolReceipt(receipt); err != nil {
			return err
		}
	}
	for _, receipt := range material.CalculationReceipts {
		if receipt.Status != contracts.ReceiptSuccess {
			return fmt.Errorf("calculation receipt %q is not successful", receipt.ReceiptID)
		}
		if err := contracts.ValidateCalculationReceipt(receipt); err != nil {
			return err
		}
	}
	if material.NumericalContext != nil {
		if material.NumericalContext.RunID != request.RunID || material.NumericalContext.AsOf.After(request.Scope.AsOf) {
			return errors.New("numerical context does not match the context request")
		}
		if err := contracts.ValidateNumericalContext(*material.NumericalContext); err != nil {
			return err
		}
		allowedReceipts := make(map[string]bool, len(material.CalculationReceipts))
		for _, receipt := range material.CalculationReceipts {
			allowedReceipts[receipt.ReceiptID] = true
		}
		for _, variable := range material.NumericalContext.Variables {
			for _, receiptID := range variable.ReceiptRefs {
				if !allowedReceipts[receiptID] {
					return fmt.Errorf("numerical variable %q references unauthorized receipt %q", variable.VariableID, receiptID)
				}
			}
		}
	}
	return nil
}

func authorizePacketReferences(packet contracts.ContextPacket, material Material) ([]contracts.EvidenceRef, []contracts.CalculationReceipt, *contracts.NumericalContext, error) {
	allowedEvidence := map[string]contracts.EvidenceRef{}
	scopeEvidence := map[string]contracts.EvidenceRef{}
	for _, item := range material.Evidence.Items {
		if evidenceIsQuarantined(item) {
			continue
		}
		if item.State == contracts.EvidenceAvailable || item.State == contracts.EvidenceConflicting || item.State == contracts.EvidenceStale {
			allowedEvidence[item.EvidenceRef.EvidenceID] = item.EvidenceRef
		}
		if item.State == contracts.EvidenceIncomparable && strings.HasPrefix(item.EvidenceRef.EvidenceID, "comparison:") {
			scopeEvidence[item.EvidenceRef.EvidenceID] = item.EvidenceRef
		}
	}
	allowedReceipts := map[string]contracts.CalculationReceipt{}
	for _, receipt := range material.CalculationReceipts {
		allowedReceipts[receipt.ReceiptID] = receipt
	}
	allowedVariables := map[string]contracts.NumericalVariable{}
	allowedRelations := map[string]contracts.NumericalRelation{}
	if material.NumericalContext != nil {
		for _, variable := range material.NumericalContext.Variables {
			allowedVariables[variable.VariableID] = variable
		}
		for _, relation := range material.NumericalContext.Relations {
			allowedRelations[relation.RelationID] = relation
		}
	}
	usedEvidence := map[string]bool{}
	usedReceipts := map[string]bool{}
	usedVariables := map[string]bool{}
	usedRelations := map[string]bool{}
	claimIDs := map[string]bool{}
	all := append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...)
	for _, finding := range all {
		if claimIDs[finding.ClaimID] {
			return nil, nil, nil, fmt.Errorf("duplicate claim ID %q", finding.ClaimID)
		}
		claimIDs[finding.ClaimID] = true
		for _, evidenceID := range finding.EvidenceRefs {
			if _, ok := allowedEvidence[evidenceID]; !ok {
				scope, scopeOK := scopeEvidence[evidenceID]
				if !scopeOK || finding.Origin != contracts.FindingOriginSourceExtraction {
					return nil, nil, nil, fmt.Errorf("claim %q invented or cannot use evidence %q", finding.ClaimID, evidenceID)
				}
				allowedEvidence[evidenceID] = scope
			}
			usedEvidence[evidenceID] = true
		}
		for _, receiptID := range finding.CalculationRefs {
			if _, ok := allowedReceipts[receiptID]; !ok {
				return nil, nil, nil, fmt.Errorf("claim %q invented or cannot use receipt %q", finding.ClaimID, receiptID)
			}
			usedReceipts[receiptID] = true
		}
		for _, numericalID := range finding.NumericalRefs {
			if variable, ok := allowedVariables[numericalID]; ok {
				usedVariables[numericalID] = true
				for _, evidenceID := range variable.EvidenceRefs {
					usedEvidence[evidenceID] = true
				}
				for _, receiptID := range variable.ReceiptRefs {
					usedReceipts[receiptID] = true
				}
				continue
			}
			if relation, ok := allowedRelations[numericalID]; ok {
				usedRelations[numericalID] = true
				usedVariables[relation.LeftVariableID] = true
				usedVariables[relation.RightVariableID] = true
				for _, evidenceID := range relation.EvidenceRefs {
					usedEvidence[evidenceID] = true
				}
				for _, receiptID := range relation.ReceiptRefs {
					usedReceipts[receiptID] = true
				}
				continue
			}
			return nil, nil, nil, fmt.Errorf("claim %q invented or cannot use numerical reference %q", finding.ClaimID, numericalID)
		}
		for _, assumption := range finding.AssumptionRefs {
			if !contains(packet.Assumptions, assumption) {
				return nil, nil, nil, fmt.Errorf("claim %q references unknown assumption %q", finding.ClaimID, assumption)
			}
		}
	}
	result := []contracts.EvidenceRef{}
	for _, item := range material.Evidence.Items {
		if usedEvidence[item.EvidenceRef.EvidenceID] {
			result = append(result, item.EvidenceRef)
		}
	}
	receipts := make([]contracts.CalculationReceipt, 0, len(usedReceipts))
	for _, receipt := range material.CalculationReceipts {
		if usedReceipts[receipt.ReceiptID] {
			receipts = append(receipts, receipt)
		}
	}
	var numerical *contracts.NumericalContext
	if len(usedVariables)+len(usedRelations) > 0 {
		selected := contracts.NumericalContext{
			SchemaVersion: material.NumericalContext.SchemaVersion, ContextID: material.NumericalContext.ContextID,
			RunID: material.NumericalContext.RunID, Version: material.NumericalContext.Version, AsOf: material.NumericalContext.AsOf,
		}
		for _, variable := range material.NumericalContext.Variables {
			if usedVariables[variable.VariableID] {
				selected.Variables = append(selected.Variables, variable)
			}
		}
		for _, relation := range material.NumericalContext.Relations {
			if usedRelations[relation.RelationID] {
				selected.Relations = append(selected.Relations, relation)
			}
		}
		contracts.SortNumericalContext(&selected)
		numerical = &selected
	}
	return result, receipts, numerical, nil
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func decodeJSONObject(payload string, destination any) error {
	if len(payload) > maxModelResponseBytes {
		return fmt.Errorf("model response exceeds %d-byte contract", maxModelResponseBytes)
	}
	trimmed := strings.TrimSpace(payload)
	if strings.HasPrefix(trimmed, "```") {
		firstNewline := strings.IndexByte(trimmed, '\n')
		lastFence := strings.LastIndex(trimmed, "```")
		if firstNewline < 0 || lastFence <= firstNewline {
			return errors.New("malformed JSON code fence")
		}
		trimmed = strings.TrimSpace(trimmed[firstNewline+1 : lastFence])
	}
	decoder := json.NewDecoder(strings.NewReader(trimmed))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return err
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("multiple JSON values are not allowed")
		}
		return fmt.Errorf("invalid trailing JSON content: %w", err)
	}
	return nil
}

var _ orchestrator.Specialist = (*Adapters)(nil)
var _ orchestrator.ObservedSpecialist = (*Adapters)(nil)
