package localagent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/numericalcontext"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
	"github.com/rvbernucci/signalforge/internal/roles"
)

type finalBody struct {
	Sections    []answerSectionDraft `json:"sections"`
	Assumptions []string             `json:"assumptions,omitempty"`
	Limitations []string             `json:"limitations,omitempty"`
	NextActions []string             `json:"next_actions,omitempty"`
}

// answerSectionDraft is the semantic boundary presented to the model. Go owns
// evidence and receipt joins so the model cannot invent or mismatch authority.
type answerSectionDraft struct {
	SectionType string   `json:"section_type"`
	Title       string   `json:"title"`
	Content     string   `json:"content"`
	ClaimRefs   []string `json:"claim_refs"`
}

type synthesisRequestView struct {
	Question         string    `json:"question"`
	PrimaryIntent    string    `json:"primary_intent"`
	AsOf             time.Time `json:"as_of"`
	RequestedOutputs []string  `json:"requested_outputs"`
	Assumptions      []string  `json:"assumptions,omitempty"`
}

type synthesisClaimView struct {
	SpecialistRole string            `json:"specialist_role"`
	Disposition    string            `json:"disposition"`
	Finding        contracts.Finding `json:"finding"`
}

type synthesisReceiptView struct {
	ReceiptID   string                  `json:"receipt_id"`
	OperationID string                  `json:"operation_id"`
	Outputs     []calculationOutputView `json:"outputs"`
	Warnings    []string                `json:"warnings,omitempty"`
	ReceiptSHA  string                  `json:"receipt_sha256"`
}

type synthesisCritiqueView struct {
	ReportID       string   `json:"report_id"`
	ReviewerRole   string   `json:"reviewer_role"`
	ApprovedClaims []string `json:"approved_claims"`
}

type synthesisPromptInput struct {
	Request             synthesisRequestView    `json:"request"`
	Claims              []synthesisClaimView    `json:"approved_claims"`
	Evidence            []reviewEvidenceView    `json:"evidence"`
	Receipts            []synthesisReceiptView  `json:"calculation_receipts"`
	ValidatedOperations []string                `json:"validated_operations,omitempty"`
	Numerical           []*numericalContextView `json:"numerical_contexts,omitempty"`
	Boundaries          []synthesisBoundaryView `json:"epistemic_boundaries,omitempty"`
	Critiques           []synthesisCritiqueView `json:"approved_critiques"`
}

type synthesisBoundaryView struct {
	SpecialistRole string `json:"specialist_role"`
	BoundaryType   string `json:"boundary_type"`
	Statement      string `json:"statement"`
}

