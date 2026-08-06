// Package decision implements the Decision Protocol:
// LLM call interface (mockable), text scanner for directive phrasings,
// and evidence_pointers assembly.
package decision

import (
	"fmt"
	"regexp"
)

// ── Text Scanner ────────────────────────────────────────────────────
//
// The text scanner identifies directive phrasings in text and records
// them as evidence pointers for the Decision Protocol.

// DirectivePhrasing represents a detected directive statement.
type DirectivePhrasing struct {
	Phrase   string `json:"phrase"`    // the matched phrase (e.g., "必须")
	Category string `json:"category"`  // directive category
	Position int    `json:"position"`  // byte offset in text
	Sentence string `json:"sentence"`  // surrounding sentence context
}

// DirectiveCategory groups directive phrasings by intent.
type DirectiveCategory string

const (
	CatObligation  DirectiveCategory = "obligation"
	CatProhibition DirectiveCategory = "prohibition"
	CatUrgency     DirectiveCategory = "urgency"
)

// directiveRule defines a single directive detection rule.
type directiveRule struct {
	phrase   string
	category DirectiveCategory
	pattern  *regexp.Regexp
}

// scanner contains all directive detection rules.
type Scanner struct {
	rules []directiveRule
}

// NewScanner creates a scanner with the 10 standard directive phrasings.
func NewScanner() *Scanner {
	phrasings := []struct {
		phrase   string
		category DirectiveCategory
	}{
		{"必须", CatObligation},
		{"应该", CatUrgency},
		{"立即", CatUrgency},
		{"禁止", CatProhibition},
		{"不准", CatProhibition},
		{"务必", CatObligation},
		{"强制", CatObligation},
		{"确保", CatObligation},
		{"不得", CatProhibition},
		{"严禁", CatProhibition},
	}

	rules := make([]directiveRule, len(phrasings))
	for i, p := range phrasings {
		rules[i] = directiveRule{
			phrase:   p.phrase,
			category: p.category,
			pattern:  regexp.MustCompile(regexp.QuoteMeta(p.phrase)),
		}
	}
	return &Scanner{rules: rules}
}

// Scan scans text for directive phrasings and returns all matches.
func (s *Scanner) Scan(text string) []DirectivePhrasing {
	var results []DirectivePhrasing

	for _, rule := range s.rules {
		matches := rule.pattern.FindAllStringIndex(text, -1)
		for _, m := range matches {
			sentence := extractSentence(text, m[0])
			results = append(results, DirectivePhrasing{
				Phrase:   rule.phrase,
				Category: string(rule.category),
				Position: m[0],
				Sentence: sentence,
			})
		}
	}

	if results == nil {
		return []DirectivePhrasing{}
	}
	return results
}

// ScanAllRules returns a map of category -> []phrase for all defined rules.
func (s *Scanner) ScanAllRules() map[string][]string {
	result := make(map[string][]string)
	for _, rule := range s.rules {
		cat := string(rule.category)
		result[cat] = append(result[cat], rule.phrase)
	}
	return result
}

// ── extractSentence ─────────────────────────────────────────────────

// extractSentence extracts the sentence containing position pos in text.
// Uses rune-based iteration to handle multi-byte Chinese characters.
func extractSentence(text string, pos int) string {
	if pos < 0 || pos >= len(text) {
		return ""
	}

	runes := []rune(text)
	runePos := 0
	for i, r := range runes {
		if pos < i+len(string(r)) {
			runePos = i
			break
		}
	}

	// Walk backward to find sentence start
	start := runePos
	for start > 0 {
		c := runes[start-1]
		if c == 12290 || c == 65281 || c == 65311 || c == 10 || c == '.' || c == '!' || c == '?' {
			break
		}
		start--
	}

	// Walk forward to find sentence end
	end := runePos
	for end < len(runes) {
		c := runes[end]
		if c == 12290 || c == 65281 || c == 65311 || c == 10 || c == '.' || c == '!' || c == '?' {
			end++
			break
		}
		end++
	}

	if start >= end {
		result := string(runes[runePos:min(runePos+20, len(runes))])
		return result
	}

	result := string(runes[start:end])
	if len([]rune(result)) > 120 {
		rs := []rune(result)
		result = string(rs[:120]) + "..."
	}
	return result
}

