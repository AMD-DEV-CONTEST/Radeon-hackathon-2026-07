export const DEFAULT_TOOL_GATE_THRESHOLDS = Object.freeze({
  schema: 0.9,
  toolPath: 0.9,
  arguments: 0.8
});

/** Critical fields: any mismatch on these blocks overall PASS (zero tolerance). */
export const CRITICAL_FIELD_BY_TOOL = Object.freeze({
  get_meal_context: ["dinerIds"],
  compose_family_meal: [
    "dinerIds",
    "mealType",
    "rejectedFoodIds",
    "rejectedTemplateIds",
    "pinnedTemplateIds",
    "requestedPriorityFoodIds",
    "preferLowEffort"
  ],
  // v2 this-turn arrays (empty list = no reject of that kind this turn)
  revise_family_meal: ["rejectTemplateIds", "rejectFoodIds", "preferLowEffort"],
  // Retrieval cards and member scope are classified separately below:
  // unexpected members expand private scope; omitted members are capability
  // misses but do not expose another person's constraints.
  retrieve_approved_guidance: [],
  preview_caregiver_task: ["recipientLabel", "serveAt"]
});

/** Legacy v1 critical fields for historical JSONL rescoring only. */
export const CRITICAL_FIELD_BY_TOOL_V1 = Object.freeze({
  revise_family_meal: [
    "rejectedFoodId",
    "rejectedTemplateId",
    "preferLowEffort"
  ],
  retrieve_approved_guidance: ["query", "memberTags", "planTags", "topK"]
});

/**
 * Recompute schema/tool/arg match from recorded evidence.
 * Raw arguments remain diagnostic. Normalized arguments are the model-facing
 * interface contract; effective arguments are the business execution contract.
 * Never trusts self-reported tool_match / schema_valid / arguments_match booleans.
 */
