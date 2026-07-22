package localagent

func interpreterSchema() map[string]any {
	intents := []string{"company_understanding", "financial_quality", "economic_transmission", "valuation", "company_comparison", "concept_education", "market_behavior", "thesis_review"}
	entity := strictObject(map[string]any{
		"entity_type": stringEnum("company"), "entity_id": stringSchema(),
		"mention": stringSchema(), "resolved": boolSchema(),
	}, "entity_type", "entity_id", "mention", "resolved")
	period := strictObject(map[string]any{
		"kind": stringSchema(), "lookback_years": integerSchema(0, 20),
		"fiscal_years": arraySchema(integerSchema(1900, 2200)), "fiscal_periods": stringArraySchema(),
	}, "kind", "lookback_years", "fiscal_years", "fiscal_periods")
	comparison := strictObject(map[string]any{
		"mode":       stringEnum("none", "peer", "benchmark"),
		"entity_ids": stringArraySchema(), "metrics": stringArraySchema(),
	}, "mode", "entity_ids", "metrics")
	return strictObject(map[string]any{
		"primary_intent": stringEnum(intents...), "secondary_intents": arraySchema(stringEnum(intents...)),
		"entities": arraySchema(entity), "period": period, "comparison": comparison,
		"answer_depth": stringEnum("brief", "standard", "deep"), "requested_outputs": stringArraySchema(),
		"assumptions": stringArraySchema(), "ambiguities": stringArraySchema(), "risk_flags": stringArraySchema(),
	}, "primary_intent", "secondary_intents", "entities", "period", "comparison", "answer_depth", "requested_outputs", "assumptions", "ambiguities", "risk_flags")
}

func planSchema() map[string]any {
	step := strictObject(map[string]any{
		"step_id": stringSchema(), "kind": stringEnum("context", "review", "synthesis"),
		"objective": stringSchema(), "role_id": stringSchema(), "capability_ids": stringArraySchema(),
		"evidence_requirements": stringArraySchema(), "depends_on": stringArraySchema(),
		"mandatory": boolSchema(), "context_budget_tokens": integerSchema(1, 7000),
		"timeout_ms": integerSchema(1, 120000),
	}, "step_id", "kind", "objective", "role_id", "capability_ids", "evidence_requirements", "depends_on", "mandatory", "context_budget_tokens", "timeout_ms")
	return strictObject(map[string]any{
		"steps": arraySchema(step), "max_parallel_specialists": integerSchema(1, 4),
		"max_repair_passes": integerSchema(0, 1), "deadline_ms": integerSchema(1, 120000),
		"completion_conditions": stringArraySchema(), "abstention_conditions": stringArraySchema(),
	}, "steps", "max_parallel_specialists", "max_repair_passes", "deadline_ms", "completion_conditions", "abstention_conditions")
}

func packetSchema() map[string]any {
	return packetSchemaWithArrays(arraySchema, arraySchema)
}

func boundedPacketSchema(maxFindings, maxCounterevidence int) map[string]any {
	return packetSchemaWithArrays(
		func(items map[string]any) map[string]any { return boundedArraySchema(items, maxFindings) },
		func(items map[string]any) map[string]any { return boundedArraySchema(items, maxCounterevidence) },
	)
}

func packetSchemaWithArrays(
	findingsArray func(map[string]any) map[string]any,
	counterevidenceArray func(map[string]any) map[string]any,
) map[string]any {
	finding := strictObject(map[string]any{
		"claim_id": stringSchema(), "claim_type": stringEnum("fact", "calculation", "inference", "hypothesis"),
		"statement": stringSchema(), "evidence_refs": stringArraySchema(),
		"calculation_refs": stringArraySchema(), "numerical_refs": stringArraySchema(), "assumption_refs": stringArraySchema(),
		"confidence": numberSchema(0, 1),
	}, "claim_id", "claim_type", "statement", "evidence_refs", "calculation_refs", "numerical_refs", "assumption_refs", "confidence")
	return strictObject(map[string]any{
		"findings": findingsArray(finding), "counterevidence": counterevidenceArray(finding),
		"assumptions": stringArraySchema(), "missing_evidence": stringArraySchema(),
		"conflicts": stringArraySchema(), "uncertainties": stringArraySchema(), "handoff_notes": stringArraySchema(),
	}, "findings", "counterevidence", "assumptions", "missing_evidence", "conflicts", "uncertainties", "handoff_notes")
}

