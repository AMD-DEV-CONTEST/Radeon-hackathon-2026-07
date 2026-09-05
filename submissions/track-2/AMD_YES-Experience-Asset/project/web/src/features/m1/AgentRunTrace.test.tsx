import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AgentRunTrace } from './AgentRunTrace';
import type { M1Workspace } from './types';

type AgentRun = NonNullable<M1Workspace['latest_agent_run']>;

function run(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    run_id: 'run-1',
    model_id: 'Qwen3.5-9B',
    server_base_url: 'http://127.0.0.1:8000/v1',
    retrieval_scope: 'CURRENT_ASSET_ONLY',
    work_plan: {
      goal: '检查来源边界',
      revision: 1,
      steps: [
        {
          step_id: 'step-1',
          step_kind: 'RETRIEVE',
          reason: '取当前资产证据。',
          status: 'DONE',
          stop_condition: '证据已取。',
        },
      ],
    },
    retrieved_evidence: [],
    tool_proposals: [
      { name: 'search_current_experience', permission_granted: false },
      { name: 'summarize_statements', permission_granted: false },
    ],
    policy_decisions: [
      { outcome: 'ALLOW', reason_codes: ['ALLOWLIST_AND_SCOPE_VALID'] },
      { outcome: 'DENY', reason_codes: ['OUT_OF_SCOPE', 'NOT_ALLOWLISTED'] },
    ],
    tool_executions: [
      {
        tool_name: 'search_current_experience',
        status: 'SUCCEEDED',
        observation_refs: ['asset:current/statement:source'],
      },
    ],
    verification_report: {
      outcome: 'VERIFIED',
      checks: { effect_matches_policy: true, scope_respected: false },
      finding_codes: ['SCOPE_DRIFT'],
      safe_summary: 'Current-source retrieval effect verified.',
    },
    terminal_state: 'SUCCEEDED',
    ...overrides,
  };
}

describe('AgentRunTrace', () => {
  it('renders every proposal, not just the first', () => {
    render(<AgentRunTrace run={run()} />);
    const proposals = screen.getByTestId('m1-agent-proposals');
    expect(within(proposals).getByText('search_current_experience')).toBeInTheDocument();
    expect(within(proposals).getByText('summarize_statements')).toBeInTheDocument();
  });

  it('renders every policy decision with its reason codes', () => {
    render(<AgentRunTrace run={run()} />);
    const decisions = screen.getByTestId('m1-agent-decisions');
    expect(within(decisions).getByText('ALLOW')).toBeInTheDocument();
    expect(within(decisions).getByText('DENY')).toBeInTheDocument();
    expect(within(decisions).getByText(/OUT_OF_SCOPE · NOT_ALLOWLISTED/)).toBeInTheDocument();
  });

  it('never claims a proposal carried execution permission', () => {
    render(<AgentRunTrace run={run()} />);
    const proposals = screen.getByTestId('m1-agent-proposals');
    expect(within(proposals).getAllByText(/permission_granted: false/)).toHaveLength(2);
  });

  it('shows each verification check outcome, including failures', () => {
    render(<AgentRunTrace run={run()} />);
    const verification = screen.getByTestId('m1-agent-verification');
    expect(within(verification).getByText('effect_matches_policy')).toBeInTheDocument();
    expect(within(verification).getByText('scope_respected')).toBeInTheDocument();
    expect(within(verification).getByText('fail')).toBeInTheDocument();
    expect(within(verification).getByText('SCOPE_DRIFT')).toBeInTheDocument();
  });

  it('states an empty list instead of implying work happened', () => {
    render(<AgentRunTrace run={run({ tool_executions: [], verification_report: null })} />);
    expect(
      within(screen.getByTestId('m1-agent-executions')).getByText('没有工具被实际执行。'),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId('m1-agent-verification')).getByText('尚无验证报告。'),
    ).toBeInTheDocument();
  });
});