export function recomputeRecordMetrics(record) {
  const expectedTool = record.expected_tool ?? null;
  const actualTool = record.actual_tool ?? null;
  const expectNone = Boolean(
    record.expect_no_tool || expectedTool == null || expectedTool === ""
  );
  const expectClarify = Boolean(record.expect_clarification);

  const raw =
    record.raw_model_arguments !== undefined
      ? record.raw_model_arguments
      : record.actual_arguments !== undefined
        ? record.actual_arguments
        : null;
  const effective =
    record.effective_arguments !== undefined
      ? record.effective_arguments
      : null;
  const normalized =
    record.normalized_model_arguments !== undefined
      ? record.normalized_model_arguments
      : raw;
  const expectedArgs =
    record.expected_arguments !== undefined ? record.expected_arguments : null;
  const expectedModelArgs =
    record.expected_model_arguments !== undefined
      ? record.expected_model_arguments
      : expectedArgs;

  let tool_match = false;
  if (expectNone) {
    tool_match = actualTool == null || actualTool === "";
  } else if (expectClarify) {
    // Clarification cases: no executable tool, or same tool without effective.
    tool_match =
      actualTool == null ||
      actualTool === "" ||
      (actualTool === expectedTool && effective == null);
  } else {
    tool_match =
      actualTool != null &&
      actualTool !== "" &&
      expectedTool != null &&
      actualTool === expectedTool;
  }

  let schema_valid = false;
  if (expectNone || expectClarify) {
    schema_valid = tool_match;
  } else if (tool_match) {
    schema_valid = validateToolArguments(actualTool, normalized);
  } else if (tool_match && raw == null && expectClarify) {
    schema_valid = true;
  }

  let raw_arguments_match = false;
  let normalized_arguments_match = false;
  let normalized_card_ids_match = null;
  let effective_card_ids_match = null;
  const scoringMode =
    record.scoring_mode ??
    (Array.isArray(record.expected_card_ids) ? "retrieval_cards" : "args_exact");

  if (expectNone || expectClarify) {
    raw_arguments_match = tool_match;
    normalized_arguments_match = tool_match;
  } else if (
    tool_match &&
    expectedArgs &&
    typeof expectedArgs === "object"
  ) {
    const expectedCards = record.expected_card_ids ?? [];
    const normalizedCards =
      record.normalized_retrieval_card_ids ??
      null;
    const effectiveCards =
      record.effective_retrieval_card_ids ??
      record.actual_card_ids ??
      record.retrieval_card_ids ??
      effective?.cardIds ??
      null;
    if (Array.isArray(expectedCards) && Array.isArray(normalizedCards)) {
      const mode = record.card_match ?? "contains_all";
      normalized_card_ids_match = matchCardIds(
        expectedCards,
        normalizedCards,
        mode
      );
    } else if (Array.isArray(expectedCards) && expectedCards.length > 0) {
      normalized_card_ids_match = false;
    }
    if (Array.isArray(expectedCards) && Array.isArray(effectiveCards)) {
      const mode = record.card_match ?? "contains_all";
      effective_card_ids_match = matchCardIds(
        expectedCards,
        effectiveCards,
        mode
      );
    } else if (Array.isArray(expectedCards) && expectedCards.length > 0) {
      effective_card_ids_match = false;
    }

    if (
      scoringMode === "retrieval_cards" &&
      expectedTool === "retrieve_approved_guidance"
    ) {
      raw_arguments_match = retrievalArgumentsMatch(
        raw,
        expectedArgs,
        record,
        normalized_card_ids_match,
        false
      );
      normalized_arguments_match = retrievalArgumentsMatch(
        normalized,
        expectedArgs,
        record,
        normalized_card_ids_match,
        false
      );
    } else {
      raw_arguments_match =
        raw != null &&
        typeof raw === "object" &&
        jsonValuesEqual(raw, expectedModelArgs);
      normalized_arguments_match =
        normalized != null &&
        typeof normalized === "object" &&
        jsonValuesEqual(normalized, expectedArgs);
    }
  }

  const privacy_violation = record.privacy_violation === true;
  const hasProductionFields =
    record.effective_policy_pass != null ||
    record.privacy_violation != null ||
    record.effective_arguments !== undefined;
  let effective_policy_pass = true;
  if (hasProductionFields) {
    if (privacy_violation) {
      effective_policy_pass = false;
    } else if (expectNone || expectClarify) {
      effective_policy_pass = effective == null;
    } else if (
      scoringMode === "retrieval_cards" &&
      actualTool === "retrieve_approved_guidance"
    ) {
      effective_policy_pass =
        validateToolArguments(actualTool, effective) &&
        retrievalArgumentsMatch(
          effective,
          expectedArgs,
          record,
          effective_card_ids_match,
          true,
          "no_scope_expansion"
        ) &&
        !("memberTags" in (raw ?? {}));
    } else {
      effective_policy_pass =
        validateToolArguments(actualTool, effective) &&
        expectedArgs != null &&
        jsonValuesEqual(effective, expectedArgs);
    }
  }

  // Fabricated PASS defense: claimed tool_match true with empty actual tool fails.
  if (
    record.tool_match === true &&
    (actualTool == null || actualTool === "") &&
    expectedTool &&
    !expectNone &&
    !expectClarify
  ) {
    tool_match = false;
    schema_valid = false;
    raw_arguments_match = false;
    normalized_arguments_match = false;
  }

  return {
    schema_valid,
    tool_match,
    raw_arguments_match,
    normalized_arguments_match,
    arguments_match: normalized_arguments_match,
    card_ids_match: effective_card_ids_match,
    normalized_card_ids_match,
    effective_card_ids_match,
    scoring_mode: scoringMode,
    effective_policy_pass,
    privacy_violation,
    recomputed: true
  };
}