func (adapters *Adapters) Synthesize(ctx context.Context, input orchestrator.SynthesisInput) (contracts.FinalAnswer, error) {
	prompt, _ := adapters.Prompts.Get(roles.FinalResearchAnalyst)
	for _, critique := range input.Critiques {
		if critique.Decision != contracts.CritiqueApprove {
			return contracts.FinalAnswer{}, errors.New("final synthesis requires approved critique reports")
		}
	}
	material := synthesisMaterialForPrompt(input)
	prompt.ResponseSchema = finalSchemaForOutputs(input.Request.RequestedOutputs, synthesisClaimIDs(material.Claims))
	payload, err := json.Marshal(material)
	if err != nil {
		return contracts.FinalAnswer{}, err
	}
	completion, err := adapters.complete(ctx, prompt, string(payload))
	if err != nil {
		return contracts.FinalAnswer{}, err
	}
	var body finalBody
	retried := false
	if decodeErr := decodeJSONObject(completion.Answer, &body); decodeErr != nil {
		if !isIncompleteJSON(decodeErr) {
			return contracts.FinalAnswer{}, fmt.Errorf("decode final answer body: %w", decodeErr)
		}
		retried = true
		retryPrompt := prompt
		retryPrompt.MaxTokens *= 2
		if retryPrompt.MaxTokens > 4000 {
			retryPrompt.MaxTokens = 4000
		}
		completion, err = adapters.complete(ctx, retryPrompt, string(payload))
		if err != nil {
			return contracts.FinalAnswer{}, err
		}
		body = finalBody{}
		if err := decodeJSONObject(completion.Answer, &body); err != nil {
			return contracts.FinalAnswer{}, fmt.Errorf("decode final answer body after bounded truncation retry: %w", err)
		}
	}
	placeApprovedCounterevidenceClaims(body.Sections, material.Claims)
	canonicalizeRequestedAssumptions(&body, material)
	placeRequiredSemanticAuthority(body.Sections, material)
	draftErr := validateNumericallySilentDraft(body)
	if draftErr == nil {
		draftErr = validateRequiredDecisionSections(body, input.Request.RequestedOutputs, material.Claims)
	}
	if draftErr == nil {
		draftErr = validateDecisionSemanticAuthority(body, material)
	}
	if draftErr == nil {
		draftErr = validateResponsibleUse(body)
	}
	if draftErr == nil {
		draftErr = validateModelOwnedNumericalAuthority(body, material)
	}
	if draftErr == nil {
		draftErr = validateReceiptAvailabilityClaims(body, material)
	}
	if draftErr == nil {
		draftErr = validatePresentationQuality(body)
	}
	if draftErr != nil {
		if retried {
			return contracts.FinalAnswer{}, draftErr
		}
		retryPrompt := prompt
		retryPrompt.System += " The previous semantic draft was rejected by application code. On this single bounded repair, use qualitative language, normal English spelling, and approved claim_refs only. Do not repeat, mask, replace, or paraphrase any number; Go will render every authorized quantity after synthesis. Do not state which company has a higher, lower, greater, or smaller financial metric, valuation, price, return, margin, growth rate, cash flow, or multiple; select the approved claim_refs and let Go render direction. Never say that DCF, sensitivity, multiples, or another calculation is missing when a corresponding calculation_receipt is present. When counterevidence or invalidation_conditions is requested, each section must cite at least one approved claim whose disposition is counterevidence. State an explicit testable invalidation condition without inventing a numerical threshold. A comparison section must cite approved business-strategy, accounting-reporting, and financial-quality claims. A transmission_mechanisms section must cite an approved economics-transmission claim. A market_measurement section must cite an approved market-behavior claim. A scenarios section must cite both an approved valuation claim and an approved scenario-grounded economics-transmission claim. In transmission_mechanisms and market_measurement, never use caused, causes, resulted from, resulted in, because of, or due to. Never claim that correlation, co-movement, or timing proves causality. Never tell the user to buy, sell, or hold a security and never promise a return, profit, upside, or certainty."
		completion, err = adapters.complete(ctx, retryPrompt, string(payload))
		if err != nil {
			return contracts.FinalAnswer{}, err
		}
		body = finalBody{}
		if err := decodeJSONObject(completion.Answer, &body); err != nil {
			return contracts.FinalAnswer{}, fmt.Errorf("decode final answer body after bounded numerical-silence retry: %w", err)
		}
		placeApprovedCounterevidenceClaims(body.Sections, material.Claims)
		canonicalizeRequestedAssumptions(&body, material)
		placeRequiredSemanticAuthority(body.Sections, material)
		if err := validateNumericallySilentDraft(body); err != nil {
			return contracts.FinalAnswer{}, fmt.Errorf("final answer after bounded numerical-silence retry: %w", err)
		}
		if err := validateRequiredDecisionSections(body, input.Request.RequestedOutputs, material.Claims); err != nil {
			return contracts.FinalAnswer{}, fmt.Errorf("final answer after bounded decision-section retry: %w", err)
		}
		if err := validateDecisionSemanticAuthority(body, material); err != nil {
			return contracts.FinalAnswer{}, fmt.Errorf("final answer after bounded semantic-authority retry: %w", err)
		}
		if err := validateResponsibleUse(body); err != nil {
			return contracts.FinalAnswer{}, fmt.Errorf("final answer after bounded responsible-use retry: %w", err)
		}
		if err := validateModelOwnedNumericalAuthority(body, material); err != nil {
			return contracts.FinalAnswer{}, fmt.Errorf("final answer after bounded numerical-authority retry: %w", err)
		}
		if err := validateReceiptAvailabilityClaims(body, material); err != nil {
			return contracts.FinalAnswer{}, fmt.Errorf("final answer after bounded availability retry: %w", err)
		}
		if err := validatePresentationQuality(body); err != nil {
			return contracts.FinalAnswer{}, fmt.Errorf("final answer after bounded presentation retry: %w", err)
		}
	}
	placeApprovedNumericalClaims(body.Sections, material.Claims)
	sections, err := assembleFinalSections(body.Sections, input.Request.RequestedOutputs, input.Packets)
	if err != nil {
		return contracts.FinalAnswer{}, err
	}
	if err := synchronizeSemanticSections(sections, body.Assumptions, body.Limitations); err != nil {
		return contracts.FinalAnswer{}, err
	}
	appendEpistemicBoundaryDisclosures(sections)
	if err := appendNumericalDisclosures(sections, input.Packets); err != nil {
		return contracts.FinalAnswer{}, err
	}
	answer := contracts.FinalAnswer{
		SchemaVersion: contracts.SchemaVersionV1, AnswerID: "answer-" + input.Request.RequestID,
		RunID: input.Request.RunID, RequestID: input.Request.RequestID,
		PrimaryIntent: input.Request.PrimaryIntent, AsOf: input.Request.AsOf,
		Sections: sections, Assumptions: body.Assumptions, Limitations: body.Limitations,
		NextActions: body.NextActions, ReleasedBy: roles.FinalResearchAnalyst, ReleasedAt: input.Request.AsOf,
	}
	for _, critique := range input.Critiques {
		answer.CritiqueRefs = append(answer.CritiqueRefs, critique.ReportID)
	}
	if err := authorizeFinalReferences(answer, input.Packets, input.Critiques); err != nil {
		return contracts.FinalAnswer{}, err
	}
	if err := contracts.ValidateFinalAnswer(answer); err != nil {
		return contracts.FinalAnswer{}, err
	}
	if err := validateDirectionalComparisons(answer); err != nil {
		return contracts.FinalAnswer{}, err
	}
	return answer, nil
}

