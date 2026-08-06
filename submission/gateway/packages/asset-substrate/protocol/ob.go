package protocol

import "github.com/konspace/unionagents-go/packages/asset-substrate/decision"

// SourceRef is a traceable reference to a data source in OB output.
type SourceRef struct {
	URI     string `json:"uri"`
	Type    string `json:"type"`
	Summary string `json:"summary"`
}

// OBOutput is the structured output sent to OB inbox.
type OBOutput struct {
	Title      string                    `json:"title"`
	Insight    string                    `json:"insight"`
	Memories   []SourceRef               `json:"memories"`
	Evidence   []decision.EvidencePointer `json:"evidence_pointers"`
	Directives int                       `json:"directive_count"`
	Decision   string                    `json:"decision"`
	LLMCost    int                       `json:"llm_token_cost"`
	AuditHash  string                    `json:"audit_chain_tip_hash"`
}