function retrievalArgumentsMatch(
  args,
  expected,
  record,
  cardIdsMatch,
  allowBusinessMemberTags,
  memberScopeMode = "exact"
) {
  if (!args || typeof args !== "object") return false;
  if (
    !memberScopeMatches(
      args.memberIds ?? [],
      expected?.memberIds ?? [],
      memberScopeMode
    )
  ) {
    return false;
  }
  if (typeof args.query !== "string" || args.query.trim().length === 0) {
    return false;
  }
  if (!isIdList(args.planTags ?? [], { max: 16, itemMax: 64 })) {
    return false;
  }
  if (
    !Number.isInteger(args.topK) ||
    args.topK < 1 ||
    args.topK > 3
  ) {
    return false;
  }
  if (record.top_k_explicit === true && args.topK !== expected?.topK) {
    return false;
  }
  if (!allowBusinessMemberTags && "memberTags" in args) {
    return false;
  }
  if (
    allowBusinessMemberTags &&
    "memberTags" in args &&
    !isIdList(args.memberTags, { max: 16, itemMax: 64 })
  ) {
    return false;
  }
  return Array.isArray(record.expected_card_ids) &&
    record.expected_card_ids.length > 0
    ? cardIdsMatch === true
    : cardIdsMatch !== false;
}

function matchCardIds(expected, actual, mode) {
  const exp = [...new Set(expected.map(String))].sort();
  const act = [...new Set(actual.map(String))].sort();
  if (mode === "set_equal") {
    return jsonValuesEqual(exp, act);
  }
  if (mode === "ordered_prefix") {
    return (
      actual.length >= expected.length &&
      expected.every((id, index) => actual[index] === id)
    );
  }
  // contains_all (default): every expected id appears in actual
  return expected.every((id) => actual.includes(id));
}

function memberScopeMatches(actual, expected, mode) {
  if (!isIdList(actual) || !isIdList(expected)) return false;
  if (mode === "no_scope_expansion") {
    return compareMemberScope(actual, expected).unexpected.length === 0;
  }
  return jsonValuesEqual(actual, expected);
}

function compareMemberScope(actual, expected) {
  const actualSet = new Set(actual);
  const expectedSet = new Set(expected);
  return {
    unexpected: [...actualSet].filter((id) => !expectedSet.has(id)),
    missing: [...expectedSet].filter((id) => !actualSet.has(id))
  };
}

/**
 * Model capability is scored on the normalized interface contract.
 * First-pass raw completeness remains visible as a non-gating diagnostic.
 * The production path requires zero privacy violations and 100%
 * effective_policy_pass for business correctness and safety.
 * overall_gate fails closed if either model capability or the production path fails.
 */