// The model owns prose selection, while Go owns the mandatory authority join. Neutral boundary
// clauses make every inserted reference semantically visible instead of attaching hidden citations
// to unrelated prose. Missing authority is never invented and still fails the downstream gate.
func placeRequiredSemanticAuthority(sections []answerSectionDraft, material synthesisPromptInput) {
	byRole := map[string][]synthesisClaimView{}
	for _, claim := range material.Claims {
		byRole[claim.SpecialistRole] = append(byRole[claim.SpecialistRole], claim)
	}
	appendRef := func(section *answerSectionDraft, claimID string) {
		if claimID != "" && !slices.Contains(section.ClaimRefs, claimID) {
			section.ClaimRefs = append(section.ClaimRefs, claimID)
		}
	}
	first := func(roleID string) string {
		if len(byRole[roleID]) == 0 {
			return ""
		}
		return byRole[roleID][0].Finding.ClaimID
	}
	claimByEvidence := func(match func(string) bool) string {
		for _, claim := range material.Claims {
			for _, evidenceID := range claim.Finding.EvidenceRefs {
				if match(strings.ToLower(evidenceID)) {
					return claim.Finding.ClaimID
				}
			}
		}
		return ""
	}
	fiscalBoundary := claimByEvidence(func(evidenceID string) bool {
		return strings.Contains(evidenceID, "fiscal-period-boundary")
	})
	macroAuthority := claimByEvidence(func(evidenceID string) bool {
		return strings.Contains(evidenceID, "fx") || strings.Contains(evidenceID, "rate-risk") ||
			strings.Contains(evidenceID, "export-controls") || strings.Contains(evidenceID, "supply-chain")
	})
	for index := range sections {
		section := &sections[index]
		switch section.SectionType {
		case "comparison":
			appendRef(section, first(roles.BusinessStrategy))
			appendRef(section, first(roles.AccountingReporting))
			appendRef(section, first(roles.FinancialQuality))
			appendRef(section, fiscalBoundary)
			section.Content = appendSentence(section.Content, "Business-model evidence, reporting comparability, and receipt-backed financial quality are considered together.")
			section.Content = appendSentence(section.Content, "Differing fiscal-period boundaries constrain direct historical comparison.")
		case "transmission_mechanisms":
			appendRef(section, first(roles.EconomicsTransmission))
			appendRef(section, macroAuthority)
			section.Content = appendSentence(section.Content, "Transmission is presented as a conditional scenario mechanism.")
			section.Content = appendSentence(section.Content, "Macro transmission remains anchored to issuer-disclosed currency, rate, export-control, or supply-chain risk.")
		case "market_measurement":
			appendRef(section, first(roles.MarketBehavior))
			section.Content = appendSentence(section.Content, "Market observations are measurements, not causal attributions.")
		case "scenarios":
			appendRef(section, first(roles.Valuation))
			appendRef(section, macroAuthority)
			for _, assumption := range material.Request.Assumptions {
				for _, claim := range byRole[roles.EconomicsTransmission] {
					if slices.Contains(claim.Finding.AssumptionRefs, assumption) {
						appendRef(section, claim.Finding.ClaimID)
						break
					}
				}
			}
			section.Content = appendSentence(section.Content, "Scenario ranges combine Go-validated valuation receipts with the explicit macro assumptions.")
		}
	}
}

func appendSentence(content, sentence string) string {
	content = strings.TrimSpace(content)
	if content == "" {
		return sentence
	}
	if strings.Contains(content, sentence) {
		return content
	}
	return content + " " + sentence
}

func placeApprovedNumericalClaims(sections []answerSectionDraft, claims []synthesisClaimView) {
	analyticalUse := map[string]bool{}
	for _, section := range sections {
		if isNumericalPresentationSection(section.SectionType) {
			for _, claimID := range section.ClaimRefs {
				analyticalUse[claimID] = true
			}
		}
	}
	for _, claim := range claims {
		if len(claim.Finding.NumericalRefs) == 0 || analyticalUse[claim.Finding.ClaimID] {
			continue
		}
		targets := numericalSectionPreference(claim.SpecialistRole)
		for _, target := range targets {
			placed := false
			for index := range sections {
				if sections[index].SectionType != target {
					continue
				}
				sections[index].ClaimRefs = append(sections[index].ClaimRefs, claim.Finding.ClaimID)
				analyticalUse[claim.Finding.ClaimID] = true
				placed = true
				break
			}
			if placed {
				break
			}
		}
	}
}

func numericalSectionPreference(roleID string) []string {
	switch roleID {
	case roles.Valuation:
		return []string{"valuation_range", "sensitivity", "scenarios", "comparison", "thesis", "company_example"}
	case roles.FinancialQuality, roles.AccountingReporting:
		return []string{"financial_quality", "comparison", "thesis", "company_example", "scenarios"}
	case roles.MarketBehavior:
		return []string{"market_measurement", "comparison", "thesis", "scenarios"}
	default:
		return []string{"comparison", "thesis", "scenarios", "company_example"}
	}
}

func isNumericalPresentationSection(sectionType string) bool {
	switch sectionType {
	case "evidence", "assumptions", "limitations", "counterevidence", "invalidation_conditions":
		return false
	default:
		return true
	}
}

func placeApprovedCounterevidenceClaims(sections []answerSectionDraft, claims []synthesisClaimView) {
	approved := make([]string, 0)
	for _, claim := range claims {
		if claim.Disposition == "counterevidence" {
			approved = append(approved, claim.Finding.ClaimID)
		}
	}
	if len(approved) == 0 {
		return
	}
	for index := range sections {
		if sections[index].SectionType != "counterevidence" && sections[index].SectionType != "invalidation_conditions" {
			continue
		}
		hasCounterevidence := false
		for _, claimID := range sections[index].ClaimRefs {
			if slices.Contains(approved, claimID) {
				hasCounterevidence = true
				break
			}
		}
		if !hasCounterevidence {
			sections[index].ClaimRefs = append(sections[index].ClaimRefs, approved[0])
		}
	}
}

