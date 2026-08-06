import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { RouteDecision, RouteEligibility, RouteType } from '../../contracts/types';
import { M5ReviewPanel } from './M5ReviewPanel';
import type { M5WorkspaceView } from './types';

const routes: RouteType[] = [
  'PRIVATE_SELF',
  'BEGINNER',
  'PEER',
  'CUSTOMER_EVALUATOR',
  'PUBLIC',
];

function decisions(): RouteDecision[] {
  const states: Record<RouteType, RouteEligibility> = {
    PRIVATE_SELF: 'ELIGIBLE',
    BEGINNER: 'ELIGIBLE',
    PEER: 'BLOCKED',
    CUSTOMER_EVALUATOR: 'INELIGIBLE',
    PUBLIC: 'ELIGIBLE_AFTER_PRIVACY_APPROVAL',
  };
  return routes.map(route => ({
    route,
    eligibility: states[route],
    explanation: `${route} explanation`,
    reason_codes: states[route] === 'ELIGIBLE' ? ['READY'] : [`${route}_REASON`],
    supporting_statement_ids: ['statement-1'],
    missing_statement_ids: states[route] === 'BLOCKED' ? ['statement-2'] : [],
    canonical_version_id: 'version-1',
    policy_version: 'm5-route-policy-v1',
  }));
}

function workspace(overrides: Partial<M5WorkspaceView> = {}): M5WorkspaceView {
  return {
    asset_id: 'asset-1',
    version_id: 'version-1',
    content_hash: 'content-hash-1',
    autosave_state: 'saved',
    run_id: 'run-1',
    terminal_state: 'NEEDS_USER_INPUT',
    decisions: decisions(),
    findings: [{
      finding_id: 'finding-1',
      category: 'IDENTITY',
      severity: 'HIGH',
      explanation: 'Identity detail requires review.',
      affected_reference_ids: ['statement-1'],
      allowed_actions: ['GENERALIZE', 'REMOVE'],
      resolution: 'OPEN',
    }],
    privacy_review_state: 'COMPLETE',
    approval: {
      state: 'READY',
      route: 'PUBLIC',
      language: 'zh-CN',
      version_id: 'version-1',
      route_draft_id: 'draft-id-1',
      privacy_review_hash: 'privacy-hash-1',
    },
    ...overrides,
  };
}

describe('isolated M5 route, privacy, and approval UI', () => {
  it('renders all five backend-owned route states distinctly', () => {
    render(
      <M5ReviewPanel
        workspace={workspace()}
        onResolveFinding={vi.fn()}
        onApprove={vi.fn()}
      />,
    );
    for (const route of routes) {
      expect(screen.getByTestId(`m5-route-${route}`)).toBeInTheDocument();
    }
    expect(screen.getByText('受阻')).toBeInTheDocument();
    expect(screen.getByText('不适用')).toBeInTheDocument();
    expect(screen.getByText('隐私审批后可用')).toBeInTheDocument();
  });

  it('shows the exact supporting and missing evidence references for review', () => {
    render(
      <M5ReviewPanel
        workspace={workspace()}
        onResolveFinding={vi.fn()}
        onApprove={vi.fn()}
      />,
    );

    const peerEvidence = screen.getByTestId('m5-route-PEER-evidence');
    expect(peerEvidence).toHaveTextContent('支持证据：statement-1');
    expect(peerEvidence).toHaveTextContent('缺失证据：statement-2');
  });

  it('requires a second confirmation for content-changing privacy actions', async () => {
    const onResolve = vi.fn();
    const onCanonicalEdit = vi.fn();
    const user = userEvent.setup();
    render(
      <M5ReviewPanel
        workspace={workspace()}
        onResolveFinding={onResolve}
        onApprove={vi.fn()}
        onCanonicalEdit={onCanonicalEdit}
      />,
    );
    await user.click(screen.getByRole('button', {name: 'GENERALIZE'}));
    expect(onResolve).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog', {name: '确认内容修改'})).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: '去 M1 创建新版本'}));
    expect(onResolve).not.toHaveBeenCalled();
    expect(onCanonicalEdit).toHaveBeenCalledOnce();
  });

  it('passes the exact visible draft binding to Runtime approval', async () => {
    const onApprove = vi.fn();
    const user = userEvent.setup();
    render(
      <M5ReviewPanel
        workspace={workspace({findings: []})}
        onResolveFinding={vi.fn()}
        onApprove={onApprove}
      />,
    );
    await user.click(screen.getByRole('button', {name: '批准当前精确草稿用于外部导出'}));
    expect(onApprove).toHaveBeenCalledWith({
      route_draft_id: 'draft-id-1',
      user_action: 'APPROVE_SHAREABLE_EXPORT',
      idempotency_key: 'asset-1:version-1:draft-id-1:privacy-hash-1',
    });
  });

  it('reuses the key for an exact retry and changes it with the stored draft', async () => {
    const firstApproval = vi.fn();
    const user = userEvent.setup();
    const first = render(
      <M5ReviewPanel
        workspace={workspace({findings: []})}
        onResolveFinding={vi.fn()}
        onApprove={firstApproval}
      />,
    );
    const approveButton = screen.getByRole('button', {
      name: '批准当前精确草稿用于外部导出',
    });
    await user.click(approveButton);
    await user.click(approveButton);
    expect(firstApproval).toHaveBeenCalledTimes(2);
    expect(firstApproval.mock.calls[0][0].idempotency_key).toBe(
      firstApproval.mock.calls[1][0].idempotency_key,
    );
    const originalKey = firstApproval.mock.calls[0][0].idempotency_key;
    first.unmount();

    const changedApproval = vi.fn();
    render(
      <M5ReviewPanel
        workspace={workspace({
          findings: [],
          approval: {
            state: 'READY',
            route: 'PUBLIC',
            language: 'zh-CN',
            version_id: 'version-1',
            route_draft_id: 'draft-id-2',
            privacy_review_hash: 'privacy-hash-2',
          },
        })}
        onResolveFinding={vi.fn()}
        onApprove={changedApproval}
      />,
    );
    await user.click(screen.getByRole('button', {
      name: '批准当前精确草稿用于外部导出',
    }));

    expect(changedApproval.mock.calls[0][0].idempotency_key).not.toBe(originalKey);
  });

  it('keeps approval disabled while any privacy finding remains open', () => {
    render(
      <M5ReviewPanel
        workspace={workspace()}
        onResolveFinding={vi.fn()}
        onApprove={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', {name: '批准当前精确草稿用于外部导出'})).toBeDisabled();
  });

  it('shows privacy failure and disables approval without a final draft', () => {
    render(
      <M5ReviewPanel
        workspace={workspace({
          privacy_review_state: 'FAILED',
          privacy_failure_code: 'MODEL_UNAVAILABLE',
          approval: {
            state: 'NOT_READY',
            route: 'PUBLIC',
            language: 'zh-CN',
            version_id: 'version-1',
          },
        })}
        onResolveFinding={vi.fn()}
        onApprove={vi.fn()}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('MODEL_UNAVAILABLE');
    expect(screen.getByRole('button', {name: '批准当前精确草稿用于外部导出'})).toBeDisabled();
  });
});
