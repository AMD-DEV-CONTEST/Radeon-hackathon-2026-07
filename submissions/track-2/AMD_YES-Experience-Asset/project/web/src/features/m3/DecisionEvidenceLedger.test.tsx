import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import { describe, expect, it, vi } from 'vitest';
import workspaceSchema from '../../../../contracts/json-schema/m3-workspace-v1.schema.json';
import { DecisionEvidenceLedger } from './DecisionEvidenceLedger';
import { M3_SCENARIOS } from './fixtures';

const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);
const validateWorkspace = ajv.compile(workspaceSchema);

describe('DecisionEvidenceLedger preparation UI', () => {
  it('keeps every isolated scenario inside the published workspace contract', () => {
    for (const fixture of Object.values(M3_SCENARIOS)) {
      expect(
        validateWorkspace(fixture),
        JSON.stringify(validateWorkspace.errors),
      ).toBe(true);
    }
  });

  it('renders all five required decision roles with evidence state', () => {
    render(<DecisionEvidenceLedger workspace={M3_SCENARIOS.complete} />);

    const list = screen.getByTestId('m3-decision-list');
    expect(within(list).getByText('替代方案')).toBeInTheDocument();
    expect(within(list).getByText('理由')).toBeInTheDocument();
    expect(within(list).getByText('最终决策')).toBeInTheDocument();
    expect(within(list).getByText('行动')).toBeInTheDocument();
    expect(within(list).getByText('观察结果')).toBeInTheDocument();
    expect(within(list).getAllByText('有证据')).toHaveLength(5);
  });

  it('exposes stable evidence IDs with readable moment and source text', () => {
    render(<DecisionEvidenceLedger workspace={M3_SCENARIOS.complete} />);

    const evidence = screen.getAllByTestId('m3-evidence-details')[0];
    expect(evidence).toHaveTextContent(
      M3_SCENARIOS.complete.evidence_moments[0].moment_id,
    );
    expect(evidence).toHaveTextContent(
      M3_SCENARIOS.complete.evidence_moments[0].title,
    );
    expect(evidence).toHaveTextContent(
      M3_SCENARIOS.complete.evidence_statements[0].statement_id,
    );
    expect(evidence).toHaveTextContent(
      M3_SCENARIOS.complete.evidence_statements[0].text,
    );
    expect(evidence).toHaveTextContent('公开改写研究样例');
  });

  it('shows a missing result as unresolved instead of inventing one', () => {
    render(<DecisionEvidenceLedger workspace={M3_SCENARIOS.incomplete} />);

    const result = screen.getByTestId('m3-statement-observed_result');
    expect(result).toHaveTextContent('尚未提供可观察结果');
    expect(result).toHaveTextContent('待补充');
    expect(screen.getByTestId('m3-unresolved-reason')).toHaveTextContent(
      '没有说明执行后的实际结果',
    );
  });

  it('keeps conflicting evidence visible', () => {
    render(<DecisionEvidenceLedger workspace={M3_SCENARIOS.conflicting} />);

    const reason = screen.getByTestId('m3-statement-reason');
    expect(reason).toHaveTextContent('证据冲突');
    expect(reason).toHaveTextContent('两个来源');
  });

  it('exposes the permission-denied terminal without implying an effect', () => {
    render(<DecisionEvidenceLedger workspace={M3_SCENARIOS.permission_denied} />);

    expect(screen.getByTestId('m3-failure')).toHaveTextContent(
      'PERMISSION_DENIED',
    );
    expect(screen.getByTestId('m3-progress')).toHaveTextContent('TERMINAL');
  });

  it('keeps invalidated history read-only and offers no stale edit', () => {
    const onChange = vi.fn();
    render(
      <DecisionEvidenceLedger
        workspace={M3_SCENARIOS.correction_invalidation}
        onStatementTextChange={onChange}
      />,
    );

    expect(screen.getByTestId('m3-invalidated')).toHaveTextContent('已失效');
    expect(screen.getAllByRole('textbox')[0]).toHaveAttribute('readonly');
  });

  it('emits a controlled edit without mutating the fixture', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <DecisionEvidenceLedger
        workspace={M3_SCENARIOS.complete}
        onStatementTextChange={onChange}
      />,
    );

    const alternative = screen.getByRole('textbox', { name: '替代方案' });
    const original = M3_SCENARIOS.complete.artifact.entries[0].statements[0].text;
    await user.type(alternative, '补');

    expect(onChange).toHaveBeenCalled();
    expect(
      M3_SCENARIOS.complete.artifact.entries[0].statements[0].text,
    ).toBe(original);
  });
});
