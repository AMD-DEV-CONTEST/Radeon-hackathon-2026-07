import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { M5Workspace } from './M5Workspace';
import { toWorkspaceView, type M5Api, type M5WorkspaceResponse } from './api';

const ASSET = '11111111-1111-4111-8111-111111111111';
const VERSION = '22222222-2222-4222-8222-222222222222';
const STATEMENT = '44444444-4444-4444-8444-444444444444';

function previewIdentity(route: 'PRIVATE_SELF' | 'PUBLIC' = 'PUBLIC') {
  return {
    route_draft_id: '55555555-5555-4555-8555-555555555555',
    asset_id: ASSET,
    version_id: VERSION,
    asset_version_hash: 'a'.repeat(64),
    lineage_parent_version_id: null,
    relation_projection_hash: '0'.repeat(64),
    route,
    language: 'zh-CN' as const,
    renderer_input_identity: 'd'.repeat(64),
    route_draft_hash: 'e'.repeat(64),
    privacy_state_hash: 'f'.repeat(64),
    draft_state: 'CURRENT' as const,
  };
}

function decision(route: string, eligibility: string, reason: string) {
  return {
    route,
    eligibility,
    reason_codes: [reason],
    explanation: `${route} explanation`,
    supporting_statement_ids: [],
    missing_statement_ids: [],
    canonical_version_id: VERSION,
    policy_version: 'm5-route-policy-v1',
    model_run_id: null,
  };
}

function evaluated(): M5WorkspaceResponse {
  return {
    asset_id: ASSET,
    version_id: VERSION,
    content_hash: 'a'.repeat(64),
    stale_reason: null,
    matrix_hash: 'b'.repeat(64),
    matrix: {
      asset_id: ASSET,
      version_id: VERSION,
      content_hash: 'a'.repeat(64),
      relation_projection_hash: '0'.repeat(64),
      policy_version: 'm5-route-policy-v1',
      decisions: [
        decision('PRIVATE_SELF', 'ELIGIBLE', 'READY'),
        decision('BEGINNER', 'BLOCKED', 'MISSING_BEGINNER_PREREQUISITE'),
        decision('PEER', 'BLOCKED', 'MISSING_PEER_EVIDENCE'),
        decision('CUSTOMER_EVALUATOR', 'INELIGIBLE', 'MISSING_QUALIFYING_CONTEXT'),
        decision('PUBLIC', 'ELIGIBLE_AFTER_PRIVACY_APPROVAL', 'OPEN_PRIVACY_FINDINGS'),
      ] as never,
    },
    privacy_review: {
      review_hash: 'c'.repeat(64),
      status: 'COMPLETE',
      failure_code: null,
      proposal_sources: ['DETERMINISTIC_TEXT_DETECTOR'],
      detector_version: 'm5-privacy-text-detector-v1',
      findings: [
        {
          finding_id: '33333333-3333-4333-8333-333333333333',
          category: 'IDENTITY',
          severity: 'HIGH',
          explanation: '检测到可识别身份信息。',
          affected_statement_ids: ['44444444-4444-4444-8444-444444444444'],
          affected_source_ids: [],
          proposed_actions: ['GENERALIZE', 'REMOVE'],
          resolution: 'OPEN',
        },
      ],
    },
    evidence_statements: {
      [STATEMENT]: '一条经过证据绑定的经验。',
    },
  };
}

function notReady(): M5WorkspaceResponse {
  return {
    asset_id: ASSET,
    version_id: VERSION,
    content_hash: 'a'.repeat(64),
    stale_reason: 'M5_INPUT_NOT_READY',
    matrix: null,
    matrix_hash: null,
    privacy_review: null,
    evidence_statements: {},
  };
}

function api(overrides: Partial<M5Api> = {}): M5Api {
  return {
    get: vi.fn().mockResolvedValue(evaluated()),
    evaluate: vi.fn().mockResolvedValue(evaluated()),
    resolveFinding: vi.fn().mockResolvedValue(evaluated()),
    approve: vi.fn().mockResolvedValue({}),
    createDraft: vi.fn().mockResolvedValue({}),
    previewDraft: vi.fn().mockResolvedValue({}),
    exportDraft: vi.fn().mockResolvedValue({}),
    ...overrides,
  };
}

const storage = (seed: ReadonlyArray<[string, string]> = [
  ['experience-asset.m1.active-asset-id', ASSET],
]) => {
  const map = new Map<string, string>(seed);
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => void map.set(key, value),
    removeItem: (key: string) => void map.delete(key),
    clear: () => map.clear(),
    key: () => null,
    length: 0,
  } as unknown as Storage;
};

