import { useEffect, useMemo, useState } from 'react';
import { Badge, Mono } from '../../components/primitives';
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
};

export function M3Workspace({
  apiBaseUrl = '',
  api: supplied,
  storage = window.localStorage,
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

  const load = async () => {
    if (!assetId) return;
    setBusy(true);
    setDrafts({});
    setError('');
    try {
      const currentUpstream = await api.getCurrentUpstream(assetId);
      setUpstream(currentUpstream);
      try {
        setWorkspace(await api.get(assetId));
      } catch (reason) {
        if (reason instanceof M3ApiError && reason.status === 404) {
          setWorkspace(null);
        } else {
          throw reason;
        }
      }
      storage.setItem(KEY, assetId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not load the ledger.');
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
      setWorkspace(
        await api.create(
          assetId,
          currentUpstream.m2_artifact_id,
          currentUpstream.canonical_version_id,
        ),
      );
      storage.setItem(KEY, assetId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not generate the ledger.');
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
      setWorkspace(
        await api.regenerate(
          assetId,
          currentUpstream.m2_artifact_id,
          currentUpstream.canonical_version_id,
          workspace.artifact.artifact_id,
        ),
      );
      setDrafts({});
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not regenerate the ledger.');
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
      setWorkspace(
        await api.edit(assetId, workspace.artifact.artifact_id, [{
          statement_id: statementId,
          text: drafts[statementId] ?? original.text,
          user_action: action,
          ...(action === 'MARK_UNRESOLVED'
            ? {unresolved_reason: 'Marked by the user as needing more evidence'}
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
      setError(reason instanceof Error ? reason.message : 'Could not save the ledger.');
    }
  };

  const confirm = async (withGaps: boolean) => {
    if (!workspace) return;
    try {
      setWorkspace(
        await api.confirm(assetId, workspace.artifact.artifact_id, withGaps),
      );
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not confirm the ledger.');
    }
  };

  return (
    <section data-testid="m3-workspace">
      <div className="panel">
        <h2>M3 Decision and Evidence Ledger</h2>
        <label className="form-field">
          <span>Asset ID</span>
          <input value={assetId} onChange={event => setAssetId(event.target.value)} />
        </label>
        <p data-testid="m3-current-upstream">
          Latest M2 read by the system:{' '}
          <Mono>{upstream?.m2_artifact_id ?? 'Not loaded'}</Mono>{' '}
          {upstream ? <Badge tone="info">{upstream.m2_state}</Badge> : null}
        </p>
        <p>
          Current canonical version:{' '}
          <Mono>{upstream?.canonical_version_id ?? 'Not loaded'}</Mono>
        </p>
        <div className="row">
          <button className="btn" disabled={busy || !assetId} onClick={() => void load()}>
            Reload
          </button>
          <button
            className="btn btn--primary"
            disabled={busy || !assetId || workspace !== null}
            onClick={() => void create()}
          >
            Create from current M2
          </button>
          <button
            className="btn"
            disabled={busy || !workspace?.allowed_actions.includes('REGENERATE')}
            onClick={() => void regenerate()}
          >
            Regenerate
          </button>
        </div>
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
            Confirm ledger
          </button>
          <button
            className="btn"
            disabled={!workspace.allowed_actions.includes('CONFIRM')}
            onClick={() => void confirm(true)}
          >
            Confirm with visible gaps
          </button>
        </>
      ) : null}
    </section>
  );
}
