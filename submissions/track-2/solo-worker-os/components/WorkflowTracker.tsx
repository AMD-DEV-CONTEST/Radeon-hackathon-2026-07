'use client';

import { useEffect, useState, useCallback } from 'react';
import { useLang } from './LanguageProvider';
import {
  WORKFLOW_STAGES, STAGE_ORDER, STAGE_COLOR_CLASSES,
  isStageComplete, nextStage,
  type ChecksMap,
} from '@/lib/workflow';

interface Props { projectId: string }

export default function WorkflowTracker({ projectId }: Props) {
  const { t } = useLang();
  const wf = t.workflow;

  const [stage, setStage] = useState('kickoff');
  const [checks, setChecks] = useState<ChecksMap>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/workflow/${projectId}`);
      if (!res.ok) throw new Error('Failed to load workflow');
      const d = await res.json() as { stage: string; checks: ChecksMap };
      setStage(d.stage);
      setChecks(d.checks);
    } catch {
      setError(t.workflow.title + ' load failed');
    } finally {
      setLoading(false);
    }
  }, [projectId, t.workflow.title]);

  useEffect(() => { void load(); }, [load]);

  async function toggle(checkKey: string, checked: boolean) {
    setSaving(true);
    setError(null);
    // Optimistic update — save previous value for rollback
    const prev = checks[checkKey];
    setChecks((p) => ({ ...p, [checkKey]: checked }));
    try {
      const res = await fetch(`/api/workflow/${projectId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ checkKey, checked }),
      });
      if (!res.ok) throw new Error('Save failed');
    } catch {
      // Rollback on failure
      setChecks((p) => ({ ...p, [checkKey]: prev }));
      setError('Save failed — please retry');
    } finally {
      setSaving(false);
    }
  }

  async function advance() {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`/api/workflow/${projectId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ advanceStage: true }),
      });
      if (!res.ok) throw new Error('Advance failed');
      const d = await res.json() as { stage: string; checks: ChecksMap };
      setStage(d.stage);
      setChecks(d.checks); // Sync checks from server (was missing before)
    } catch {
      setError('Advance failed — please retry');
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="glass rounded-2xl p-6">
        <div className="h-5 w-40 animate-pulse rounded-lg bg-gray-200 dark:bg-white/[0.05]" />
        <div className="mt-4 flex gap-2">
          {[1,2,3,4,5,6].map((i) => <div key={i} className="h-8 flex-1 animate-pulse rounded-lg bg-gray-200 dark:bg-white/[0.04]" />)}
        </div>
      </div>
    );
  }

  const currentIdx = STAGE_ORDER.indexOf(stage);
  const currentStageDef = WORKFLOW_STAGES.find((s) => s.key === stage);
  if (!currentStageDef) {
    return (
      <div className="glass rounded-2xl p-6">
        <p className="text-[13px] text-gray-400 dark:text-white/35">Workflow data unavailable.</p>
      </div>
    );
  }
  const canAdvance = isStageComplete(stage, checks) && nextStage(stage) !== null;
  const progressPct = Math.round(((currentIdx + 1) / STAGE_ORDER.length) * 100);
  const nextStageDef = WORKFLOW_STAGES[currentIdx + 1];

  return (
    <div className="glass rounded-2xl p-6 space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-[15px] font-bold text-gray-800 dark:text-white/80">{wf.title}</h2>
        {saving && <span className="text-[11px] text-gray-400 dark:text-white/30 animate-pulse-soft">{wf.saving}</span>}
      </div>

      {error && (
        <div className="rounded-lg border border-red-400/20 bg-red-400/5 px-3 py-2 text-[12px] text-red-300">
          {error}
        </div>
      )}

      {/* Stage stepper */}
      <div className="flex items-center gap-0 overflow-x-auto">
        {WORKFLOW_STAGES.map((s, i) => {
          const done   = i < currentIdx;
          const active = i === currentIdx;
          const colors = STAGE_COLOR_CLASSES[s.color];
          const stageLabel = wf.stages[s.key as keyof typeof wf.stages] ?? s.label;
          return (
            <div key={s.key} className="flex items-center flex-shrink-0">
              <div className="flex flex-col items-center gap-1">
                <div
                  className={`flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-bold transition-all ${
                    done
                      ? 'bg-emerald-400/20 text-emerald-300 ring-1 ring-emerald-400/30'
                      : active
                      ? `${colors.bg} ${colors.text} ring-1 ${colors.ring}`
                      : 'bg-gray-100 dark:bg-white/[0.04] text-gray-400 dark:text-white/25'
                  }`}
                >
                  {done ? '✓' : i + 1}
                </div>
                <span className={`text-[10px] font-semibold whitespace-nowrap ${
                  done ? 'text-emerald-300/70' : active ? colors.text : 'text-gray-400 dark:text-white/25'
                }`}>
                  {stageLabel}
                </span>
              </div>
              {i < WORKFLOW_STAGES.length - 1 && (
                <div className={`mx-1 mb-4 h-px flex-1 min-w-[16px] transition-all ${
                  done ? 'bg-emerald-400/30' : 'bg-gray-200 dark:bg-white/[0.06]'
                }`} />
              )}
            </div>
          );
        })}
      </div>

      {/* Progress bar */}
      <div className="h-1 w-full rounded-full bg-gray-200 dark:bg-white/[0.06]">
        <div
          className="h-1 rounded-full bg-amber-400 transition-all duration-700"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Current stage checklist */}
      <div className="space-y-2">
        <p className="text-[12px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">
          {wf.stages[currentStageDef.key as keyof typeof wf.stages] ?? currentStageDef.label}
          {' — '}
          {wf.checklist}
        </p>
        {currentStageDef.checks.map((c) => {
          const fullKey = `${stage}:${c.key}`;
          const checked = !!checks[fullKey];
          const checkLabel = wf.checks[c.key as keyof typeof wf.checks] ?? c.label;
          return (
            <label key={c.key} className="flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.03]">
              <button
                type="button"
                onClick={() => void toggle(fullKey, !checked)}
                className={`flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-md border transition-all duration-200 ${
                  checked
                    ? 'border-emerald-400/50 bg-emerald-400/20 text-emerald-300'
                    : 'border-gray-200 dark:border-white/[0.1] bg-gray-50 dark:bg-white/[0.03] text-transparent hover:border-gray-300 dark:hover:border-white/20'
                }`}
              >
                {checked && (
                  <svg className="h-3 w-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="m2 6 3 3 5-5" />
                  </svg>
                )}
              </button>
              <span className={`text-[13px] transition-colors ${checked ? 'text-gray-400 dark:text-white/35 line-through' : 'text-gray-700 dark:text-white/70'}`}>
                {checkLabel}
              </span>
            </label>
          );
        })}
      </div>

      {/* Advance button */}
      {nextStage(stage) && (
        <button
          type="button"
          onClick={() => void advance()}
          disabled={!canAdvance || saving}
          className="w-full rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.03] py-2.5 text-[13px] font-semibold text-gray-500 dark:text-white/50 transition-all duration-300 hover:border-emerald-400/20 hover:bg-emerald-400/5 hover:text-emerald-300 disabled:cursor-not-allowed disabled:opacity-30"
        >
          {canAdvance && nextStageDef
            ? `${wf.advanceTo} "${wf.stages[nextStageDef.key as keyof typeof wf.stages] ?? nextStageDef.label}" →`
            : wf.completeToAdvance}
        </button>
      )}

      {stage === 'paid' && (
        <div className="rounded-xl border border-emerald-400/20 bg-emerald-400/5 px-4 py-3 text-center">
          <p className="text-[13px] font-semibold text-emerald-300">{wf.projectComplete}</p>
        </div>
      )}
    </div>
  );
}