// ── Evidence Pointer ────────────────────────────────────────────────

// EvidencePointer records a specific evidence item for decision support.
type EvidencePointer struct {
	Source    string `json:"source"`    // where the evidence was found
	Directive string `json:"directive"` // the directive phrase
	Context   string `json:"context"`   // surrounding context
	Severity  string `json:"severity"`  // info | warning | critical
}

// EvidenceCollector collects evidence pointers during decision processing.
type EvidenceCollector struct {
	pointers []EvidencePointer
}

func NewEvidenceCollector() *EvidenceCollector {
	return &EvidenceCollector{pointers: make([]EvidencePointer, 0)}
}

func (ec *EvidenceCollector) Add(source, directive, context, severity string) {
	ec.pointers = append(ec.pointers, EvidencePointer{
		Source:    source,
		Directive: directive,
		Context:   context,
		Severity:  severity,
	})
}

func (ec *EvidenceCollector) Pointers() []EvidencePointer {
	result := make([]EvidencePointer, len(ec.pointers))
	copy(result, ec.pointers)
	return result
}

func (ec *EvidenceCollector) HasDirectives() bool {
	return len(ec.pointers) > 0
}

// ── LLM Call Interface (mockable) ──────────────────────────────────

// LLMRequest represents a request to an LLM.
type LLMRequest struct {
	Prompt    string `json:"prompt"`
	Context   string `json:"context,omitempty"`
	MaxTokens int    `json:"max_tokens,omitempty"`
}

// LLMResponse represents a response from an LLM.
type LLMResponse struct {
	Text       string `json:"text"`
	Model      string `json:"model,omitempty"`
	TokenCount int    `json:"token_count,omitempty"`
}

// LLMClient is the interface for making LLM calls (mockable).
type LLMClient interface {
	Complete(req *LLMRequest) (*LLMResponse, error)
}

// ── Decision Engine ─────────────────────────────────────────────────

// DecisionOutput is the final output of the decision protocol.
type DecisionOutput struct {
	Summary          string              `json:"summary"`
	DirectivesFound  []DirectivePhrasing `json:"directives_found"`
	EvidencePointers []EvidencePointer   `json:"evidence_pointers"`
	Decision         string              `json:"decision"` // user must decide; we say "analysis_complete"
}

// ProcessDecision runs the full decision pipeline:
// 1. Scan text for directive phrasings
// 2. Collect evidence pointers
// 3. Return structured output (does NOT make the decision)
func ProcessDecision(text string, scanner *Scanner, collector *EvidenceCollector) *DecisionOutput {
	directives := scanner.Scan(text)

	for _, d := range directives {
		severity := "info"
		switch DirectiveCategory(d.Category) {
		case CatObligation:
			severity = "warning"
		case CatProhibition:
			severity = "critical"
		case CatUrgency:
			severity = "warning"
		}
		collector.Add(fmt.Sprintf("text-scanner@pos-%d", d.Position), d.Phrase, d.Sentence, severity)
	}

	return &DecisionOutput{
		Summary:          fmt.Sprintf("Scanned %d chars, found %d directive phrasings", len(text), len(directives)),
		DirectivesFound:  directives,
		EvidencePointers: collector.Pointers(),
		Decision:         "analysis_complete",
	}
}

// ── Mock LLM Client ─────────────────────────────────────────────────

// MockLLMClient is a mock LLM implementation for testing.
type MockLLMClient struct {
	Response *LLMResponse
	Err      error
}

func NewMockLLMClient(response string) *MockLLMClient {
	return &MockLLMClient{
		Response: &LLMResponse{Text: response, Model: "mock", TokenCount: len(response)},
	}
}

func (m *MockLLMClient) Complete(req *LLMRequest) (*LLMResponse, error) {
	if m.Err != nil {
		return nil, m.Err
	}
	return m.Response, nil
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