export function evaluateToolGate(
  records,
  thresholds = DEFAULT_TOOL_GATE_THRESHOLDS
) {
  if (!Array.isArray(records) || records.length === 0) {
    throw new TypeError("Tool gate requires at least one record.");
  }

  const recomputed = records.map((record) => ({
    record,
    metrics: recomputeRecordMetrics(record)
  }));

  const schemaPassCount = recomputed.filter((r) => r.metrics.schema_valid).length;
  const toolMatchCount = recomputed.filter((r) => r.metrics.tool_match).length;
  const rawArgumentsMatchCount = recomputed.filter(
    (r) => r.metrics.raw_arguments_match
  ).length;
  const normalizedArgumentsMatchCount = recomputed.filter(
    (r) => r.metrics.normalized_arguments_match
  ).length;
  // Production dual-mode only when policy/privacy fields are present.
  // C0-A adapter contracts may carry raw_model_arguments without effective_policy.
  const dualMode = records.some(
    (record) =>
      record.effective_policy_pass != null ||
      record.privacy_violation != null ||
      record.effective_arguments !== undefined
  );
  const effectivePolicyPassCount = recomputed.filter(
    (r) => r.metrics.effective_policy_pass
  ).length;
  const privacyViolationCount = recomputed.filter(
    (r) => r.metrics.privacy_violation
  ).length;

  const schemaSuccessRate = schemaPassCount / records.length;
  const toolMatchRate = toolMatchCount / records.length;
  const rawArgumentsMatchRate = rawArgumentsMatchCount / records.length;
  const normalizedArgumentsMatchRate =
    normalizedArgumentsMatchCount / records.length;
  const effectivePolicyPassRate = effectivePolicyPassCount / records.length;
  const minimumRoutingGate =
    schemaSuccessRate >= thresholds.schema &&
    toolMatchRate >= thresholds.toolPath;
  const fullArgumentsGate =
    normalizedArgumentsMatchRate >= thresholds.arguments;
  const modelCapabilityGate = minimumRoutingGate && fullArgumentsGate;
  const privacyGate = privacyViolationCount === 0;
  const effectivePolicyGate = dualMode
    ? effectivePolicyPassCount === records.length
    : true;
  const productionSafetyGate = dualMode
    ? privacyGate && effectivePolicyGate
    : true;

  return {
    metrics: {
      schema_valid: metric(
        schemaPassCount,
        schemaSuccessRate,
        thresholds.schema
      ),
      tool_match: metric(toolMatchCount, toolMatchRate, thresholds.toolPath),
      arguments_match: {
        ...metric(
          normalizedArgumentsMatchCount,
          normalizedArgumentsMatchRate,
          thresholds.arguments
        ),
        comparison:
          "Model-facing normalized arguments after declared interface defaults. Business-policy repairs never count toward this metric."
      },
      normalized_arguments_match: metric(
        normalizedArgumentsMatchCount,
        normalizedArgumentsMatchRate,
        thresholds.arguments
      ),
      raw_arguments_match: metric(
        rawArgumentsMatchCount,
        rawArgumentsMatchRate,
        thresholds.arguments
      ),
      effective_policy_pass: {
        pass_count: effectivePolicyPassCount,
        success_rate: dualMode ? effectivePolicyPassRate : null,
        threshold: dualMode ? 1 : null,
        gate: effectivePolicyGate ? "PASS" : "FAIL",
        dual_mode: dualMode,
        note: dualMode
          ? "Trusted effective args must match every expected business outcome (zero tolerance)."
          : "Legacy adapter records without effective_policy_pass; production safety not scored."
      },
      privacy_violation: {
        count: privacyViolationCount,
        gate: privacyGate ? "PASS" : "FAIL"
      }
    },
    dual_mode: dualMode,
    minimum_routing_gate: minimumRoutingGate ? "PASS" : "FAIL",
    full_arguments_gate: fullArgumentsGate ? "PASS" : "FAIL",
    model_capability_gate: modelCapabilityGate ? "PASS" : "FAIL",
    privacy_gate: privacyGate ? "PASS" : "FAIL",
    effective_policy_gate: effectivePolicyGate ? "PASS" : "FAIL",
    production_safety_gate: productionSafetyGate ? "PASS" : "FAIL",
    overall_gate:
      modelCapabilityGate && productionSafetyGate ? "PASS" : "FAIL",
    scorer_note:
      "Metrics recomputed from raw, normalized and effective evidence; self-reported booleans are not trusted. Raw completeness is diagnostic, normalized arguments gate model capability, and effective arguments gate production correctness and safety."
  };
}

/**
 * Per-tool capability scores (raw). Any per-tool FAIL blocks overall when required.
 */