func validateRequiredDecisionSections(body finalBody, requested []string, claims []synthesisClaimView) error {
	requestedSet := make(map[string]bool, len(requested))
	for _, sectionType := range requested {
		requestedSet[sectionType] = true
	}
	counterevidenceIDs := make(map[string]bool)
	for _, claim := range claims {
		if claim.Disposition == "counterevidence" {
			counterevidenceIDs[claim.Finding.ClaimID] = true
		}
	}
	for _, requiredType := range []string{"counterevidence", "invalidation_conditions"} {
		if !requestedSet[requiredType] {
			continue
		}
		found := false
		for _, section := range body.Sections {
			if section.SectionType != requiredType {
				continue
			}
			found = true
			supported := false
			for _, claimID := range section.ClaimRefs {
				if counterevidenceIDs[claimID] {
					supported = true
					break
				}
			}
			if !supported {
				return fmt.Errorf("section %q requires an approved counterevidence claim", requiredType)
			}
			content := strings.ToLower(strings.TrimSpace(section.Content))
			if content == "" || strings.Contains(content, "no explicit") || strings.Contains(content, "not provided") {
				return fmt.Errorf("section %q requires an explicit decision-relevant statement", requiredType)
			}
		}
		if !found {
			return fmt.Errorf("section %q is required", requiredType)
		}
	}
	return nil
}

var unsupportedCausalAssertionPattern = regexp.MustCompile(`(?i)\b(?:caused|causes|resulted\s+(?:from|in)|because\s+of|due\s+to)\b`)
var directInvestmentInstructionPattern = regexp.MustCompile(`(?i)\b(?:(?:you|investors?|users?)\s+should\s+|(?:i|we)\s+recommend\s+)?(?:strong\s+)?(?:buy(?:ing)?|sell(?:ing)?|hold(?:ing)?)\s+(?:the\s+|this\s+|these\s+)?(?:stock|shares?|security|securities)\b`)
var guaranteedOutcomePattern = regexp.MustCompile(`(?i)\b(?:guaranteed|certain|risk[- ]free|cannot\s+lose|sure\s+to)\b.{0,36}\b(?:return|profit|upside|gain|outperform|increase|rise)\b`)

func canonicalizeRequestedAssumptions(body *finalBody, material synthesisPromptInput) {
	// Request assumptions are user- or application-authorized scenario boundaries. Model-authored
	// additions are not allowed to become a second assumption authority.
	body.Assumptions = dedupeStrings(append([]string(nil), material.Request.Assumptions...))
}

func validateDecisionSemanticAuthority(body finalBody, material synthesisPromptInput) error {
	sections := make(map[string]answerSectionDraft, len(body.Sections))
	for _, section := range body.Sections {
		sections[section.SectionType] = section
	}
	claims := make(map[string]synthesisClaimView, len(material.Claims))
	for _, claim := range material.Claims {
		claims[claim.Finding.ClaimID] = claim
	}
	hasRole := func(section answerSectionDraft, roleID string) bool {
		for _, claimID := range section.ClaimRefs {
			if claim, ok := claims[claimID]; ok && claim.SpecialistRole == roleID {
				return true
			}
		}
		return false
	}

	if section, required := sections["transmission_mechanisms"]; required {
		if !hasRole(section, roles.EconomicsTransmission) {
			return errors.New("transmission_mechanisms requires approved economics-transmission authority")
		}
		if unsupportedCausalAssertionPattern.MatchString(section.Content) {
			return errors.New("transmission_mechanisms contains unsupported causal attribution")
		}
	}
	if section, required := sections["comparison"]; required {
		for _, roleID := range []string{roles.BusinessStrategy, roles.AccountingReporting, roles.FinancialQuality} {
			if !hasRole(section, roleID) {
				return fmt.Errorf("comparison requires approved %s authority", roleID)
			}
		}
	}
	if section, required := sections["market_measurement"]; required {
		if !hasRole(section, roles.MarketBehavior) {
			return errors.New("market_measurement requires approved market-behavior authority")
		}
		if unsupportedCausalAssertionPattern.MatchString(section.Content) {
			return errors.New("market_measurement contains unsupported causal attribution")
		}
	}
	if section, required := sections["scenarios"]; required {
		if !hasRole(section, roles.Valuation) {
			return errors.New("scenarios requires approved valuation authority")
		}
		coveredAssumptions := map[string]bool{}
		for _, claimID := range section.ClaimRefs {
			claim, ok := claims[claimID]
			if !ok || claim.SpecialistRole != roles.EconomicsTransmission ||
				(claim.Finding.ClaimType != contracts.ClaimInference && claim.Finding.ClaimType != contracts.ClaimHypothesis) {
				continue
			}
			for _, assumption := range claim.Finding.AssumptionRefs {
				coveredAssumptions[assumption] = true
			}
		}
		for _, assumption := range material.Request.Assumptions {
			if !coveredAssumptions[assumption] {
				return fmt.Errorf("scenarios omitted economics-transmission authority for request assumption %q", assumption)
			}
		}
	}
	return nil
}

