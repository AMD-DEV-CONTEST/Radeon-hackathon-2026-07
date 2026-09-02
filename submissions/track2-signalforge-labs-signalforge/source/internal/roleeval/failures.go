package roleeval

import "strings"

const (
	FailureTimeout                = "timeout"
	FailureSchemaInvalid          = "schema_invalid"
	FailureInventedEvidence       = "invented_evidence"
	FailureInventedReceipt        = "invented_receipt"
	FailureUnapprovedClaimRelease = "unapproved_claim_release"
	FailureRouting                = "routing_error"
	FailureIncompletePacket       = "incomplete_packet"
	FailureUnsupportedCitation    = "unsupported_citation"
	FailureNumericalInconsistency = "numerical_inconsistency"
	FailureContradictionUnhandled = "contradiction_unhandled"
	FailureAuthorityBoundary      = "authority_boundary_violation"
	FailureContractInvalid        = "contract_invalid"
	FailureUnknown                = "unclassified_failure"
)

func classifyFailure(observation Observation) string {
	lower := strings.ToLower(observation.Error)
	switch {
	case strings.Contains(lower, "deadline exceeded"), strings.Contains(lower, "timeout"):
		return FailureTimeout
	case strings.Contains(lower, "invented") && strings.Contains(lower, "evidence"):
		return FailureInventedEvidence
	case strings.Contains(lower, "invented") && strings.Contains(lower, "receipt"):
		return FailureInventedReceipt
	case strings.Contains(lower, "without unanimous review approval"), strings.Contains(lower, "unapproved"):
		return FailureUnapprovedClaimRelease
	case strings.Contains(lower, "decode"), strings.Contains(lower, "json"), strings.Contains(lower, "unknown field"):
		return FailureSchemaInvalid
	case observation.Metrics.ContractValid < 1:
		return FailureContractInvalid
	case observation.Metrics.RoutingCorrect < 1:
		return FailureRouting
	case observation.Metrics.PacketComplete < 1:
		return FailureIncompletePacket
	case observation.Metrics.CitationSupport < 1:
		return FailureUnsupportedCitation
	case observation.Metrics.NumericalConsistency < 1:
		return FailureNumericalInconsistency
	case observation.Metrics.ContradictionHandling < 1:
		return FailureContradictionUnhandled
	case observation.Metrics.BoundaryCompliance < 1:
		return FailureAuthorityBoundary
	default:
		return FailureUnknown
	}
}