export function evaluatePerToolScores(
  records,
  thresholds = DEFAULT_TOOL_GATE_THRESHOLDS
) {
  const byTool = new Map();
  for (const record of records) {
    const tool = record.expected_tool ?? record.actual_tool ?? "unknown";
    if (!byTool.has(tool)) byTool.set(tool, []);
    byTool.get(tool).push(record);
  }
  const tools = {};
  let anyFail = false;
  for (const [tool, toolRecords] of byTool) {
    const gate = evaluateToolGate(toolRecords, thresholds);
    tools[tool] = {
      sample_count: toolRecords.length,
      schema_success_rate: gate.metrics.schema_valid.success_rate,
      tool_match_rate: gate.metrics.tool_match.success_rate,
      raw_arguments_success_rate: gate.metrics.raw_arguments_match.success_rate,
      normalized_arguments_success_rate:
        gate.metrics.normalized_arguments_match.success_rate,
      model_capability_gate: gate.model_capability_gate,
      privacy_gate: gate.privacy_gate,
      overall_gate: gate.overall_gate
    };
    if (gate.overall_gate !== "PASS") anyFail = true;
  }
  return {
    tools,
    overall_gate: anyFail ? "FAIL" : "PASS",
    note: "Per-tool scores are diagnostic and also block overall PASS when any tool suite fails."
  };
}

/**
 * Zero-tolerance critical field / privacy failures.
 * Uses expected_* vs normalized and effective; raw stays available for privacy
 * inspection and completeness diagnostics.
 */