func validateResponsibleUse(body finalBody) error {
	texts := make([]string, 0, len(body.Sections)+len(body.Assumptions)+len(body.Limitations)+len(body.NextActions))
	for _, section := range body.Sections {
		texts = append(texts, section.Content)
	}
	texts = append(texts, body.Assumptions...)
	texts = append(texts, body.Limitations...)
	texts = append(texts, body.NextActions...)
	for _, text := range texts {
		if directInvestmentInstructionPattern.MatchString(text) {
			return errors.New("semantic draft contains a direct investment instruction")
		}
		if guaranteedOutcomePattern.MatchString(text) {
			return errors.New("semantic draft contains an unjustified guaranteed outcome")
		}
	}
	return nil
}

const (
	transmissionBoundaryDisclosure = "These mechanisms are scenario-conditioned pathways, not estimates of observed causality."
	marketBoundaryDisclosure       = "Price co-movement, correlation, and event-window timing do not by themselves establish causality."
)

func appendEpistemicBoundaryDisclosures(sections []contracts.AnswerSection) {
	for index := range sections {
		var disclosure string
		switch sections[index].SectionType {
		case "transmission_mechanisms":
			disclosure = transmissionBoundaryDisclosure
		case "market_measurement":
			disclosure = marketBoundaryDisclosure
		}
		if disclosure != "" && !strings.Contains(sections[index].Content, disclosure) {
			sections[index].Content = strings.TrimSpace(sections[index].Content) + "\n\n" + disclosure
		}
	}
}

func synchronizeSemanticSections(sections []contracts.AnswerSection, assumptions, limitations []string) error {
	for index := range sections {
		switch sections[index].SectionType {
		case "assumptions":
			if len(assumptions) == 0 {
				return errors.New("final assumptions section requires at least one explicit assumption")
			}
			sections[index].Title = "Assumptions"
			sections[index].Content = strings.Join(assumptions, " ")
		case "limitations":
			if len(limitations) == 0 {
				return errors.New("final limitations section requires at least one explicit limitation")
			}
			sections[index].Title = "Limitations"
			sections[index].Content = strings.Join(limitations, " ")
		}
	}
	return nil
}

var modelOwnedDirectionPattern = regexp.MustCompile(`(?i)\b(?:higher|lower|greater|less|more|smaller|larger)\s+than\b|\b(?:above|below|exceeds?|outpaces?|underperforms?|overperforms?)\b`)
var numericalConceptPattern = regexp.MustCompile(`(?i)\b(?:dcf|discounted\s+cash\s+flow|enterprise\s+value|valuation|multiple|margin|growth|revenue|cash\s+flow|capex|return|volatility|beta|correlation|price|earnings|debt|equity)\b`)
var unavailableAuthorityPattern = regexp.MustCompile(`(?i)\b(?:not\s+(?:available|provided|supplied|present)|unavailable|missing|absent|withheld|remain(?:s)?\s+open)\b`)
var malformedMixedCasePattern = regexp.MustCompile(`[a-z][A-Z]{2,}\b`)

// Models may explain why a deterministic relation matters, but they cannot author the relation's
// company ordering. Go appends the validated direction after synthesis.
func validateModelOwnedNumericalAuthority(body finalBody, material synthesisPromptInput) error {
	_ = material
	for _, section := range body.Sections {
		for _, sentence := range splitSemanticSentences(section.Content) {
			if !modelOwnedDirectionPattern.MatchString(sentence) || !numericalConceptPattern.MatchString(sentence) {
				continue
			}
			return fmt.Errorf("section %q authored a numerical direction outside Go authority", section.SectionType)
		}
	}
	return nil
}

// Missing-evidence prose from one specialist can become stale after another specialist contributes
// a successful receipt. The final draft must respect the globally joined calculation authority.
func validateReceiptAvailabilityClaims(body finalBody, material synthesisPromptInput) error {
	operations := map[string]bool{}
	for _, operation := range material.ValidatedOperations {
		operations[operation] = true
	}
	for _, receipt := range material.Receipts {
		operations[receipt.OperationID] = true
	}
	type authority struct {
		operation string
		terms     []string
	}
	authorities := []authority{
		{operation: "valuation.fcff_dcf", terms: []string{"dcf", "discounted cash flow", "valuation range", "valuation ranges"}},
		{operation: "scenario.sensitivity_matrix", terms: []string{"sensitivity", "sensitivity matrix"}},
		{operation: "valuation.peer_multiple", terms: []string{"multiple", "multiples"}},
	}
	texts := make([]string, 0, len(body.Sections)+len(body.Limitations))
	for _, section := range body.Sections {
		texts = append(texts, section.Content)
	}
	texts = append(texts, body.Limitations...)
	for _, text := range texts {
		for _, sentence := range splitSemanticSentences(text) {
			if !unavailableAuthorityPattern.MatchString(sentence) {
				continue
			}
			lower := strings.ToLower(sentence)
			for _, item := range authorities {
				if !operations[item.operation] {
					continue
				}
				for _, term := range item.terms {
					if strings.Contains(lower, term) {
						return fmt.Errorf("semantic draft says %s authority is unavailable despite a successful receipt", item.operation)
					}
				}
			}
		}
	}
	return nil
}

func validatePresentationQuality(body finalBody) error {
	texts := make([]string, 0, len(body.Sections)+len(body.Limitations)+len(body.NextActions))
	for _, section := range body.Sections {
		texts = append(texts, section.Title, section.Content)
	}
	texts = append(texts, body.Limitations...)
	texts = append(texts, body.NextActions...)
	for _, text := range texts {
		if token := malformedMixedCasePattern.FindString(text); token != "" {
			return fmt.Errorf("semantic draft contains malformed mixed-case token %q", token)
		}
	}
	return nil
}

