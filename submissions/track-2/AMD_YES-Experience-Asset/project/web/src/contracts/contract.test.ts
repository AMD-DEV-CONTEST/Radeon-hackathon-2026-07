/**
 * Contract conformance: every mock fixture the UI renders must validate against
 * the vendored E1-A JSON Schema. This is what makes "typed client and mocks
 * derived from the checked-in contracts" verifiable rather than asserted, and it
 * fails if the hand-written TS types drift from the reviewed schema.
 */
import { describe, expect, it } from 'vitest';
import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';

import healthSchema from '../../contracts/openapi.json';
import progressSchema from '../../contracts/json-schema/progress-event-v1.schema.json';
import terminalSchema from '../../contracts/json-schema/terminal-result-v1.schema.json';
import assetSchema from '../../contracts/json-schema/experience-asset-v1.schema.json';
import proposalSchema from '../../contracts/json-schema/structured-proposal-v1.schema.json';
import runStateSchema from '../../contracts/json-schema/agent-run-state-v1.schema.json';
import workPlanSchema from '../../contracts/json-schema/work-plan-v1.schema.json';
import policyDecisionSchema from '../../contracts/json-schema/policy-decision-v1.schema.json';
import toolExecutionSchema from '../../contracts/json-schema/tool-execution-record-v1.schema.json';
import verificationReportSchema from '../../contracts/json-schema/verification-report-v1.schema.json';
import readinessSchema from '../../contracts/json-schema/knowledge-card-readiness-v1.schema.json';
import candidateSchema from '../../contracts/json-schema/relation-candidate-v1.schema.json';
import workspaceSchema from '../../contracts/json-schema/relation-workspace-v1.schema.json';

import proposalExample from '../../contracts/examples/structured-tool-proposal.json';

import {
  CANDIDATE_METHOD_REUSE,
  CANDIDATE_SAME_THEME,
  MOCK_SCENARIOS,
  PROGRESS_RUNNING,
  TERMINAL_MODEL_UNAVAILABLE,
  HEALTH_OK,
  AGENT_RUN_STATE,
} from '../data/fixtures';

function makeAjv() {
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  addFormats(ajv);
  return ajv;
}

const healthStatusSchema = (healthSchema as { components: { schemas: Record<string, object> } })
  .components.schemas.HealthStatusV1;

describe('mock fixtures conform to vendored E1-A contracts', () => {
  const ajv = makeAjv();
  const validateHealth = ajv.compile(healthStatusSchema);
  const validateProgress = ajv.compile(progressSchema);
  const validateTerminal = ajv.compile(terminalSchema);
  const validateAsset = ajv.compile(assetSchema);
  const validateProposal = ajv.compile(proposalSchema);
  const validateRunState = ajv.compile(runStateSchema);
  const validateWorkPlan = ajv.compile(workPlanSchema);
  const validatePolicyDecision = ajv.compile(policyDecisionSchema);
  const validateToolExecution = ajv.compile(toolExecutionSchema);
  const validateVerificationReport = ajv.compile(verificationReportSchema);

  it('health fixture matches HealthStatusV1', () => {
    expect(validateHealth(HEALTH_OK), JSON.stringify(validateHealth.errors)).toBe(true);
  });

  it('progress fixture matches ProgressEventV1', () => {
    expect(validateProgress(PROGRESS_RUNNING), JSON.stringify(validateProgress.errors)).toBe(true);
  });

  it('terminal fixtures match TerminalResultV1', () => {
    expect(validateTerminal(TERMINAL_MODEL_UNAVAILABLE), JSON.stringify(validateTerminal.errors)).toBe(true);
    const paused = MOCK_SCENARIOS['safe-stop'].activeRun;
    expect(paused?.kind).toBe('terminal');
    if (paused?.kind === 'terminal') {
      expect(validateTerminal(paused.result), JSON.stringify(validateTerminal.errors)).toBe(true);
    }
  });

  it('structured proposal example matches StructuredProposalV1 and grants no permission', () => {
    expect(validateProposal(proposalExample), JSON.stringify(validateProposal.errors)).toBe(true);
    for (const proposal of proposalExample.tool_call_proposals) {
      expect(proposal.permission_granted).toBe(false);
    }
  });

  it('canonical run-state fixture and every durable component match final E1-A schemas', () => {
    expect(validateRunState(AGENT_RUN_STATE), JSON.stringify(validateRunState.errors)).toBe(true);
    expect(
      validateWorkPlan(AGENT_RUN_STATE.work_plan),
      JSON.stringify(validateWorkPlan.errors),
    ).toBe(true);
    for (const decision of AGENT_RUN_STATE.policy_decisions ?? []) {
      expect(
        validatePolicyDecision(decision),
        JSON.stringify(validatePolicyDecision.errors),
      ).toBe(true);
    }
    for (const execution of AGENT_RUN_STATE.tool_executions ?? []) {
      expect(
        validateToolExecution(execution),
        JSON.stringify(validateToolExecution.errors),
      ).toBe(true);
    }
    expect(AGENT_RUN_STATE.verification_report).not.toBeNull();
    expect(
      validateVerificationReport(AGENT_RUN_STATE.verification_report),
      JSON.stringify(validateVerificationReport.errors),
    ).toBe(true);
  });

  it('every canonical-asset fixture validates against ExperienceAssetV1', () => {
    const assets = Object.values(MOCK_SCENARIOS)
      .map((s) => s.asset)
      .filter((a): a is NonNullable<typeof a> => a !== null);
    expect(assets.length).toBeGreaterThan(0);
    for (const asset of assets) {
      const ok = validateAsset(asset);
      expect(ok, JSON.stringify(validateAsset.errors)).toBe(true);
    }
  });
});


/*
 * The E5 relation contracts were previously absent here, which is why the
 * TypeScript mirror could diverge from the backend while typecheck and Vitest
 * stayed green: the types and the fixtures agreed with each other, and nothing
 * compared either to the reviewed schema. Every relation fixture the UI renders
 * is now validated against the vendored E5 schema.
 */
describe('E5 relation contract conformance', () => {
  const ajv = new Ajv2020({ strict: false, allErrors: true });
  addFormats(ajv);

  it('validates every scenario relation workspace', () => {
    const validate = ajv.compile(workspaceSchema);
    for (const [name, scenario] of Object.entries(MOCK_SCENARIOS)) {
      if (!scenario.relationWorkspace) continue;
      const ok = validate(scenario.relationWorkspace);
      expect(validate.errors ?? [], `${name}: ${JSON.stringify(validate.errors)}`).toEqual(
        [],
      );
      expect(ok).toBe(true);
    }
  });

  it('validates the readiness record the workspace carries', () => {
    const validate = ajv.compile(readinessSchema);
    const readiness = MOCK_SCENARIOS['relation-ready'].relationWorkspace?.readiness;
    expect(readiness).toBeTruthy();
    const ok = validate(readiness);
    expect(validate.errors ?? []).toEqual([]);
    expect(ok).toBe(true);
  });

  it('validates each candidate fixture, including the SAME_THEME root mapping', () => {
    const validate = ajv.compile(candidateSchema);
    for (const candidate of [CANDIDATE_SAME_THEME, CANDIDATE_METHOD_REUSE]) {
      const ok = validate(candidate);
      expect(
        validate.errors ?? [],
        `${candidate.relation_type}: ${JSON.stringify(validate.errors)}`,
      ).toEqual([]);
      expect(ok).toBe(true);
    }
  });
});
