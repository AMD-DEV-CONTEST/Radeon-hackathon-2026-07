package localagent

import (
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/rvbernucci/signalforge/internal/roles"
)

var numericalLiteralPattern = regexp.MustCompile(`[0-9]+(?:[.,][0-9]+)*%?`)
var numericalWordPattern = regexp.MustCompile(`(?i)\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|trillion|single|double|triple|half|quarter)\b`)
var singleEvidenceArtifactPattern = regexp.MustCompile(`(?i)\b(?:single|one)\s+(?:provided\s+)?(?:(?:held[- ]out|retrieved)\s+)?(?:evidence(?:\s+source)?|source|fixture|document)\b`)
var rawInternalReferenceTokenPattern = regexp.MustCompile(`(?i)\b(?:claim|evidence|receipt|numvar)[-_][a-z0-9][a-z0-9_.:-]*\b`)
var authorityOnlyParentheticalPattern = regexp.MustCompile(
	`(?i)\s*\(\s*(?:(?:the approved claim|the approved evidence|the validated calculation receipt|` +
		`the validated numerical reference)\s*(?:,\s*)?)+\)?`,
)
var repeatedHorizontalWhitespacePattern = regexp.MustCompile(`[ \t]{2,}`)
var internalRoleDisplayLabels = map[string]string{
	roles.RequestInterpreter:    "request interpretation",
	roles.ResearchOrchestrator:  "research orchestration",
	roles.BusinessStrategy:      "business strategy",
	roles.AccountingReporting:   "accounting and reporting",
	roles.FinancialQuality:      "financial quality",
	roles.EconomicsTransmission: "economic transmission",
	roles.Valuation:             "valuation",
	roles.MarketBehavior:        "market behavior",
	roles.RiskContrarian:        "contrarian risk review",
	roles.EvidenceCritic:        "evidence review",
	roles.FinalResearchAnalyst:  "final research synthesis",
}

func containsAuthoritativeNumericalLiteral(value string) bool {
	if numericalWordPattern.MatchString(value) {
		return true
	}
	for _, token := range numericalLiteralPattern.FindAllString(value, -1) {
		if allowedCalendarYear(token) {
			continue
		}
		return true
	}
	return false
}

func redactFinancialNumerics(value string) string {
	value = neutralizeKnownRoleIDs(value)
	redacted := numericalLiteralPattern.ReplaceAllStringFunc(value, func(token string) string {
		if allowedCalendarYear(token) {
			return token
		}
		return "[value withheld]"
	})
	return numericalWordPattern.ReplaceAllString(redacted, "[value withheld]")
}

func allowedCalendarYear(token string) bool {
	if len(token) != 4 || strings.ContainsAny(token, ".,%") {
		return false
	}
	year, err := strconv.Atoi(token)
	return err == nil && year >= 1900 && year <= 2200
}

func validateNumericallySilentDraft(body finalBody) error {
	for _, section := range body.Sections {
		if containsAuthoritativeNumericalLiteral(section.Title) || containsAuthoritativeNumericalLiteral(section.Content) {
			return fmt.Errorf("section %q crossed the numerical-silence boundary", section.SectionType)
		}
	}
	for _, group := range [][]string{body.Assumptions, body.Limitations, body.NextActions} {
		for _, value := range group {
			if containsAuthoritativeNumericalLiteral(value) {
				return fmt.Errorf("final semantic metadata crossed the numerical-silence boundary")
			}
		}
	}
	return nil
}

// repairAuthorizedNumericalDraft is a deterministic recovery at the model/application boundary.
// It may remove model-authored numerical sentences only from sections whose claim references
// resolve to approved deterministic authority. Unknown numbers, numerical metadata, and sections
// without such authority still fail closed.
func repairAuthorizedNumericalDraft(body *finalBody, material synthesisPromptInput) error {
	numericallyAuthorized := map[string]bool{}
	for _, claim := range material.Claims {
		if len(claim.Finding.CalculationRefs) > 0 || len(claim.Finding.NumericalRefs) > 0 {
			numericallyAuthorized[claim.Finding.ClaimID] = true
		}
	}
	for _, value := range body.Assumptions {
		if containsAuthoritativeNumericalLiteral(value) {
			return fmt.Errorf("numerical request assumption has no deterministic rendering boundary")
		}
	}
	body.Limitations = removeNumericalMetadata(body.Limitations)
	if len(body.Limitations) == 0 {
		body.Limitations = []string{
			"The analysis remains bounded by available source authority, validated calculations, and the stated as-of date.",
		}
	}
	body.NextActions = removeNumericalMetadata(body.NextActions)
	for index := range body.Sections {
		section := &body.Sections[index]
		if !containsAuthoritativeNumericalLiteral(section.Title) &&
			!containsAuthoritativeNumericalLiteral(section.Content) {
			continue
		}
		authorized := false
		hasApprovedClaim := false
		for _, claimID := range section.ClaimRefs {
			for _, claim := range material.Claims {
				if claim.Finding.ClaimID == claimID {
					hasApprovedClaim = true
					break
				}
			}
			if numericallyAuthorized[claimID] {
				authorized = true
				break
			}
		}
		// Once a section is attached to an approved claim, deleting every numerical sentence can
		// only narrow its authority. The trusted renderer remains the sole path for quantities in
		// every section, including business, financial, comparison, and valuation prose. A section
		// without an approved claim still fails closed because its number has no semantic boundary.
		if hasApprovedClaim {
			authorized = true
		}
		if !authorized {
			return fmt.Errorf("section %q has numerical prose without deterministic authority", section.SectionType)
		}
		if containsAuthoritativeNumericalLiteral(section.Title) {
			section.Title = titleFromSectionType(section.SectionType)
		}
		kept := make([]string, 0)
		for _, sentence := range semanticSentenceFragmentPattern.FindAllString(section.Content, -1) {
			sentence = strings.TrimSpace(sentence)
			if sentence != "" && !containsAuthoritativeNumericalLiteral(sentence) {
				kept = append(kept, sentence)
			}
		}
		section.Content = strings.TrimSpace(strings.Join(kept, " "))
		if section.Content == "" {
			section.Content = "Approved evidence and validated calculation lineage support this section; verified quantities are rendered deterministically below."
		}
	}
	return nil
}