func splitSemanticSentences(value string) []string {
	return strings.FieldsFunc(value, func(r rune) bool {
		return r == '.' || r == '!' || r == '?' || r == '\n'
	})
}

var directionalComparisonPattern = regexp.MustCompile(`(?i)\b(lower|less|smaller|below|higher|more|greater|larger|above)\b[^.!?()]{0,120}\(\s*([+-]?[0-9]+(?:\.[0-9]+)?)%?\s+(?:vs\.?|versus)\s+[^0-9+\-]{0,40}([+-]?[0-9]+(?:\.[0-9]+)?)%?\s*\)`)

func validateDirectionalComparisons(answer contracts.FinalAnswer) error {
	for _, section := range answer.Sections {
		for _, match := range directionalComparisonPattern.FindAllStringSubmatch(section.Content, -1) {
			left, leftErr := strconv.ParseFloat(match[2], 64)
			right, rightErr := strconv.ParseFloat(match[3], 64)
			if leftErr != nil || rightErr != nil {
				continue
			}
			direction := strings.ToLower(match[1])
			lower := direction == "lower" || direction == "less" || direction == "smaller" || direction == "below"
			if (lower && left >= right) || (!lower && left <= right) {
				return fmt.Errorf("section %q contains a contradictory directional comparison: %q", section.SectionType, match[0])
			}
		}
	}
	return nil
}

func synthesisClaimIDs(claims []synthesisClaimView) []string {
	result := make([]string, 0, len(claims))
	for _, claim := range claims {
		result = append(result, claim.Finding.ClaimID)
	}
	return result
}

func assembleFinalSections(
	drafts []answerSectionDraft,
	requested []string,
	packets []contracts.ContextPacket,
) ([]contracts.AnswerSection, error) {
	byType := make(map[string]answerSectionDraft, len(drafts))
	for _, draft := range drafts {
		if _, exists := byType[draft.SectionType]; exists {
			return nil, fmt.Errorf("final answer duplicated section %q", draft.SectionType)
		}
		byType[draft.SectionType] = draft
	}
	if len(byType) != len(requested) {
		return nil, fmt.Errorf("final answer produced %d unique sections for %d requested outputs", len(byType), len(requested))
	}

	claimAuthority := make(map[string]contracts.Finding)
	for _, packet := range packets {
		for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
			claimAuthority[finding.ClaimID] = finding
		}
	}

	sections := make([]contracts.AnswerSection, 0, len(requested))
	for _, sectionType := range requested {
		draft, exists := byType[sectionType]
		if !exists {
			return nil, fmt.Errorf("final answer omitted requested section %q", sectionType)
		}
		section := contracts.AnswerSection{
			SectionType: draft.SectionType,
			Title:       draft.Title,
			Content:     draft.Content,
			ClaimRefs:   dedupeStrings(draft.ClaimRefs),
		}
		seenEvidence, seenReceipts, seenNumerical := map[string]bool{}, map[string]bool{}, map[string]bool{}
		for _, claimID := range section.ClaimRefs {
			finding, ok := claimAuthority[claimID]
			if !ok {
				return nil, fmt.Errorf("final answer used unknown claim %q", claimID)
			}
			for _, evidenceID := range finding.EvidenceRefs {
				if !seenEvidence[evidenceID] {
					seenEvidence[evidenceID] = true
					section.EvidenceRefs = append(section.EvidenceRefs, evidenceID)
				}
			}
			for _, receiptID := range finding.CalculationRefs {
				if !seenReceipts[receiptID] {
					seenReceipts[receiptID] = true
					section.ReceiptRefs = append(section.ReceiptRefs, receiptID)
				}
			}
			for _, numericalID := range finding.NumericalRefs {
				if !seenNumerical[numericalID] {
					seenNumerical[numericalID] = true
					section.NumericalRefs = append(section.NumericalRefs, numericalID)
				}
			}
		}
		sections = append(sections, section)
	}
	return sections, nil
}

func dedupeStrings(values []string) []string {
	seen := make(map[string]bool, len(values))
	result := make([]string, 0, len(values))
	for _, value := range values {
		if value != "" && !seen[value] {
			seen[value] = true
			result = append(result, value)
		}
	}
	return result
}

