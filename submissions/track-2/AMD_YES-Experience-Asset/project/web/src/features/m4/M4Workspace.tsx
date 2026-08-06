import { useEffect, useMemo, useState } from 'react';
import { Badge, Mono } from '../../components/primitives';
import { AssetHandoff } from '../../shell/AssetHandoff';
import { Working } from '../../shell/Working';
import { InsightBoundaryMap } from './InsightBoundaryMap';
import { ReadinessGate } from './ReadinessGate';
import { DiscoveryPanel } from '../relation/DiscoveryPanel';
import { EvidenceCardPanel } from '../relation/EvidenceCardPanel';
import { deriveDiscoveryView } from '../relation/discoveryView';
import {
  LiveDiscoveryApi,
  type DiscoveryApi,
} from '../relation/api';
import type { RelationWorkspaceV1 } from '../relation/types';
import { deriveM4View } from './m4View';
import {
  LiveReadinessApi,
  type DiscoveryLock,
  type KnowledgeCardReadinessV1,
  type ReadinessApi,
} from './readiness';
import { LiveM4Api, M4ApiError, type M4Api, type M4UpstreamIdentity } from './api';
import type { M4WorkspaceV1 } from './types';

const KEY = 'experience-asset.m1.active-asset-id';

type Props = {
  apiBaseUrl?: string;
  api?: M4Api;
  readinessApi?: ReadinessApi;
  discoveryApi?: DiscoveryApi;
  storage?: Storage;
  onStatusChange?: () => void;
};

