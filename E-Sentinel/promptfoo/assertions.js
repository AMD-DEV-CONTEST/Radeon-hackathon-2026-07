module.exports = function assertFixtureResult(output, context) {
  let result;
  try {
    result = JSON.parse(output);
  } catch {
    return { pass: false, score: 0, reason: "provider output is not valid JSON" };
  }

  const vars = context?.vars || {};
  const expectedCategory = vars.expected_category;
  const expectedBlock = vars.expected_block === true || vars.expected_block === "true";
  const pass = result.case_id === vars.case_id
    && result.predicted_category === expectedCategory
    && result.blocked === expectedBlock
    && typeof result.evidence_coverage === "number"
    && result.rule_version === "qa-rules-v1"
    && Object.values(result.source_provenance || {}).every((value) => /^[a-f0-9]{16}$/.test(value));
  return {
    pass,
    score: pass ? 1 : 0,
    reason: pass
      ? "deterministic fixture result matches the declared expected contract"
      : `expected ${expectedCategory}/${expectedBlock}, got ${result.predicted_category}/${result.blocked}`,
  };
};
