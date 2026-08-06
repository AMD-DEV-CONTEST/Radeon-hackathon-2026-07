import { useCallback, useEffect, useMemo, useState } from 'react';
import { Mono } from '../../components/primitives';
import type { RouteType } from '../../contracts/types';
import { DeliveryPreview } from '../delivery/DeliveryPreview';
import type { DeliveryPreviewV1 } from '../delivery/types';
import { M5ReviewPanel } from './M5ReviewPanel';
import {
  createM5Api,
  toWorkspaceView,
  type ApprovalResponse,
  type DeliveryPreviewResponse,
  type M5Api,
  type M5WorkspaceResponse,
  type StoredRouteDraftResponse,
} from './api';
import type { M5ApprovalAction, M5PrivacyAction, M5WorkspaceView } from './types';
import { Working } from '../../shell/Working';

const KEY = 'experience-asset.m1.active-asset-id';

type Props = {
  apiBaseUrl?: string;
  api?: M5Api;
  storage?: Storage;
  onCanonicalEdit?: () => void;
  onStatusChange?: () => void;
};

export function M5Workspace({
  apiBaseUrl = '',
  api: supplied,
  storage = window.localStorage,
  onCanonicalEdit = () => {},
  onStatusChange,
}: Props) {
  const live = useMemo(() => createM5Api(apiBaseUrl), [apiBaseUrl]);
  const api = supplied ?? live;
  const [assetId, setAssetId] = useState(
    () => new URLSearchParams(location.search).get('asset') ?? storage.getItem(KEY) ?? '',
  );
  const [response, setResponse] = useState<M5WorkspaceResponse | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftTitle, setDraftTitle] = useState('我的可复用经验');
  const [draftSummary, setDraftSummary] = useState('');
  const [route, setRoute] = useState<RouteType>('PRIVATE_SELF');
  const [language, setLanguage] = useState<'zh-CN' | 'en'>('zh-CN');
  const [draft, setDraft] = useState<StoredRouteDraftResponse | null>(null);
  const [preview, setPreview] = useState<DeliveryPreviewResponse | null>(null);
  const [approval, setApproval] = useState<ApprovalResponse | null>(null);
  const [exported, setExported] = useState(false);

  const clearDeliveryBinding = useCallback(() => {
    setDraft(null);
    setPreview(null);
    setApproval(null);
    setExported(false);
  }, []);

  const run = useCallback(
    async (action: () => Promise<M5WorkspaceResponse>, notifyStatus = false) => {
      setBusy(true);
      setError('');
      try {
        const next = await action();
        setResponse(next);
        clearDeliveryBinding();
        if (notifyStatus) onStatusChange?.();
      } catch (cause) {
        // Surface the reason rather than an empty panel: a blocked M5 is a
        // state the user has to be able to read and act on.
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setBusy(false);
      }
    },
    [clearDeliveryBinding, onStatusChange],
  );

  useEffect(() => {
    if (!assetId) return;
    void run(() => api.get(assetId));
  }, [api, assetId, run]);

  const view = response ? toWorkspaceView(response, route, language) : null;
  const notReady = response?.stale_reason ?? null;
  const decision = response?.matrix?.decisions.find((item) => item.route === route);
  const evidenceText = decision?.supporting_statement_ids
    ?.map((statementId) => response?.evidence_statements[statementId])
    .find((text): text is string => Boolean(text));
  useEffect(() => {
    setDraftSummary(evidenceText ?? '');
  }, [evidenceText]);
  const canSaveDraft =
    Boolean(draftTitle.trim())
    && Boolean(draftSummary.trim())
    && Boolean(decision?.supporting_statement_ids?.length)
    && decision?.eligibility !== 'BLOCKED'
    && decision?.eligibility !== 'INELIGIBLE';
  const panelView: M5WorkspaceView | null = view
    ? {
        ...view,
        approval: {
          ...view.approval,
          state: approval ? 'APPROVED' : view.approval.state,
          route_draft_id: draft?.draft.route_draft_id,
        },
      }
    : null;
  const deliveryPreview: DeliveryPreviewV1 | null = preview && draft
    ? {
        route_draft_id: preview.identity.route_draft_id,
        asset_id: preview.identity.asset_id,
        version_id: preview.identity.version_id,
        asset_version_hash: preview.identity.asset_version_hash,
        lineage_parent_version_id: preview.identity.lineage_parent_version_id,
        relation_projection_hash: preview.identity.relation_projection_hash,
        route: preview.identity.route,
        language: preview.identity.language,
        route_draft_hash: preview.identity.route_draft_hash,
        renderer_input_identity: preview.identity.renderer_input_identity,
        privacy_state_hash: preview.identity.privacy_state_hash,
        state: preview.identity.draft_state,
        approval_status: route === 'PRIVATE_SELF' ? 'NOT_REQUIRED' : approval ? 'VALID' : 'MISSING',
        title: draft.content.title,
        summary: draft.content.summary.text,
        sections: draft.content.sections,
      }
    : null;

  const saveDraft = async () => {
    if (!canSaveDraft || !decision) return;
    setDraftBusy(true);
    setError('');
    setApproval(null);
    setExported(false);
    try {
      const statementIds = decision.supporting_statement_ids ?? [];
      const claim = { text: draftSummary.trim(), statement_ids: statementIds };
      const saved = await api.createDraft(assetId, {
        create_request_id: crypto.randomUUID(),
        route,
        language,
        content: {
          title: draftTitle.trim(),
          summary: claim,
          sections: [
            {heading: language === 'zh-CN' ? '核心经验' : 'Core evidence', claims: [claim]},
          ],
          notices: [
            language === 'zh-CN'
              ? '对外分享前请复核内容和隐私状态。'
              : 'Review content and privacy state before external sharing.',
          ],
        },
      });
      setDraft(saved);
      setPreview(await api.previewDraft(saved.draft.route_draft_id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setDraftBusy(false);
    }
  };

  return (
    <section className="panel" data-testid="m5-workspace">
      <header className="panel__header">
        <h2>M5 路由就绪度与隐私审查</h2>
        <p className="panel__subtitle">
          五条路由各给一个可解释的结论；对外分享必须先解决隐私发现并取得绑定到确切版本/哈希的批准。
        </p>
      </header>

      {assetId ? null : (
        <div className="notice notice--muted" data-testid="m5-no-asset">
          还没有可评估的经验资产。M5 读取的是 M1–M4 打磨完成的那一份，请先在 M1
          创建或恢复它。{' '}
          <button type="button" className="btn" onClick={onCanonicalEdit}>
            去 M1
          </button>
        </div>
      )}

      <div className="field-row">
        <label htmlFor="m5-asset">经验资产 ID</label>
        <input
          id="m5-asset"
          data-testid="m5-asset-input"
          value={assetId}
          placeholder="由 M1 创建后自动带入"
          onChange={(event) => {
            setAssetId(event.target.value);
            storage.setItem(KEY, event.target.value);
          }}
        />
        <button
          type="button"
          className="btn"
          data-testid="m5-load"
          disabled={!assetId || busy}
          onClick={() => void run(() => api.get(assetId))}
        >
          读取
        </button>
        <button
          type="button"
          className="btn btn--primary"
          data-testid="m5-evaluate"
          disabled={!assetId || busy}
          onClick={() => void run(() => api.evaluate(assetId), true)}
        >
          评估五条路由
        </button>
      </div>

      {busy ? <Working label="正在处理当前 M5 操作" testId="m5-working" /> : null}
      {draftBusy ? (
        <Working label="正在生成私有预览与三种格式" testId="m5-draft-working" />
      ) : null}
      {error ? (
        <p className="notice notice--danger" role="alert" data-testid="m5-error">
          {error}
        </p>
      ) : null}

      {notReady ? (
        <p className="notice notice--warn" data-testid="m5-not-ready">
          M5 尚不可用：<Mono>{notReady}</Mono>
          。请先在 M4 完成并接受知识卡片。
        </p>
      ) : null}

      {panelView && !notReady ? (
        <>
          <section className="panel" data-testid="m5-draft-workspace">
            <header className="panel__header">
              <h3>生成与预览最终草稿</h3>
              <p className="panel__subtitle">
                先选择可用路线并保存草稿，再对这一个持久化版本进行批准。
              </p>
            </header>
            <div className="fields">
              <label className="field">
                <span className="field__label">路线</span>
                <select value={route} onChange={(event) => {
                  setRoute(event.target.value as RouteType);
                  clearDeliveryBinding();
                }}>
                  <option value="PRIVATE_SELF">PRIVATE_SELF</option>
                  <option value="PUBLIC">PUBLIC</option>
                  <option value="BEGINNER">BEGINNER</option>
                  <option value="PEER">PEER</option>
                  <option value="CUSTOMER_EVALUATOR">CUSTOMER_EVALUATOR</option>
                </select>
              </label>
              <label className="field">
                <span className="field__label">语言</span>
                <select value={language} onChange={(event) => {
                  const nextLanguage = event.target.value as typeof language;
                  setLanguage(nextLanguage);
                  setDraftTitle(nextLanguage === 'zh-CN' ? '我的可复用经验' : 'My reusable experience');
                  clearDeliveryBinding();
                }}>
                  <option value="zh-CN">中文</option>
                  <option value="en">English</option>
                </select>
              </label>
              <label className="field">
                <span className="field__label">标题</span>
                <input value={draftTitle} readOnly />
              </label>
              <label className="field">
                <span className="field__label">摘要 / 核心表述</span>
                <textarea value={draftSummary} readOnly />
              </label>
            </div>
            <p className="route__why">
              这份草稿将绑定当前路线的 {decision?.supporting_statement_ids?.length ?? 0} 条证据引用。
            </p>
            <button className="btn btn--primary" disabled={!canSaveDraft || draftBusy} onClick={() => void saveDraft()}>
              保存并生成私有预览
            </button>
            {deliveryPreview ? (
              <div data-testid="m5-live-preview">
                <DeliveryPreview
                  preview={deliveryPreview}
                  onPrivateDownload={() => {
                    void api.exportDraft(deliveryPreview.route_draft_id)
                      .then(() => setExported(true))
                      .catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
                  }}
                  onExternalExport={approval ? () => {
                    void api.exportDraft(deliveryPreview.route_draft_id, approval.approval_id)
                      .then(() => setExported(true))
                      .catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
                  } : undefined}
                />
                {exported ? <p className="notice notice--ok">三种格式已生成。</p> : null}
              </div>
            ) : null}
          </section>
          <M5ReviewPanel
          workspace={panelView}
          onResolveFinding={(findingId: string, action: M5PrivacyAction) =>
            void run(() => api.resolveFinding(assetId, findingId, action))
          }
          onApprove={(binding: M5ApprovalAction) => {
            void api
              .approve(assetId, binding)
              .then((saved) => setApproval(saved))
              .catch((cause) =>
                setError(cause instanceof Error ? cause.message : String(cause)),
              );
          }}
          onCanonicalEdit={onCanonicalEdit}
        />
        </>
      ) : null}
    </section>
  );
}