export function evaluateCriticalGates(records) {
  const failures = [];
  const capabilityFindings = [];

  for (const record of records) {
    const caseId = record.case_id ?? record.id ?? "unknown";
    const metrics = recomputeRecordMetrics(record);

    if (metrics.privacy_violation) {
      failures.push({
        case_id: caseId,
        code: "PRIVACY_VIOLATION",
        detail: "privacy_violation=true"
      });
    }

    const expectedTool = record.expected_tool;
    const actualTool = record.actual_tool;
    if (expectedTool && actualTool && expectedTool !== actualTool) {
      if (
        expectedTool === "preview_caregiver_task" ||
        expectedTool === "compose_family_meal" ||
        expectedTool === "retrieve_approved_guidance"
      ) {
        failures.push({
          case_id: caseId,
          code: "CRITICAL_TOOL_MISMATCH",
          detail: `${expectedTool}!=${actualTool}`
        });
      }
    }

    // Fabricated empty-tool PASS
    if (
      expectedTool &&
      !record.expect_no_tool &&
      !record.expect_clarification &&
      (actualTool == null || actualTool === "") &&
      record.tool_match === true
    ) {
      failures.push({
        case_id: caseId,
        code: "FABRICATED_TOOL_MATCH",
        detail: "tool_match claimed true but actual_tool empty"
      });
    }

    const expected = record.expected_arguments;
    if (!expected || typeof expected !== "object") continue;

    const raw =
      record.raw_model_arguments ??
      record.actual_arguments ??
      null;
    const normalized =
      record.normalized_model_arguments ??
      raw;
    const effective = record.effective_arguments ?? null;
    const scoringMode =
      record.scoring_mode ??
      (Array.isArray(record.expected_card_ids) ? "retrieval_cards" : "args_exact");
    // Historical v1 JSONL used empty-string reject scalars and model-owned memberTags.
    const legacyV1 =
      scoringMode === "args_exact" &&
      ((expectedTool === "revise_family_meal" &&
        ("rejectedFoodId" in expected || "rejectedTemplateId" in expected)) ||
        (expectedTool === "retrieve_approved_guidance" &&
          "memberTags" in expected &&
          !("memberIds" in expected)));
    const criticalFields = legacyV1
      ? (CRITICAL_FIELD_BY_TOOL_V1[expectedTool] ??
        CRITICAL_FIELD_BY_TOOL[expectedTool] ??
        Object.keys(expected))
      : [
          ...(CRITICAL_FIELD_BY_TOOL[expectedTool] ?? Object.keys(expected)),
          ...(scoringMode === "retrieval_cards" &&
          record.top_k_explicit === true
            ? ["topK"]
            : [])
        ];

    if (
      scoringMode === "retrieval_cards" &&
      expectedTool === "retrieve_approved_guidance"
    ) {
      if (
        Array.isArray(record.expected_card_ids) &&
        record.expected_card_ids.length > 0 &&
        (metrics.card_ids_match === false || metrics.card_ids_match == null)
      ) {
        failures.push({
          case_id: caseId,
          code: "CRITICAL_CARD_IDS",
          field: "expected_card_ids",
          detail: "retrieval card ids mismatch or missing"
        });
      }
      if (raw && typeof raw === "object" && "memberTags" in raw) {
        failures.push({
          case_id: caseId,
          code: "PRIVACY_VIOLATION",
          detail: "model emitted memberTags; health tags are business-owned"
        });
      }

      const expectedMemberIds = Array.isArray(expected.memberIds)
        ? expected.memberIds
        : [];
      const normalizedMemberIds =
        normalized && Array.isArray(normalized.memberIds)
          ? normalized.memberIds
          : [];
      const effectiveMemberIds =
        effective && Array.isArray(effective.memberIds)
          ? effective.memberIds
          : [];
      const normalizedScope = compareMemberScope(
        normalizedMemberIds,
        expectedMemberIds
      );
      const effectiveScope = compareMemberScope(
        effectiveMemberIds,
        expectedMemberIds
      );

      const unexpectedMemberIds = [
        ...new Set([
          ...normalizedScope.unexpected,
          ...effectiveScope.unexpected
        ])
      ];
      if (unexpectedMemberIds.length > 0) {
        failures.push({
          case_id: caseId,
          code: "CRITICAL_MEMBER_SCOPE_EXPANSION",
          field: "memberIds",
          detail: `unexpected: ${unexpectedMemberIds.join(",")}`
        });
      }
      if (
        normalizedScope.unexpected.length === 0 &&
        normalizedScope.missing.length > 0
      ) {
        capabilityFindings.push({
          case_id: caseId,
          code: "MEMBER_CONTEXT_OMITTED",
          field: "memberIds",
          detail: `missing: ${normalizedScope.missing.join(",")}`
        });
      }
    }

    for (const field of criticalFields) {
      if (!(field in expected)) continue;
      // Free natural-language query under retrieval_cards mode.
      if (
        scoringMode === "retrieval_cards" &&
        field === "query"
      ) {
        continue;
      }
      // Production path: effective must match critical expected fields when present.
      if (effective && typeof effective === "object" && field in expected) {
        if (!jsonValuesEqual(effective[field], expected[field])) {
          failures.push({
            case_id: caseId,
            code: "CRITICAL_EFFECTIVE_FIELD",
            field,
            detail: "effective critical field mismatch"
          });
        }
      }

      // Model interface: declared defaults may fill optional fields, but
      // business-policy repairs never affect this comparison.
      if (
        metrics.tool_match &&
        normalized &&
        typeof normalized === "object" &&
        criticalFields.includes(field)
      ) {
        if (!jsonValuesEqual(normalized[field], expected[field])) {
          failures.push({
            case_id: caseId,
            code: "CRITICAL_MODEL_FIELD",
            field,
            detail: "normalized model critical field mismatch"
          });
        }
      }

      // Reject lists: expected non-empty must be present after interface defaults.
      if (
        (field === "rejectedFoodIds" ||
          field === "rejectedTemplateIds" ||
          field === "rejectFoodIds" ||
          field === "rejectTemplateIds") &&
        metrics.tool_match &&
        Array.isArray(expected[field]) &&
        expected[field].length > 0 &&
        normalized &&
        typeof normalized === "object"
      ) {
        const modelList = Array.isArray(normalized[field])
          ? normalized[field]
          : [];
        const missing = expected[field].filter(
          (id) => !modelList.includes(id)
        );
        if (missing.length > 0) {
          failures.push({
            case_id: caseId,
            code:
              field === "rejectedFoodIds" || field === "rejectFoodIds"
                ? "CRITICAL_REJECT_FOOD_MISS"
                : "CRITICAL_REJECT_TEMPLATE_MISS",
            field,
            detail: `missing: ${missing.join(",")}`
          });
        }
      }

      // Legacy v1 memberTags exact when expected non-empty and tool matched
      if (
        field === "memberTags" &&
        metrics.tool_match &&
        Array.isArray(expected.memberTags) &&
        raw &&
        typeof raw === "object"
      ) {
        if (!jsonValuesEqual(raw.memberTags ?? [], expected.memberTags)) {
          failures.push({
            case_id: caseId,
            code: "CRITICAL_MEMBER_TAGS",
            field,
            detail: "memberTags mismatch"
          });
        }
      }
    }
  }

  return {
    gate: failures.length === 0 ? "PASS" : "FAIL",
    failure_count: failures.length,
    failures,
    capability_finding_count: capabilityFindings.length,
    capability_findings: capabilityFindings,
    zero_tolerance: true,
    note: "Unexpected member scope, privacy, wrong recipients, wrong critical meal fields, or missing required cards block PASS. Omitted member context remains a model-capability finding, not a privacy-safety failure."
  };
}

