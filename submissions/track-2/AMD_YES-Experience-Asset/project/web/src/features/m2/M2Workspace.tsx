import { useEffect, useMemo, useRef, useState } from 'react';
import { Badge, Mono } from '../../components/primitives';
import { AssetHandoff } from '../../shell/AssetHandoff';
import { Working } from '../../shell/Working';
import { CriticalMomentMap } from './CriticalMomentMap';
import {
  LiveM2Api,
  M2ApiError,
  type CurrentM1Version,
  type M2Api,
  type M2Workspace as Workspace,
} from './api';

const KEY = 'experience-asset.m1.active-asset-id';

type Props = {
  apiBaseUrl?: string;
  storage?: Storage;
  api?: M2Api;
  autosaveDelayMs?: number;
  onStatusChange?: () => void;
};

export function M2Workspace({apiBaseUrl = '', storage = window.localStorage, api: injectedApi, autosaveDelayMs = 500, onStatusChange}: Props) {
  const liveApi = useMemo(() => new LiveM2Api(apiBaseUrl), [apiBaseUrl]);
  const api = injectedApi ?? liveApi;
  const [assetId, setAssetId] = useState(() => new URLSearchParams(location.search).get('asset') ?? storage.getItem(KEY) ?? '');
  const [currentM1, setCurrentM1] = useState<CurrentM1Version | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const workspaceRef = useRef<Workspace | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const draftsRef = useRef(drafts);
  const [criticalityDrafts, setCriticalityDrafts] = useState<
    Record<string, 'AGENT_PROPOSED' | 'USER_CONFIRMED' | 'UNRESOLVED'>
  >({});
  const criticalityDraftsRef = useRef(criticalityDrafts);
  const dirtyTitleIdsRef = useRef(new Set<string>());
  const dirtyCriticalityIdsRef = useRef(new Set<string>());
  const savingRef = useRef(false);
  const queuedRef = useRef(false);
  const recoveryBlockedRef = useRef(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const acknowledge = (next: Workspace, preserveDraft = false) => {
    workspaceRef.current = next;
    setWorkspace(next);
    onStatusChange?.();
    if (!preserveDraft) {
      const titles = Object.fromEntries(next.artifact.moments.map(m => [m.moment_id, m.title]));
      const criticalities = Object.fromEntries(
        next.artifact.moments.map(m => [m.moment_id, m.criticality_status]),
      );
      draftsRef.current = titles; setDrafts(titles); setDirty(false);
      criticalityDraftsRef.current = criticalities;
      setCriticalityDrafts(criticalities);
      dirtyTitleIdsRef.current.clear();
      dirtyCriticalityIdsRef.current.clear();
      recoveryBlockedRef.current = false;
    }
  };
  const mayDiscardDraft = () => !dirty || window.confirm('存在尚未保存的编辑，确定要放弃并继续吗？');
  const clearWorkspace = () => {
    workspaceRef.current = null;
    setWorkspace(null);
    draftsRef.current = {};
    setDrafts({});
    criticalityDraftsRef.current = {};
    setCriticalityDrafts({});
    dirtyTitleIdsRef.current.clear();
    dirtyCriticalityIdsRef.current.clear();
    recoveryBlockedRef.current = false;
    setDirty(false);
  };
  const load = async () => {
    if (!assetId || !mayDiscardDraft()) return;
    setBusy(true); setError('');
    try {
      setCurrentM1(await api.getCurrentM1Version(assetId));
      try {
        acknowledge(await api.get(assetId));
      } catch (reason) {
        if (reason instanceof M2ApiError && reason.status === 404) {
          clearWorkspace();
        } else {
          throw reason;
        }
      }
      storage.setItem(KEY, assetId);
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : '载入失败'); }
    finally { setBusy(false); }
  };
  useEffect(() => {
    void load();
    // Restore is intentionally mount-only. Later asset changes require the
    // explicit reload action so a dirty draft is never discarded implicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async (): Promise<void> => {
    const acknowledged = workspaceRef.current;
    if (!acknowledged || recoveryBlockedRef.current) return;
    if (savingRef.current) { queuedRef.current = true; return; }
    savingRef.current = true; setSaving(true); setError('');
    const sentDrafts = draftsRef.current;
    const sentCriticalities = criticalityDraftsRef.current;
    const sentCriticalityIds = new Set(dirtyCriticalityIdsRef.current);
    try {
      const next = await api.edit(acknowledged.artifact.asset_id, acknowledged.artifact.artifact_id,
        acknowledged.artifact.moments.map(m => {
          const criticality = sentCriticalities[m.moment_id];
          return {
            moment_id: m.moment_id,
            title: sentDrafts[m.moment_id],
            ...(!sentCriticalityIds.has(m.moment_id) || criticality === 'AGENT_PROPOSED'
              ? {}
              : {criticality_status: criticality}),
          };
        }));
      const changedDuringSave = draftsRef.current !== sentDrafts
        || criticalityDraftsRef.current !== sentCriticalities;
      if (criticalityDraftsRef.current === sentCriticalities) {
        sentCriticalityIds.forEach(id => dirtyCriticalityIdsRef.current.delete(id));
      }
      acknowledge(next, changedDuringSave);
      if (changedDuringSave) queuedRef.current = true;
    } catch (reason) {
      setDirty(true);
      if (reason instanceof M2ApiError && reason.status === 409 && acknowledged) {
        recoveryBlockedRef.current = true;
        queuedRef.current = false;
        try {
          const latest = await api.get(acknowledged.artifact.asset_id);
          const latestIds = new Set(latest.artifact.moments.map(moment => moment.moment_id));
          const draftIds = Object.keys(draftsRef.current);
          if (latest.is_current && draftIds.every(id => latestIds.has(id)) && latestIds.size === draftIds.length) {
            const rebasedDrafts = Object.fromEntries(
              latest.artifact.moments.map(moment => [
                moment.moment_id,
                dirtyTitleIdsRef.current.has(moment.moment_id)
                  ? draftsRef.current[moment.moment_id]
                  : moment.title,
              ]),
            );
            draftsRef.current = rebasedDrafts;
            setDrafts(rebasedDrafts);
            const rebasedCriticalities = Object.fromEntries(
              latest.artifact.moments.map(moment => [
                moment.moment_id,
                dirtyCriticalityIdsRef.current.has(moment.moment_id)
                  ? criticalityDraftsRef.current[moment.moment_id]
                  : moment.criticality_status,
              ]),
            );
            criticalityDraftsRef.current = rebasedCriticalities;
            setCriticalityDrafts(rebasedCriticalities);
            acknowledge(latest, true);
            recoveryBlockedRef.current = false;
            queuedRef.current = true;
            setError('检测到远端版本更新，已保留本地编辑并自动重试。');
          } else if (!latest.is_current) {
            setError('M1 已变化，当前 M2 失效；本地编辑仍保留。复制内容，或重新载入并确认放弃草稿。');
          } else {
            setError('版本结构已变化；本地编辑仍保留，请复制后再重新载入。');
          }
        } catch (reloadReason) {
          setError(reloadReason instanceof Error ? reloadReason.message : '版本冲突且载入失败');
        }
      } else {
        setError(reason instanceof Error ? reason.message : '自动保存失败');
      }
    } finally {
      savingRef.current = false; setSaving(false);
      if (queuedRef.current) { queuedRef.current = false; void save(); }
    }
  };
  useEffect(() => {
    if (!dirty || !workspace?.is_current) return;
    const timer = window.setTimeout(() => void save(), autosaveDelayMs);
    return () => window.clearTimeout(timer);
    // save reads the current acknowledged/draft refs and serializes itself.
    // Recreating the timer for each render would break the in-flight queue.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drafts, criticalityDrafts, dirty, workspace?.artifact.artifact_id, workspace?.is_current, autosaveDelayMs]);

  const create = async () => {
    if (!assetId || !mayDiscardDraft()) return;
    setBusy(true); setError('');
    try {
      const latestM1 = await api.getCurrentM1Version(assetId);
      setCurrentM1(latestM1);
      acknowledge(await api.create(assetId, latestM1.version_id));
      storage.setItem(KEY, assetId);
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : '生成失败'); }
    finally { setBusy(false); }
  };
  const changeTitle = (id: string, title: string) => {
    const next = {...draftsRef.current, [id]: title};
    dirtyTitleIdsRef.current.add(id);
    draftsRef.current = next; setDrafts(next); setDirty(true);
  };
  const changeCriticality = (
    id: string,
    criticality: 'USER_CONFIRMED' | 'UNRESOLVED',
  ) => {
    const next = {...criticalityDraftsRef.current, [id]: criticality};
    dirtyCriticalityIdsRef.current.add(id);
    criticalityDraftsRef.current = next;
    setCriticalityDrafts(next);
    setDirty(true);
  };
  const confirm = async () => {
    if (!workspace || dirty || saving) return;
    setBusy(true); setError('');
    const completeWithGaps = workspace.artifact.moments.some(
      m => m.temporal_status !== 'KNOWN' || m.criticality_status === 'UNRESOLVED',
    );
    try { acknowledge(await api.confirm(assetId, workspace.artifact.artifact_id, completeWithGaps)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '确认失败'); }
    finally { setBusy(false); }
  };

  return <section className="m1-workspace m2-workspace" data-testid="m2-workspace">
    <div className="panel"><h2>Critical Moment Map</h2>
      <AssetHandoff assetId={assetId} upstream="M1" testId="m2-no-asset" />
      <label className="form-field"><span>Asset ID</span><input value={assetId} onChange={e => setAssetId(e.target.value)} /></label>
      <p data-testid="m2-current-m1-version">
        最近自动读取的 M1 版本（生成时刷新）：{' '}
        <Mono>{currentM1?.version_id ?? '尚未读取'}</Mono>{' '}
        {currentM1 ? <Badge tone="info">{currentM1.milestone_state}</Badge> : null}
      </p>
      <div className="row"><button className="btn" disabled={busy || saving || !assetId} onClick={() => void load()}>重新载入</button><button className="btn btn--primary" disabled={busy || saving || !assetId} onClick={() => void create()}>{busy ? '处理中…' : (workspace ? '按最新 M1 重新生成' : '从 M1 生成')}</button></div>
      {busy ? <Working label="正在处理当前 M2 操作" testId="m2-working" /> : null}
      {error ? <div className="notice notice--danger" role="alert">{error}</div> : null}
    </div>
    {workspace ? <>{!workspace.is_current ? <div className="notice notice--danger">该 M2 已因依赖的 M1 更正而失效，请重新生成。</div> : null}<CriticalMomentMap artifact={workspace.artifact} />
      {workspace.is_current ? <div className="panel"><h3>编辑并自动保存</h3>{workspace.artifact.moments.map((moment, index) => <div className="form-field" key={moment.moment_id}><label><span>#{index + 1} · 来源 {moment.source_statement_ids.join(', ')}</span><input value={drafts[moment.moment_id] ?? moment.title} onChange={e => changeTitle(moment.moment_id, e.target.value)} /></label><label><span>这个时刻是否确实改变了经历走向？</span><select aria-label={`关键性 #${index + 1}`} value={criticalityDrafts[moment.moment_id] ?? moment.criticality_status} onChange={e => changeCriticality(moment.moment_id, e.target.value as 'USER_CONFIRMED' | 'UNRESOLVED')}><option value="AGENT_PROPOSED" disabled>待用户决定</option><option value="USER_CONFIRMED">确认是关键时刻</option><option value="UNRESOLVED">暂时无法确认</option></select></label></div>)}<button className="btn btn--primary" disabled={busy || dirty || saving || workspace.artifact.moments.some(moment => moment.criticality_status === 'AGENT_PROPOSED')} onClick={() => void confirm()}>确认 Critical Moment Map</button></div> : null}
    </> : null}
  </section>;
}