describe('entering M5 before an asset exists', () => {
  it('says where the asset comes from and routes back, instead of asking for a UUID', async () => {
    const onCanonicalEdit = vi.fn();
    render(
      <M5Workspace api={api({})} storage={storage([])} onCanonicalEdit={onCanonicalEdit} />,
    );

    expect(screen.getByTestId('m5-no-asset')).toHaveTextContent('请先在 M1');
    await userEvent.click(screen.getByRole('button', { name: '去 M1' }));
    expect(onCanonicalEdit).toHaveBeenCalledOnce();
  });

  it('drops the guidance once M1 has carried an asset over', () => {
    render(<M5Workspace api={api({})} storage={storage()} />);

    expect(screen.queryByTestId('m5-no-asset')).not.toBeInTheDocument();
  });
});

describe('M5 review is reachable from the product surface', () => {
  it('renders all five route decisions with their own reasons', async () => {
    render(<M5Workspace api={api()} storage={storage()} />);

    // A user who only sees the green routes cannot tell a blocked route from
    // one the system never evaluated.
    const workspace = await screen.findByTestId('m5-workspace');
    await waitFor(() =>
      expect(workspace.textContent).toContain('MISSING_QUALIFYING_CONTEXT'),
    );
    for (const reason of [
      '原因：READY',
      '原因：MISSING_BEGINNER_PREREQUISITE',
      '原因：MISSING_PEER_EVIDENCE',
      '原因：MISSING_QUALIFYING_CONTEXT',
      '原因：OPEN_PRIVACY_FINDINGS',
    ]) {
      expect(workspace.textContent).toContain(reason);
    }
  });

  it('explains why M5 is unavailable instead of showing an empty page', async () => {
    render(<M5Workspace api={api({ get: vi.fn().mockResolvedValue(notReady()) })} storage={storage()} />);

    const notice = await screen.findByTestId('m5-not-ready');
    expect(notice).toHaveTextContent('M5_INPUT_NOT_READY');
  });

  it('surfaces a denial reason rather than failing silently', async () => {
    const failing = api({ get: vi.fn().mockRejectedValue(new Error('M5 输入已过期。')) });
    render(<M5Workspace api={failing} storage={storage()} />);

    expect(await screen.findByTestId('m5-error')).toHaveTextContent('M5 输入已过期。');
  });

  it('sends the user evaluate action to the real endpoint', async () => {
    const client = api();
    render(<M5Workspace api={client} storage={storage()} />);
    await screen.findByTestId('m5-workspace');

    await userEvent.click(screen.getByTestId('m5-evaluate'));

    await waitFor(() => expect(client.evaluate).toHaveBeenCalledWith(ASSET));
  });

  it('closes save, preview, exact approval, and external export in the UI', async () => {
    const ready = evaluated();
    ready.privacy_review!.findings = [];
    const publicDecision = ready.matrix!.decisions.find((item) => item.route === 'PUBLIC')!;
    publicDecision.eligibility = 'ELIGIBLE';
    publicDecision.supporting_statement_ids = [STATEMENT];
    const client = api({
      get: vi.fn().mockResolvedValue(ready),
      createDraft: vi.fn().mockResolvedValue({
        renderer_input_identity: 'd'.repeat(64),
        draft: {
          route_draft_id: '55555555-5555-4555-8555-555555555555',
          route: 'PUBLIC',
          language: 'zh-CN',
          content_hash: 'e'.repeat(64),
        },
        content: {
          title: '我的可复用经验',
          summary: {
            text: '一条经过证据绑定的经验。',
            statement_ids: [STATEMENT],
          },
          sections: [],
          notices: [],
        },
      }),
      previewDraft: vi.fn().mockResolvedValue({
        identity: previewIdentity(),
        operation: 'IN_APP_PREVIEW',
        html: '<p>preview</p>',
        markdown: 'preview',
        json: '{}',
      }),
      approve: vi.fn().mockResolvedValue({
        approval_id: '66666666-6666-4666-8666-666666666666',
      }),
      exportDraft: vi.fn().mockResolvedValue({ state: 'COMPLETE' }),
    });
    render(<M5Workspace api={client} storage={storage()} />);
    await screen.findByTestId('m5-draft-workspace');

    await userEvent.selectOptions(screen.getByLabelText('路线'), 'PUBLIC');
    expect(screen.getByLabelText('摘要 / 核心表述')).toHaveValue(
      '一条经过证据绑定的经验。',
    );
    await userEvent.click(screen.getByRole('button', { name: '保存并生成私有预览' }));
    expect(await screen.findByTestId('m5-live-preview')).toHaveTextContent(
      '55555555-5555-4555-8555-555555555555',
    );

    await userEvent.click(
      screen.getByRole('button', { name: '批准当前精确草稿用于外部导出' }),
    );
    await userEvent.click(
      await screen.findByRole('button', { name: /Export HTML/ }),
    );

    await waitFor(() =>
      expect(client.exportDraft).toHaveBeenCalledWith(
        '55555555-5555-4555-8555-555555555555',
        '66666666-6666-4666-8666-666666666666',
      ),
    );
  });

  it('uses the selected route for readiness and clears a saved binding on edits', async () => {
    const ready = evaluated();
    ready.privacy_review!.findings = [];
    const publicDecision = ready.matrix!.decisions.find((item) => item.route === 'PUBLIC')!;
    publicDecision.eligibility = 'ELIGIBLE';
    publicDecision.supporting_statement_ids = [STATEMENT];
    const client = api({get: vi.fn().mockResolvedValue(ready)});
    render(<M5Workspace api={client} storage={storage()} />);

    await userEvent.selectOptions(await screen.findByLabelText('路线'), 'PUBLIC');
    const save = screen.getByRole('button', {name: '保存并生成私有预览'});
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.selectOptions(screen.getByLabelText('路线'), 'BEGINNER');

    expect(save).toBeDisabled();
    expect(
      screen.getByRole('button', {name: '批准当前精确草稿用于外部导出'}),
    ).toBeDisabled();
  });

  it('completes the default private route without creating external approval', async () => {
    const ready = evaluated();
    ready.privacy_review!.findings = [];
    const privateDecision = ready.matrix!.decisions.find(
      (item) => item.route === 'PRIVATE_SELF',
    )!;
    privateDecision.supporting_statement_ids = [STATEMENT];
    const client = api({
      get: vi.fn().mockResolvedValue(ready),
      createDraft: vi.fn().mockResolvedValue({
        renderer_input_identity: 'd'.repeat(64),
        draft: {
          route_draft_id: '55555555-5555-4555-8555-555555555555',
          route: 'PRIVATE_SELF',
          language: 'zh-CN',
          content_hash: 'e'.repeat(64),
        },
        content: {
          title: '我的可复用经验',
          summary: {text: '一条经过证据绑定的经验。', statement_ids: [STATEMENT]},
          sections: [{heading: '核心经验', claims: []}],
          notices: [],
        },
      }),
      previewDraft: vi.fn().mockResolvedValue({
        identity: previewIdentity('PRIVATE_SELF'),
        operation: 'IN_APP_PREVIEW',
        html: '<p>preview</p>',
        markdown: 'preview',
        json: '{}',
      }),
      exportDraft: vi.fn().mockResolvedValue({state: 'COMPLETE'}),
    });
    render(<M5Workspace api={client} storage={storage()} />);

    const save = await screen.findByRole('button', {name: '保存并生成私有预览'});
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);
    await userEvent.click(
      await screen.findByRole('button', {name: /Download private HTML/}),
    );

    await waitFor(() =>
      expect(client.exportDraft).toHaveBeenCalledWith(
        '55555555-5555-4555-8555-555555555555',
      ),
    );
    expect(
      screen.queryByRole('button', {name: '批准当前精确草稿用于外部导出'}),
    ).not.toBeInTheDocument();
  });
});

describe('the view model never widens what policy allowed', () => {
  it('offers only the actions the server proposed for a finding', () => {
    const view = toWorkspaceView(evaluated());

    // The server marked this finding too severe to simply keep.
    expect(view.findings[0].allowed_actions).toEqual(['GENERALIZE', 'REMOVE']);
  });

  it('does not report approval as ready while a finding is open', () => {
    const view = toWorkspaceView(evaluated());

    expect(view.approval.state).toBe('NOT_READY');
  });

  it('carries the privacy producer through to the view', () => {
    const response = evaluated();

    expect(response.privacy_review?.proposal_sources).toContain('DETERMINISTIC_TEXT_DETECTOR');
    expect(toWorkspaceView(response).privacy_review_state).toBe('COMPLETE');
  });
});
