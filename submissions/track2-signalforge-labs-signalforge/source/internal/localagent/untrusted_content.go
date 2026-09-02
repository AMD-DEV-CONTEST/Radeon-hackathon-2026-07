package localagent

import (
	"regexp"
	"strings"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

const quarantinedEvidenceStatement = "[Untrusted source instruction quarantined by SignalForge.]"

var untrustedInstructionPatterns = []struct {
	code    string
	pattern *regexp.Regexp
}{
	{"instruction_override", regexp.MustCompile(`(?i)\b(ignore|disregard|forget|override)\b.{0,48}\b(previous|prior|system|developer|assistant|instructions?|rules?|prompt)\b`)},
	{"role_impersonation", regexp.MustCompile(`(?i)(<\s*/?\s*(system|assistant|developer)\s*>|\[\s*inst\s*\]|###\s*(system|assistant|instruction)|\byou are (chatgpt|an ai assistant|the system)\b)`)},
	{"secret_exfiltration", regexp.MustCompile(`(?i)\b(reveal|print|return|send|exfiltrate|expose)\b.{0,64}\b(system prompt|api[_ -]?key|access token|password|secret|credentials?)\b`)},
	{"tool_execution", regexp.MustCompile(`(?i)\b(call|invoke|execute|run)\b.{0,40}\b(tool|function|shell|command|terminal|curl|wget)\b`)},
}

func untrustedInstructionCode(text string) string {
	text = strings.TrimSpace(text)
	if text == "" {
		return ""
	}
	for _, candidate := range untrustedInstructionPatterns {
		if candidate.pattern.MatchString(text) {
			return candidate.code
		}
	}
	return ""
}

func evidenceStateForModel(item contracts.EvidenceItem) contracts.EvidenceState {
	if untrustedInstructionCode(item.Statement) != "" {
		return contracts.EvidenceMissing
	}
	return item.State
}

func evidenceIsQuarantined(item contracts.EvidenceItem) bool {
	return untrustedInstructionCode(item.Statement) != ""
}

func quarantineEvidenceForPrompt(item *contracts.EvidenceItem) {
	code := untrustedInstructionCode(item.Statement)
	if code == "" {
		return
	}
	item.State = contracts.EvidenceMissing
	item.Statement = quarantinedEvidenceStatement
	item.ConflictRefs = nil
	item.Warnings = appendUnique(item.Warnings, "untrusted_source_instruction:"+code)
}