export function M4Workspace({
  apiBaseUrl = '',
  api: supplied,
  readinessApi: suppliedReadiness,
  discoveryApi: suppliedDiscovery,
  storage = window.localStorage,
  onStatusChange,
}: Props) {
  const live = useMemo(() => new LiveM4Api(apiBaseUrl), [apiBaseUrl]);
  const liveReadiness = useMemo(() => new LiveReadinessApi(apiBaseUrl), [apiBaseUrl]);
  const liveDiscovery = useMemo(() => new LiveDiscoveryApi(apiBaseUrl), [apiBaseUrl]);
  const api = supplied ?? live;
  const readinessApi = suppliedReadiness ?? liveReadiness;
  const discoveryApi = suppliedDiscovery ?? liveDiscovery;
  const [assetId, setAssetId] = useState(
    () => new URLSearchParams(location.search).get('asset') ?? storage.getItem(KEY) ?? '',
  );
  const [upstream, setUpstream] = useState<M4UpstreamIdentity | null>(null);
  const [workspace, setWorkspace] = useState<M4WorkspaceV1 | null>(null);
  const [error, setError] = useState('');
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [readiness, setReadiness] = useState<KnowledgeCardReadinessV1 | null>(null);
  const [lock, setLock] = useState<DiscoveryLock | null>(null);
  const [gateError, setGateError] = useState('');
  const [relation, setRelation] = useState<RelationWorkspaceV1 | null>(null);
  const [relationError, setRelationError] = useState('');

  const applyWorkspace = (next: M4WorkspaceV1) => {
    setWorkspace(next);
    onStatusChange?.();
  };

  const view = workspace ? deriveM4View(workspace) : null;

  // Both come from the backend on every refresh. Caching the lock across a
  // reload would let the UI keep offering a search the server has since
  // locked because the card moved on.
  const refreshGate = async (id: string) => {
    try {
      const [record, discovery] = await Promise.all([
        readinessApi.read(id),
        readinessApi.readDiscoveryLock(id),
      ]);
      setReadiness(record);
      setLock(discovery);
      try {
        setRelation(await discoveryApi.read(id));
      } catch {
        setRelation(null);
      }
    } catch (reason) {
      setGateError(reason instanceof Error ? reason.message : '读取就绪状态失败');
    }
  };

  const accept = async (action: 'CONFIRM' | 'ACCEPT_WITH_GAPS') => {
    if (!workspace?.map || !view) return;
    setBusy(true);
    setGateError('');
    try {
      await readinessApi.accept(assetId, {
        asset_id: assetId,
        expected_artifact_id: workspace.map.artifact_id,
        expected_canonical_version_id: workspace.canonical_version_id,
        user_action: action,
        ...(action === 'ACCEPT_WITH_GAPS'
          ? {
              accepted_gap_statement_ids: view.visibleGaps.map(
                (statement) => statement.statement_id,
              ),
            }
          : {}),
      });
      await load();
    } catch (reason) {
      setGateError(reason instanceof Error ? reason.message : '接受失败');
      await refreshGate(assetId);
    } finally {
      setBusy(false);
    }
  };

  const decide = async (action: 'CONFIRM' | 'DECLINE') => {
    const candidate = deriveDiscoveryView(relation).candidate;
    if (!candidate || !readiness) return;
    setBusy(true);
    setRelationError('');
    try {
      setRelation(
        await discoveryApi.decide(assetId, candidate.candidate_id, {
          decision_id: crypto.randomUUID(),
          candidate_id: candidate.candidate_id,
          current_asset_id: assetId,
          current_version_id: readiness.version_id,
          current_knowledge_card_hash: readiness.knowledge_card_hash,
          related_asset_id: candidate.related_asset_id,
          user_action: action,
          decided_at: new Date().toISOString(),
        }),
      );
    } catch (reason) {
      setRelationError(reason instanceof Error ? reason.message : '决定失败');
      // A refusal means the backend saw a binding this view no longer matches,
      // so the view is re-read rather than left showing the state that was
      // just rejected.
      try {
        setRelation(await discoveryApi.read(assetId));
      } catch {
        /* keep the message already surfaced */
      }
    } finally {
      setBusy(false);
    }
  };

  const search = async () => {
    if (!readiness) return;
    setBusy(true);
    setRelationError('');
    try {
      setRelation(
        await discoveryApi.start(assetId, {
          asset_id: assetId,
          current_version_id: readiness.version_id,
          knowledge_card_version_id: readiness.version_id,
          knowledge_card_hash: readiness.knowledge_card_hash,
          scope: 'CROSS_ASSET_SUMMARY',
        }),
      );
    } catch (reason) {
      setRelationError(reason instanceof Error ? reason.message : '查找失败');
      // Re-read rather than assume: the server may have moved the card out
      // from under this view, and that is exactly the case the message must
      // not paper over.
      await refreshGate(assetId);
    } finally {
      setBusy(false);
    }
  };

  const load = async () => {
    if (!assetId) return;
    setBusy(true);
    setDrafts({});
    setError('');
    try {
      const currentUpstream = await api.getCurrentUpstream(assetId);
      setUpstream(currentUpstream);
      applyWorkspace(await api.get(assetId));
      await refreshGate(assetId);
      storage.setItem(KEY, assetId);
    } catch (reason) {
      if (reason instanceof M4ApiError && reason.status === 404) setWorkspace(null);
      else setError(reason instanceof Error ? reason.message : '载入失败');
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    void load();
    // Restore is intentionally mount-only. Asset changes use explicit reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const create = async () => {
    if (!assetId) return;
    setBusy(true);
    setError('');
    try {
      const currentUpstream = await api.getCurrentUpstream(assetId);
      setUpstream(currentUpstream);
      applyWorkspace(
        await api.create(
          assetId,
          currentUpstream.m3_artifact_id,
          currentUpstream.canonical_version_id,
        ),
      );
      storage.setItem(KEY, assetId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '生成失败');
      // A stopped run leaves the workspace readable; reload so the terminal
      // state is shown rather than the pre-run view the user was looking at.
      await reload();
    } finally {
      setBusy(false);
    }
  };

  const reload = async () => {
    try {
      applyWorkspace(await api.get(assetId));
    } catch {
      /* keep the error already surfaced */
    }
  };

  const regenerate = async () => {
    if (!workspace?.map) return;
    setBusy(true);
    setError('');
    try {
      const currentUpstream = await api.getCurrentUpstream(assetId);
      setUpstream(currentUpstream);
      applyWorkspace(
        await api.regenerate(
          assetId,
          currentUpstream.m3_artifact_id,
          currentUpstream.canonical_version_id,
          workspace.map.artifact_id,
        ),
      );
      setDrafts({});
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '重新生成失败');
      await reload();
    } finally {
      setBusy(false);
    }
  };

  const save = async (statementId: string) => {
    if (!workspace?.map) return;
    const draft = drafts[statementId];
    if (draft === undefined) return;
    try {
      applyWorkspace(
        await api.edit(assetId, workspace.map.artifact_id, [
          { statement_id: statementId, text: draft },
        ]),
      );
      setDrafts((current) => {
        const next = { ...current };
        delete next[statementId];
        return next;
      });
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存失败');
      if (reason instanceof M4ApiError && reason.status === 409) await reload();
    }
  };

  const markGap = async (statementId: string) => {
    if (!workspace?.map) return;
    try {
      applyWorkspace(
        await api.edit(assetId, workspace.map.artifact_id, [
          {
            statement_id: statementId,
            is_visible_gap: true,
            gap_reason: '用户明确标记为缺口',
          },
        ]),
      );
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '标记缺口失败');
    }
  };

  return (
    <section data-testid="m4-workspace">
      <div className="panel">
        <h2>M4 Insight and Boundary Map</h2>
        <AssetHandoff assetId={assetId} upstream="M3" testId="m4-no-asset" />
        <label className="form-field">
          <span>Asset ID</span>
          <input value={assetId} onChange={(event) => setAssetId(event.target.value)} />
        </label>
        <p data-testid="m4-current-upstream">
          最近自动读取的 M3：<Mono>{upstream?.m3_artifact_id ?? '尚未读取'}</Mono>{' '}
          {upstream ? <Badge tone="info">{upstream.m3_state}</Badge> : null}
        </p>
        <p>
          当前规范版本：<Mono>{upstream?.canonical_version_id ?? '尚未读取'}</Mono>
        </p>
        <div className="row">
          <button className="btn" disabled={busy || !assetId} onClick={() => void load()}>
            重新载入
          </button>
          {/* Enabled when no workspace is loaded as well as when the loaded one
              has no map: a 404 on the workspace read is exactly the state
              generation exists to leave, so disabling here would strand the
              user on the one screen where create is the only useful action. */}
          <button
            className="btn btn--primary"
            disabled={busy || !assetId || (view !== null && !view.canCreate)}
            onClick={() => void create()}
          >
            {busy ? '处理中…' : '从当前 M3 生成'}
          </button>
          <button
            className="btn"
            disabled={busy || view?.canRegenerate !== true}
            onClick={() => void regenerate()}
          >
            重新生成
          </button>
        </div>
        {busy ? <Working label="正在处理当前 M4 操作" testId="m4-working" /> : null}
        {error ? (
          <div className="notice notice--danger" role="alert" data-testid="m4-error">
            {error}
          </div>
        ) : null}
      </div>
      {workspace && view ? (
        <ReadinessGate
          view={view}
          readiness={readiness}
          lock={lock}
          busy={busy}
          error={gateError}
          onAccept={(action) => void accept(action)}
        />
      ) : null}
      {workspace && view ? (
        <DiscoveryPanel
          view={deriveDiscoveryView(relation)}
          busy={busy}
          error={relationError}
          onSearch={() => void search()}
          onDecide={(action) => void decide(action)}
        />
      ) : null}
      {/* Below the decision, never beside the candidate: showing historical
          detail before the confirmation would make that decision moot, since
          the user would already have read what they were deciding whether to
          read. The card exists only after a confirmation, so `evidence_card`
          is null until then and the panel renders nothing. */}
      {relation ? (
        <EvidenceCardPanel
          card={relation.evidence_card}
          currentCardHash={relation.readiness?.knowledge_card_hash ?? null}
        />
      ) : null}
      {workspace && view ? (
        <InsightBoundaryMap
          workspace={workspace}
          view={view}
          drafts={drafts}
          onStatementTextChange={(id, text) => setDrafts((current) => ({ ...current, [id]: text }))}
          onStatementSave={(id) => void save(id)}
          onMarkGap={(id) => void markGap(id)}
        />
      ) : null}
    </section>
  );
}
