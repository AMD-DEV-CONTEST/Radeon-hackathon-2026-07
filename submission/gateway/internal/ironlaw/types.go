package ironlaw

import "time"

type AmbiguityFlag struct {
	Type       string `json:"type"`
	Span       string `json:"span"`
	Suggestion string `json:"suggestion"`
}

type SimilarCase struct {
	CaseID     string  `json:"case_id"`
	Title      string  `json:"title"`
	Similarity float64 `json:"similarity"`
	Category   string  `json:"category"`
	Summary    string  `json:"summary"`
}

type EnrichmentPacket struct {
	RawText        string          `json:"raw_text"`
	UserID         string          `json:"user_id"`
	EnrichedAt     string          `json:"enriched_at"`
	SimilarCases   []SimilarCase   `json:"similar_cases"`
	PriorFailures  []string        `json:"prior_failures"`
	AmbiguityFlags []AmbiguityFlag `json:"ambiguity_flags"`
	RiskLevel      string          `json:"risk_level"`
	RiskReasons    []string        `json:"risk_reasons"`
	IsCompound     bool            `json:"is_compound"`
	CompoundParts  []string        `json:"compound_parts"`
	HermesGuidance string          `json:"hermes_guidance"`
	Project        string          `json:"project"`
	ProcessingMs   float64         `json:"processing_ms"`
}

type EnrichRequest struct {
	RawText string `json:"raw_text"`
	UserID  string `json:"user_id"`
	Project string `json:"project,omitempty"`
}

type EnrichResponse struct {
	Enriched        bool            `json:"enriched"`
	SimilarCases    []SimilarCase   `json:"similar_cases"`
	AmbiguityFlags  []AmbiguityFlag `json:"ambiguity_flags"`
	RiskLevel       string          `json:"risk_level"`
	RiskReasons     []string        `json:"risk_reasons"`
	HermesGuidance  string          `json:"hermes_guidance"`
	ProcessingMs    float64         `json:"processing_ms"`
}

type RuleViolation struct {
	Rule        int    `json:"rule"`
	Message     string `json:"message"`
	AutoFixable bool   `json:"auto_fixable"`
}

func (e *RuleViolation) Error() string {
	return e.Message
}

type taskPayload struct {
	Context        *taskContext `json:"context,omitempty"`
	EstimatedHours *float64     `json:"estimated_hours,omitempty"`
}

type taskContext struct {
	Goal string `json:"goal"`
}

type acceptanceCheck struct {
	Type    string   `json:"type"`
	Command []string `json:"command"`
}

type taskDict struct {
	Title              string                 `json:"title"`
	Description        string                 `json:"description"`
	TaskType           string                 `json:"task_type"`
	Payload            taskPayload            `json:"payload"`
	AcceptanceCheck    *acceptanceCheck       `json:"acceptance_check,omitempty"`
	RequiredCaps       map[string]interface{} `json:"required_capabilities"`
	EstimatedHours     *float64               `json:"estimated_hours,omitempty"`
}

// timenow returns the current UTC time; extracted for testability.
var timenow = time.Now

// ragSearchFunc is the function signature for RAG search; extracted for testability.
var ragSearchFunc func(rawText string, topK int) ([]ragResult, error)

// ragResult is the raw search result from the RAG service.
type ragResult struct {
	Case struct {
		CaseID   string `json:"case_id"`
		Title    string `json:"title"`
		Category string `json:"category"`
		Content  struct {
			WhatWorked       string `json:"what_worked"`
			AcceptanceResult string `json:"acceptance_result"`
			Goal             string `json:"goal"`
		} `json:"content"`
	} `json:"case"`
	Similarity float64 `json:"similarity"`
}
