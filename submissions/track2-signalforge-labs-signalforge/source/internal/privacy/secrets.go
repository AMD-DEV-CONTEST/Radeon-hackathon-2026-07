package privacy

import "regexp"

var secretPatterns = []*regexp.Regexp{
	regexp.MustCompile(`(?i)\bbearer\s+[a-z0-9._~+/=-]{16,}`),
	regexp.MustCompile(`(?i)\bapi[_-]?key\s*[:=]\s*[^\s,;]{8,}`),
	regexp.MustCompile(`(?i)\b(?:password|secret)\s*[:=]\s*[^\s,;]{8,}`),
	regexp.MustCompile(`\bhf_[A-Za-z0-9]{20,}\b`),
	regexp.MustCompile(`\bsk-[A-Za-z0-9_-]{20,}\b`),
	regexp.MustCompile(`\bgithub_pat_[A-Za-z0-9_]{20,}\b`),
}

func ContainsSecret(payload []byte) bool {
	for _, pattern := range secretPatterns {
		if pattern.Match(payload) {
			return true
		}
	}
	return false
}