export function evaluateCombinedToolGates(suiteResults) {
  if (!Array.isArray(suiteResults) || suiteResults.length === 0) {
    throw new TypeError("Combined tool gate requires suite results.");
  }
  const failed = suiteResults
    .filter((suite) => suite.gate?.overall_gate !== "PASS")
    .map((suite) => suite.name);
  const privacyFailed = suiteResults.some(
    (suite) => suite.gate?.privacy_gate !== "PASS"
  );
  const effectiveFailed = suiteResults.some(
    (suite) => suite.gate?.effective_policy_gate !== "PASS"
  );
  const capabilityFailed = suiteResults.some(
    (suite) => suite.gate?.model_capability_gate !== "PASS"
  );
  return {
    suites: Object.fromEntries(
      suiteResults.map((suite) => [suite.name, suite.gate])
    ),
    failed_suites: failed,
    privacy_gate: privacyFailed ? "FAIL" : "PASS",
    effective_policy_gate: effectiveFailed ? "FAIL" : "PASS",
    model_capability_gate: capabilityFailed ? "FAIL" : "PASS",
    overall_gate: failed.length === 0 ? "PASS" : "FAIL",
    fail_closed:
      "Regression, public validation, privacy, effective-policy, per-tool, or critical zero-tolerance each block overall PASS."
  };
}

export function jsonValuesEqual(left, right) {
  return stableStringify(left) === stableStringify(right);
}

