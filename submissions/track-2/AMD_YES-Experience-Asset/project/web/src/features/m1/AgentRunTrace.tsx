import type { M1Workspace } from './types';

type AgentRun = NonNullable<M1Workspace['latest_agent_run']>;

/**
 * Renders the whole proposal -> policy -> execution -> verification chain.
 *
 * The earlier inline trace showed only the first entry of each list, which
 * cannot demonstrate that every proposal was validated and every allowed call
 * actually ran. Nothing here is summarised or inferred: each list renders every
 * record the backend returned, and an empty list says so explicitly.
 *
 * The run response is returned once, when the graph finishes, so this is a
 * completed-run replay and never claims live progress.
 */
export function AgentRunTrace({ run }: { run: AgentRun }) {
  return (
    <div className="m1-agent-trace" data-testid="m1-agent-trace">
      <div className="stats">
        <div className="stat">
          <span className="stat__value">{run.work_plan.steps.length}</span>
          <span className="stat__label">计划步骤</span>
        </div>
        <div className="stat">
          <span className="stat__value">{run.retrieved_evidence.length}</span>
          <span className="stat__label">来源证据</span>
        </div>
        <div className="stat">
          <span className="stat__value">{run.tool_executions.length}</span>
          <span className="stat__label">真实执行</span>
        </div>
        <div className="stat">
          <span className="stat__value" data-testid="m1-agent-terminal">
            {run.terminal_state ?? 'RUNNING'}
          </span>
          <span className="stat__label">终态</span>
        </div>
      </div>

      <ol className="m1-plan">
        {run.work_plan.steps.map((step) => (
          <li key={step.step_id}>
            <div className="row">
              <strong>{step.step_kind}</strong>
              <span className="badge badge--neutral">{step.status}</span>
            </div>
            <span>{step.reason}</span>
          </li>
        ))}
      </ol>

      <div className="notice notice--muted">
        <strong>模型：</strong> <code>{run.model_id}</code>
        <br />
        <strong>检索范围：</strong> <code>{run.retrieval_scope}</code>
      </div>

      <section data-testid="m1-agent-proposals">
        <p className="hint">工具提议（{run.tool_proposals.length}）— 提议不授予任何执行权限</p>
        {run.tool_proposals.length === 0 ? (
          <p className="hint">本次运行没有提出工具调用。</p>
        ) : (
          <ol className="m1-plan">
            {run.tool_proposals.map((proposal, index) => (
              <li key={`${proposal.name}-${index}`}>
                <div className="row">
                  <strong>{proposal.name}</strong>
                  <span className="badge badge--warn">
                    permission_granted: {proposal.permission_granted ? 'true' : 'false'}
                  </span>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section data-testid="m1-agent-decisions">
        <p className="hint">Runtime 裁决（{run.policy_decisions.length}）</p>
        {run.policy_decisions.length === 0 ? (
          <p className="hint">没有裁决记录。</p>
        ) : (
          <ol className="m1-plan">
            {run.policy_decisions.map((decision, index) => (
              <li key={`${decision.outcome}-${index}`}>
                <div className="row">
                  <strong>{decision.outcome}</strong>
                  <span className={`badge badge--${decision.outcome === 'ALLOW' ? 'ok' : 'danger'}`}>
                    {decision.reason_codes.length} 条依据
                  </span>
                </div>
                {decision.reason_codes.length > 0 ? (
                  <span className="mono">{decision.reason_codes.join(' · ')}</span>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section data-testid="m1-agent-executions">
        <p className="hint">真实执行（{run.tool_executions.length}）</p>
        {run.tool_executions.length === 0 ? (
          <p className="hint">没有工具被实际执行。</p>
        ) : (
          <ol className="m1-plan">
            {run.tool_executions.map((execution, index) => (
              <li key={`${execution.tool_name}-${index}`}>
                <div className="row">
                  <strong>{execution.tool_name}</strong>
                  <span className="badge badge--neutral">{execution.status}</span>
                </div>
                {execution.observation_refs.length > 0 ? (
                  <span className="mono">{execution.observation_refs.join(' · ')}</span>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section data-testid="m1-agent-verification">
        <p className="hint">验证</p>
        {run.verification_report === null ? (
          <p className="hint">尚无验证报告。</p>
        ) : (
          <div className="notice notice--muted">
            <div className="row">
              <strong>{run.verification_report.outcome}</strong>
              {run.verification_report.finding_codes.length > 0 ? (
                <span className="badge badge--warn">
                  {run.verification_report.finding_codes.join(' · ')}
                </span>
              ) : null}
            </div>
            <ul className="m1-plan">
              {Object.entries(run.verification_report.checks).map(([check, passed]) => (
                <li key={check}>
                  <div className="row">
                    <span className="mono">{check}</span>
                    <span className={`badge badge--${passed ? 'ok' : 'danger'}`}>
                      {passed ? 'pass' : 'fail'}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
            <span>{run.verification_report.safe_summary}</span>
          </div>
        )}
      </section>
    </div>
  );
}