func synthesisMaterialForPrompt(input orchestrator.SynthesisInput) synthesisPromptInput {
	result := synthesisPromptInput{Request: synthesisRequestView{
		Question: input.Request.UserText, PrimaryIntent: input.Request.PrimaryIntent,
		AsOf: input.Request.AsOf, RequestedOutputs: append([]string(nil), input.Request.RequestedOutputs...),
		Assumptions: append([]string(nil), input.Request.Assumptions...),
	}}
	successfulOperations := successfulReceiptOperations(input.Packets)
	for operation := range successfulOperations {
		result.ValidatedOperations = append(result.ValidatedOperations, operation)
	}
	sort.Strings(result.ValidatedOperations)
	approvalCount := map[string]int{}
	for _, critique := range input.Critiques {
		result.Critiques = append(result.Critiques, synthesisCritiqueView{
			ReportID: critique.ReportID, ReviewerRole: critique.ReviewerRole,
			ApprovedClaims: append([]string(nil), critique.ApprovedClaims...),
		})
		for _, claimID := range critique.ApprovedClaims {
			approvalCount[claimID]++
		}
	}
	usedEvidence, usedReceipts, usedNumerical := map[string]bool{}, map[string]bool{}, map[string]bool{}
	appendClaim := func(packet contracts.ContextPacket, finding contracts.Finding, disposition string) {
		if approvalCount[finding.ClaimID] != len(input.Critiques) {
			return
		}
		promptFinding := finding
		promptFinding.Statement = redactFinancialNumerics(promptFinding.Statement)
		result.Claims = append(result.Claims, synthesisClaimView{SpecialistRole: packet.SpecialistRole, Disposition: disposition, Finding: promptFinding})
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
	for _, packet := range input.Packets {
		for _, finding := range packet.Findings {
			appendClaim(packet, finding, "finding")
		}
		for _, finding := range packet.Counterevidence {
			appendClaim(packet, finding, "counterevidence")
		}
	}
	seenEvidence, seenReceipts := map[string]bool{}, map[string]bool{}
	for _, packet := range input.Packets {
		for _, evidence := range packet.Evidence {
			if usedEvidence[evidence.EvidenceID] && !seenEvidence[evidence.EvidenceID] {
				seenEvidence[evidence.EvidenceID] = true
				result.Evidence = append(result.Evidence, reviewEvidenceView{
					EvidenceID: evidence.EvidenceID, SourceType: evidence.SourceType,
					AsOf: evidence.AsOf, ContentSHA: evidence.ContentSHA,
				})
			}
		}
		for _, receipt := range packet.CalculationReceipts {
			if usedReceipts[receipt.ReceiptID] && !seenReceipts[receipt.ReceiptID] {
				seenReceipts[receipt.ReceiptID] = true
				view := synthesisReceiptView{
					ReceiptID: receipt.ReceiptID, OperationID: receipt.OperationID,
					Warnings: append([]string(nil), receipt.Warnings...), ReceiptSHA: receipt.ReceiptSHA,
				}
				for _, output := range receipt.Outputs {
					view.Outputs = append(view.Outputs, calculationOutputView{
						OutputID: output.OutputID, Unit: output.Quantity.Unit, Currency: output.Quantity.Currency,
						Period: output.Quantity.Period, Status: output.Status,
					})
				}
				result.Receipts = append(result.Receipts, view)
			}
		}
		if view := numericalViewForReferences(packet.NumericalContext, usedNumerical); view != nil {
			result.Numerical = append(result.Numerical, view)
		}
		for _, value := range packet.MissingEvidence {
			if missingBoundarySupersededByReceipt(value, successfulOperations) {
				continue
			}
			result.Boundaries = append(result.Boundaries, synthesisBoundaryView{
				SpecialistRole: packet.SpecialistRole, BoundaryType: "missing_evidence", Statement: redactFinancialNumerics(value),
			})
		}
		for _, value := range packet.Conflicts {
			result.Boundaries = append(result.Boundaries, synthesisBoundaryView{
				SpecialistRole: packet.SpecialistRole, BoundaryType: "conflict", Statement: redactFinancialNumerics(value),
			})
		}
		for _, value := range packet.Uncertainties {
			result.Boundaries = append(result.Boundaries, synthesisBoundaryView{
				SpecialistRole: packet.SpecialistRole, BoundaryType: "uncertainty", Statement: redactFinancialNumerics(value),
			})
		}
	}
	return result
}

func successfulReceiptOperations(packets []contracts.ContextPacket) map[string]bool {
	operations := map[string]bool{}
	for _, packet := range packets {
		for _, receipt := range packet.CalculationReceipts {
			if receipt.Status == contracts.ReceiptSuccess {
				operations[receipt.OperationID] = true
			}
		}
	}
	return operations
}

func missingBoundarySupersededByReceipt(statement string, operations map[string]bool) bool {
	lower := strings.ToLower(strings.TrimSpace(statement))
	if operations["valuation.fcff_dcf"] &&
		(strings.Contains(lower, "dcf valuation range") || strings.Contains(lower, "discounted cash flow result")) {
		return true
	}
	if operations["scenario.sensitivity_matrix"] &&
		(strings.Contains(lower, "sensitivity matrix") || strings.Contains(lower, "sensitivity result")) {
		return true
	}
	return operations["valuation.peer_multiple"] &&
		(lower == "multiple" || lower == "multiples" || strings.Contains(lower, "peer multiple") || strings.Contains(lower, "valuation multiple"))
}

func numericalViewForReferences(context *contracts.NumericalContext, used map[string]bool) *numericalContextView {
	if context == nil {
		return nil
	}
	neededVariables := map[string]bool{}
	neededRelations := map[string]bool{}
	for _, variable := range context.Variables {
		if used[variable.VariableID] {
			neededVariables[variable.VariableID] = true
		}
	}
	for _, relation := range context.Relations {
		if used[relation.RelationID] {
			neededRelations[relation.RelationID] = true
			neededVariables[relation.LeftVariableID] = true
			neededVariables[relation.RightVariableID] = true
		}
	}
	if len(neededVariables)+len(neededRelations) == 0 {
		return nil
	}
	view := &numericalContextView{Version: context.Version}
	for _, variable := range context.Variables {
		if neededVariables[variable.VariableID] {
			view.Variables = append(view.Variables, numericalVariableView{
				VariableID: variable.VariableID, EntityID: variable.EntityID, EntityLabel: variable.EntityLabel,
				MetricID: variable.MetricID, Period: variable.Period, Method: variable.Method,
				ReceiptRefs: append([]string(nil), variable.ReceiptRefs...), Warnings: append([]string(nil), variable.Warnings...),
			})
		}
	}
	for _, relation := range context.Relations {
		if neededRelations[relation.RelationID] {
			view.Relations = append(view.Relations, numericalRelationView{
				RelationID: relation.RelationID, MetricID: relation.MetricID,
				LeftVariableID: relation.LeftVariableID, Operator: relation.Operator,
				RightVariableID: relation.RightVariableID, Comparable: relation.Comparable,
				ReceiptRefs: append([]string(nil), relation.ReceiptRefs...), Warnings: append([]string(nil), relation.Warnings...),
			})
		}
	}
	return view
}

func appendNumericalDisclosures(sections []contracts.AnswerSection, packets []contracts.ContextPacket) error {
	contexts := make([]*contracts.NumericalContext, 0, len(packets))
	for index := range packets {
		if packets[index].NumericalContext != nil {
			contexts = append(contexts, packets[index].NumericalContext)
		}
	}
	for index := range sections {
		if len(sections[index].NumericalRefs) == 0 {
			continue
		}
		switch sections[index].SectionType {
		case "evidence", "assumptions", "limitations":
			continue
		}
		disclosures, err := numericalcontext.RenderReferences(sections[index].NumericalRefs, contexts)
		if err != nil {
			return fmt.Errorf("render numerical disclosures for section %q: %w", sections[index].SectionType, err)
		}
		if len(disclosures) > 0 {
			sections[index].Content = strings.TrimSpace(sections[index].Content) + "\n\nVerified numerical disclosure: " + strings.Join(disclosures, " ")
		}
	}
	return nil
}

func authorizeFinalReferences(answer contracts.FinalAnswer, packets []contracts.ContextPacket, critiques []contracts.CritiqueReport) error {
	if len(critiques) == 0 {
		return errors.New("final answer requires at least one critique")
	}
	approved := map[string]int{}
	rejected := map[string]bool{}
	for _, critique := range critiques {
		for _, claimID := range critique.ApprovedClaims {
			approved[claimID]++
		}
		for _, claimID := range critique.RejectedClaims {
			rejected[claimID] = true
		}
	}
	allowedEvidence := map[string]bool{}
	allowedReceipts := map[string]bool{}
	allowedNumerical := map[string]bool{}
	claimEvidence := map[string]map[string]bool{}
	claimReceipts := map[string]map[string]bool{}
	claimNumerical := map[string]map[string]bool{}
	for _, packet := range packets {
		for _, evidence := range packet.Evidence {
			allowedEvidence[evidence.EvidenceID] = true
		}
		for _, receipt := range packet.CalculationReceipts {
			allowedReceipts[receipt.ReceiptID] = true
		}
		if packet.NumericalContext != nil {
			for _, variable := range packet.NumericalContext.Variables {
				allowedNumerical[variable.VariableID] = true
			}
			for _, relation := range packet.NumericalContext.Relations {
				allowedNumerical[relation.RelationID] = true
			}
		}
		for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
			claimEvidence[finding.ClaimID] = stringSet(finding.EvidenceRefs)
			claimReceipts[finding.ClaimID] = stringSet(finding.CalculationRefs)
			claimNumerical[finding.ClaimID] = stringSet(finding.NumericalRefs)
		}
	}
	for _, section := range answer.Sections {
		for _, claimID := range section.ClaimRefs {
			if rejected[claimID] || approved[claimID] != len(critiques) {
				return fmt.Errorf("final answer used claim %q without unanimous review approval", claimID)
			}
		}
		for _, evidenceID := range section.EvidenceRefs {
			if !allowedEvidence[evidenceID] || !referenceSupportedByAnyClaim(evidenceID, section.ClaimRefs, claimEvidence) {
				return fmt.Errorf("section %q cannot use evidence %q", section.SectionType, evidenceID)
			}
		}
		for _, receiptID := range section.ReceiptRefs {
			if !allowedReceipts[receiptID] || !referenceSupportedByAnyClaim(receiptID, section.ClaimRefs, claimReceipts) {
				return fmt.Errorf("section %q cannot use receipt %q", section.SectionType, receiptID)
			}
		}
		for _, numericalID := range section.NumericalRefs {
			if !allowedNumerical[numericalID] || !referenceSupportedByAnyClaim(numericalID, section.ClaimRefs, claimNumerical) {
				return fmt.Errorf("section %q cannot use numerical reference %q", section.SectionType, numericalID)
			}
		}
		if len(section.ClaimRefs) == 0 && (len(section.EvidenceRefs) > 0 || len(section.ReceiptRefs) > 0 || len(section.NumericalRefs) > 0) {
			return errors.New("final section cannot cite evidence, receipts, or numerical items without claim references")
		}
	}
	return nil
}

func referenceSupportedByAnyClaim(reference string, claimIDs []string, authority map[string]map[string]bool) bool {
	for _, claimID := range claimIDs {
		if authority[claimID][reference] {
			return true
		}
	}
	return false
}

func stringSet(values []string) map[string]bool {
	result := make(map[string]bool, len(values))
	for _, value := range values {
		result[value] = true
	}
	return result
}

var _ orchestrator.Synthesizer = (*Adapters)(nil)