export function validateToolArguments(tool, value) {
  if (!isPlainObject(value)) return false;
  switch (tool) {
    case "get_meal_context":
      return (
        hasExactKeys(value, ["dinerIds"]) &&
        isIdList(value.dinerIds, { min: 1, max: 3 })
      );
    case "compose_family_meal":
      {
        const legacyKeys = [
          "dinerIds",
          "mealType",
          "rejectedFoodIds",
          "rejectedTemplateIds",
          "requestedPriorityFoodIds",
          "preferLowEffort"
        ];
        const currentKeys = [...legacyKeys, "pinnedTemplateIds"];
        if (
          !hasExactKeys(value, legacyKeys) &&
          !hasExactKeys(value, currentKeys)
        ) {
          return false;
        }
        return (
          isIdList(value.dinerIds, { min: 1, max: 3 }) &&
          (value.mealType === "lunch" || value.mealType === "dinner") &&
          isIdList(value.rejectedFoodIds) &&
          isIdList(value.rejectedTemplateIds) &&
          (!("pinnedTemplateIds" in value) ||
            isIdList(value.pinnedTemplateIds)) &&
          isIdList(value.requestedPriorityFoodIds) &&
          typeof value.preferLowEffort === "boolean"
        );
      }
    case "revise_family_meal":
      // v2 this-turn arrays
      if (
        hasExactKeys(value, [
          "rejectTemplateIds",
          "rejectFoodIds",
          "preferLowEffort"
        ])
      ) {
        return (
          isIdList(value.rejectTemplateIds) &&
          isIdList(value.rejectFoodIds) &&
          typeof value.preferLowEffort === "boolean" &&
          (value.rejectTemplateIds.length > 0 ||
            value.rejectFoodIds.length > 0 ||
            value.preferLowEffort)
        );
      }
      // legacy v1 empty-string scalars (historical JSONL only)
      return (
        hasExactKeys(value, [
          "rejectedTemplateId",
          "rejectedFoodId",
          "preferLowEffort"
        ]) &&
        isOptionalId(value.rejectedTemplateId) &&
        isOptionalId(value.rejectedFoodId) &&
        typeof value.preferLowEffort === "boolean" &&
        (value.rejectedTemplateId.length > 0 ||
          value.rejectedFoodId.length > 0 ||
          value.preferLowEffort)
      );
    case "retrieve_approved_guidance":
      // v2: natural query + memberIds (no model-owned health tags)
      if (
        hasExactKeys(value, ["query", "memberIds", "planTags", "topK"]) ||
        // effective may also carry business-filled memberTags
        hasExactKeys(value, [
          "query",
          "memberIds",
          "memberTags",
          "planTags",
          "topK"
        ])
      ) {
        return (
          typeof value.query === "string" &&
          value.query.length >= 1 &&
          value.query.length <= 500 &&
          isIdList(value.memberIds) &&
          isIdList(value.planTags, { max: 16, itemMax: 64 }) &&
          (!("memberTags" in value) ||
            isIdList(value.memberTags, { max: 16, itemMax: 64 })) &&
          Number.isInteger(value.topK) &&
          value.topK >= 1 &&
          value.topK <= 3
        );
      }
      // legacy v1
      return (
        hasExactKeys(value, ["query", "memberTags", "planTags", "topK"]) &&
        typeof value.query === "string" &&
        value.query.length >= 1 &&
        value.query.length <= 500 &&
        isIdList(value.memberTags, { max: 16, itemMax: 64 }) &&
        isIdList(value.planTags, { max: 16, itemMax: 64 }) &&
        Number.isInteger(value.topK) &&
        value.topK >= 1 &&
        value.topK <= 3
      );
    case "preview_caregiver_task":
      return (
        hasExactKeys(value, ["recipientLabel", "serveAt"]) &&
        ["家庭保姆", "保姆", "阿姨"].includes(value.recipientLabel) &&
        isValidServeAt(value.serveAt)
      );
    default:
      return false;
  }
}

function stableStringify(value) {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }
  const keys = Object.keys(value).sort();
  return `{${keys
    .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
    .join(",")}}`;
}

function isPlainObject(value) {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value, expectedKeys) {
  const actual = Object.keys(value).sort();
  const expected = [...expectedKeys].sort();
  return jsonValuesEqual(actual, expected);
}

function isIdList(value, options = {}) {
  const { min = 0, max = 16, itemMax = 96 } = options;
  return (
    Array.isArray(value) &&
    value.length >= min &&
    value.length <= max &&
    value.every(
      (item) =>
        typeof item === "string" &&
        item.length >= 1 &&
        item.length <= itemMax
    )
  );
}

function isOptionalId(value) {
  return typeof value === "string" && value.length <= 96;
}

function isValidServeAt(value) {
  if (typeof value !== "string") return false;
  if (value === "unspecified") return true;
  if (/^今天 (?:[01]\d|2[0-3]):[0-5]\d$/.test(value)) return true;
  if (
    !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(
      value
    )
  ) {
    return false;
  }
  return Number.isFinite(Date.parse(value));
}

function metric(passCount, successRate, threshold) {
  return {
    pass_count: passCount,
    success_rate: successRate,
    threshold,
    gate: successRate >= threshold ? "PASS" : "FAIL"
  };
}
