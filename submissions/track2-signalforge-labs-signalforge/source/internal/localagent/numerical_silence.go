package localagent

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

var numericalLiteralPattern = regexp.MustCompile(`[0-9]+(?:[.,][0-9]+)*%?`)
var numericalWordPattern = regexp.MustCompile(`(?i)\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|trillion|single|double|triple|half|quarter)\b`)

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