func removeNumericalMetadata(values []string) []string {
	kept := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value != "" && !containsAuthoritativeNumericalLiteral(value) {
			kept = append(kept, value)
		}
	}
	return kept
}

func titleFromSectionType(sectionType string) string {
	words := strings.Fields(strings.ReplaceAll(strings.TrimSpace(sectionType), "_", " "))
	for index := range words {
		if words[index] != "" {
			words[index] = strings.ToUpper(words[index][:1]) + words[index][1:]
		}
	}
	return strings.Join(words, " ")
}

// Internal identifiers already travel through structured reference fields. Repeating them in
// user-facing prose adds no authority and can make their numeric suffixes look like financial
// values to the numerical-silence guard. Only identifiers present in the approved synthesis
// material are replaced; arbitrary numbers and unknown identifiers remain untouched.
func neutralizeInternalReferenceMentions(body *finalBody, material synthesisPromptInput) {
	replacements := make(map[string]string, len(internalRoleDisplayLabels))
	for identifier, label := range internalRoleDisplayLabels {
		replacements[identifier] = label
	}
	for _, claim := range material.Claims {
		replacements[claim.Finding.ClaimID] = "the approved claim"
		for _, evidenceID := range claim.Finding.EvidenceRefs {
			replacements[evidenceID] = "the approved evidence"
		}
		for _, receiptID := range claim.Finding.CalculationRefs {
			replacements[receiptID] = "the validated calculation receipt"
		}
		for _, numericalID := range claim.Finding.NumericalRefs {
			replacements[numericalID] = "the validated numerical reference"
		}
	}
	for _, evidence := range material.Evidence {
		replacements[evidence.EvidenceID] = "the approved evidence"
	}
	for _, receipt := range material.Receipts {
		replacements[receipt.ReceiptID] = "the validated calculation receipt"
	}

	identifiers := make([]string, 0, len(replacements))
	for identifier := range replacements {
		if strings.TrimSpace(identifier) != "" {
			identifiers = append(identifiers, identifier)
		}
	}
	sort.Slice(identifiers, func(i, j int) bool {
		return len(identifiers[i]) > len(identifiers[j])
	})

	replace := func(value string) string {
		for _, identifier := range identifiers {
			pattern := regexp.MustCompile(`(?i)\b` + regexp.QuoteMeta(identifier) + `\b`)
			value = pattern.ReplaceAllString(value, replacements[identifier])
		}
		value = rawInternalReferenceTokenPattern.ReplaceAllStringFunc(value, func(identifier string) string {
			switch {
			case strings.HasPrefix(strings.ToLower(identifier), "claim"):
				return "the approved claim"
			case strings.HasPrefix(strings.ToLower(identifier), "evidence"):
				return "the approved evidence"
			case strings.HasPrefix(strings.ToLower(identifier), "receipt"):
				return "the validated calculation receipt"
			default:
				return "the validated numerical reference"
			}
		})
		value = authorityOnlyParentheticalPattern.ReplaceAllString(value, "")
		value = repeatedHorizontalWhitespacePattern.ReplaceAllString(value, " ")
		if len(material.Evidence) == 1 {
			value = singleEvidenceArtifactPattern.ReplaceAllString(value, "provided evidence set")
		}
		return value
	}
	for index := range body.Sections {
		body.Sections[index].Title = replace(body.Sections[index].Title)
		body.Sections[index].Content = replace(body.Sections[index].Content)
	}
	for _, group := range [][]string{body.Assumptions, body.Limitations, body.NextActions} {
		for index := range group {
			group[index] = replace(group[index])
		}
	}
}

func neutralizeKnownRoleIDs(value string) string {
	identifiers := make([]string, 0, len(internalRoleDisplayLabels))
	for identifier := range internalRoleDisplayLabels {
		identifiers = append(identifiers, identifier)
	}
	sort.Slice(identifiers, func(i, j int) bool {
		return len(identifiers[i]) > len(identifiers[j])
	})
	for _, identifier := range identifiers {
		pattern := regexp.MustCompile(`(?i)\b` + regexp.QuoteMeta(identifier) + `\b`)
		value = pattern.ReplaceAllString(value, internalRoleDisplayLabels[identifier])
	}
	return value
}