func critiqueSchema() map[string]any {
	issue := strictObject(map[string]any{
		"issue_id": stringSchema(), "severity": stringEnum("low", "medium", "high", "critical"),
		"claim_refs": stringArraySchema(), "description": stringSchema(), "repair_hint": stringSchema(),
	}, "issue_id", "severity", "claim_refs", "description", "repair_hint")
	return strictObject(map[string]any{
		"decision":        stringEnum("approve", "repair", "narrow", "reject"),
		"approved_claims": stringArraySchema(), "rejected_claims": stringArraySchema(),
		"issues": arraySchema(issue),
	}, "decision", "approved_claims", "rejected_claims", "issues")
}

func finalSchema() map[string]any {
	sectionTypes := []string{
		"business_overview", "financial_quality", "transmission_mechanisms", "scenarios", "assumptions",
		"valuation_range", "sensitivity", "comparison", "concept", "company_example", "market_measurement",
		"thesis", "counterevidence", "invalidation_conditions", "evidence", "limitations",
	}
	return finalSchemaWithSectionTypes(sectionTypes, 0)
}

func finalSchemaForOutputs(sectionTypes, claimIDs []string) map[string]any {
	return finalSchemaWithAuthority(sectionTypes, claimIDs, len(sectionTypes))
}

func finalSchemaWithSectionTypes(sectionTypes []string, exactCount int) map[string]any {
	return finalSchemaWithAuthority(sectionTypes, nil, exactCount)
}

func finalSchemaWithAuthority(sectionTypes, claimIDs []string, exactCount int) map[string]any {
	claimRefSchema := stringSchema()
	if len(claimIDs) > 0 {
		claimRefSchema = stringEnum(claimIDs...)
	}
	section := strictObject(map[string]any{
		"section_type": stringEnum(sectionTypes...), "title": boundedStringSchema(80), "content": boundedStringSchema(650),
		"claim_refs": boundedArraySchema(claimRefSchema, 8),
	}, "section_type", "title", "content", "claim_refs")
	sections := boundedArraySchema(section, 8)
	if exactCount > 0 {
		sections["minItems"] = exactCount
		sections["maxItems"] = exactCount
	}
	return strictObject(map[string]any{
		"sections": sections, "assumptions": boundedArraySchema(boundedStringSchema(180), 4),
		"limitations": boundedArraySchema(boundedStringSchema(180), 4), "next_actions": boundedArraySchema(boundedStringSchema(180), 4),
	}, "sections", "assumptions", "limitations", "next_actions")
}

func strictObject(properties map[string]any, required ...string) map[string]any {
	return map[string]any{"type": "object", "additionalProperties": false, "properties": properties, "required": required}
}

func arraySchema(items map[string]any) map[string]any {
	return map[string]any{"type": "array", "items": items}
}

func boundedArraySchema(items map[string]any, maximum int) map[string]any {
	return map[string]any{"type": "array", "items": items, "maxItems": maximum}
}

func stringArraySchema() map[string]any { return arraySchema(stringSchema()) }

func stringSchema() map[string]any { return map[string]any{"type": "string"} }

func boundedStringSchema(maximum int) map[string]any {
	return map[string]any{"type": "string", "maxLength": maximum}
}

func stringEnum(values ...string) map[string]any {
	return map[string]any{"type": "string", "enum": values}
}

func boolSchema() map[string]any { return map[string]any{"type": "boolean"} }

func integerSchema(minimum, maximum int) map[string]any {
	return map[string]any{"type": "integer", "minimum": minimum, "maximum": maximum}
}

func numberSchema(minimum, maximum float64) map[string]any {
	return map[string]any{"type": "number", "minimum": minimum, "maximum": maximum}
}
