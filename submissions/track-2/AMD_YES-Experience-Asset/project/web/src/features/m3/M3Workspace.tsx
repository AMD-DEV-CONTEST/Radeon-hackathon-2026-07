import { useEffect, useMemo, useState } from 'react';
import { Badge, Mono } from '../../components/primitives';
import { AssetHandoff } from '../../shell/AssetHandoff';
import { Working } from '../../shell/Working';
import { DecisionEvidenceLedger } from './DecisionEvidenceLedger';
import {
  LiveM3Api,
  M3ApiError,
  type M3Api,
  type M3UpstreamIdentity,
} from './api';
import type { M3WorkspaceV1 } from './types';

const KEY = 'experience-asset.m1.active-asset-id';

type Props = {
  apiBaseUrl?: string;
  api?: M3Api;
  storage?: Storage;
  onStatusChange?: () => void;
};

export function M3Workspace({
  apiBaseUrl = '',
  api: supplied,
  storage = window.localStorage,
  onStatusChange,
}: Props) {
  const live = useMemo(() => new LiveM3Api(apiBaseUrl), [apiBaseUrl]);
  const api = supplied ?? live;
  const [assetId, setAssetId] = useState(
    () => new URLSearchParams(location.search).get('asset') ?? storage.getItem(KEY) ?? '',
  );
  const [upstream, setUpstream] = useState<M3UpstreamIdentity | null>(null);
  const [workspace, setWorkspace] = useState<M3WorkspaceV1 | null>(null);
  const [error, setError] = useState('');
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const applyWorkspace = (next: M3WorkspaceV1) => {
    setWorkspace(next);
    onStatusChange?.();
  };

  const load = async () => {
    if (!assetId) return;
    setBusy(true);
    setDrafts({});
    setError('');
    try {
      const currentUpstream = await api.getCurrentUpstream(assetId);
      setUpstream(currentUpstream);
      try {
        applyWorkspace(await api.get(assetId));
      } catch (reason) {
        if (reason instanceof M3ApiError && reason.status === 404) {
          setWorkspace(null);
        } else {
          throw reason;
        }
      }
      storage.setItem(KEY, assetId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '载入失败');
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
          currentUpstream.m2_artifact_id,
          currentUpstream.canonical_version_id,
        ),
      );
      storage.setItem(KEY, assetId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '生成失败');
    } finally {
      setBusy(false);
    }
  };

  const regenerate = async () => {
    if (!workspace) return;
    setBusy(true);
    setError('');
    try {
      const currentUpstream = await api.getCurrentUpstream(assetId);
      setUpstream(currentUpstream);
      applyWorkspace(
        await api.regenerate(
          assetId,
          currentUpstream.m2_artifact_id,
          currentUpstream.canonical_version_id,
          workspace.artifact.artifact_id,
        ),
      );
      setDrafts({});
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '重新生成失败');
    } finally {
      setBusy(false);
    }
  };

  const save = async (
    statementId: string,
    action: 'CONFIRM' | 'MARK_UNRESOLVED',
  ) => {
    if (!workspace) return;
    const original = workspace.artifact.entries
      .flatMap(entry => entry.statements)
      .find(statement => statement.statement_id === statementId);
    if (!original) return;
    try {
      applyWorkspace(
        await api.edit(assetId, workspace.artifact.artifact_id, [{
          statement_id: statementId,
          text: drafts[statementId] ?? original.text,
          user_action: action,
          ...(action === 'MARK_UNRESOLVED'
            ? {unresolved_reason: '用户明确标记为待补充'}
            : {}),
        }]),
      );
      setDrafts(current => {
        const next = {...current};
        delete next[statementId];
        return next;
      });
      setError('');
    } catch (reason) {
      if (reason instanceof M3ApiError && reason.status === 409) setWorkspace(null);
      setError(reason instanceof Error ? reason.message : '保存失败');
    }
  };

  const confirm = async (withGaps: boolean) => {
    if (!workspace) return;
    try {
      applyWorkspace(
        await api.confirm(assetId, workspace.artifact.artifact_id, withGaps),
      );
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '确认失败');
    }
  };

  return (
    <section data-testid="m3-workspace">
      <div className="panel">
        <h2>M3 Decision and Evidence Ledger</h2>
        <AssetHandoff assetId={assetId} upstream="M2" testId="m3-no-asset" />
        <label className="form-field">
          <span>Asset ID</span>
          <input value={assetId} onChange={event => setAssetId(event.target.value)} />
        </label>
        <p data-testid="m3-current-upstream">
          最近自动读取的 M2：{' '}
          <Mono>{upstream?.m2_artifact_id ?? '尚未读取'}</Mono>{' '}
          {upstream ? <Badge tone="info">{upstream.m2_state}</Badge> : null}
        </p>
        <p>
          当前规范版本：{' '}
          <Mono>{upstream?.canonical_version_id ?? '尚未读取'}</Mono>
        </p>
        <div className="row">
          <button className="btn" disabled={busy || !assetId} onClick={() => void load()}>
            重新载入
          </button>
          <button
            className="btn btn--primary"
            disabled={busy || !assetId || workspace !== null}
            onClick={() => void create()}
          >
            {busy ? '处理中…' : '从当前 M2 生成'}
          </button>
          <button
            className="btn"
            disabled={busy || !workspace?.allowed_actions.includes('REGENERATE')}
            onClick={() => void regenerate()}
          >
            重新生成
          </button>
        </div>
        {busy ? <Working label="正在处理当前 M3 操作" testId="m3-working" /> : null}
        {error ? <div className="notice notice--danger" role="alert">{error}</div> : null}
      </div>
      {workspace ? (
        <>
          <DecisionEvidenceLedger
            workspace={workspace}
            drafts={drafts}
            onStatementTextChange={(id, text) =>
              setDrafts(current => ({...current, [id]: text}))
            }
            onStatementAction={(id, action) => void save(id, action)}
          />
          <button
            className="btn btn--primary"
            disabled={!workspace.allowed_actions.includes('CONFIRM')}
            onClick={() => void confirm(false)}
          >
            确认账本
          </button>
          <button
            className="btn"
            disabled={!workspace.allowed_actions.includes('CONFIRM')}
            onClick={() => void confirm(true)}
          >
            带缺口确认
          </button>
        </>
      ) : null}
    </section>
  );
}
