'use client';

import { useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';

interface Props {
  projectId: string;
  initial: {
    client_name: string;
    project_type: string;
    budget: number | string;
    currency: string;
    deadline: string;
  };
  labels: {
    budget: string;
    deadline: string;
    clientName: string;
    projectType: string;
    currency: string;
    save: string;
    cancel: string;
    edit: string;
    daysLeft: string;
    overdue: string;
    dueToday: string;
    created: string;
  };
  createdAt: string;
  statusSlot?: React.ReactNode;
}

type EditMode = 'none' | 'client_name' | 'project_type' | 'budget' | 'deadline';

export default function ProjectEditFields({ projectId, initial, labels, createdAt, statusSlot }: Props) {
  const router = useRouter();
  const [editMode, setEditMode] = useState<EditMode>('none');
  const [saving, setSaving] = useState(false);
  const [values, setValues] = useState(initial);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    if (editMode !== 'none') {
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [editMode]);

  function startEdit(field: EditMode) {
    setEditMode(field);
    setError('');
  }

  function cancelEdit() {
    setEditMode('none');
    setError('');
    setValues(initial);
  }

  async function saveField(field: EditMode) {
    if (!field || field === 'none') return;
    setSaving(true);
    setError('');
    try {
      const payload: Record<string, unknown> = {};
      payload[field] = field === 'budget' ? Number(values[field]) : values[field as keyof typeof values];

      const res = await fetch(`/api/projects/${projectId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.error ?? 'Update failed');
      }
      setEditMode('none');
      setTimeout(() => { if (mountedRef.current) router.refresh(); }, 300);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed');
    }
    setSaving(false);
  }

  function handleKeyDown(e: React.KeyboardEvent, field: EditMode) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void saveField(field);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelEdit();
    }
  }

  // Calculate days left
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const deadlineDate = new Date(values.deadline);
  const diffMs = deadlineDate.getTime() - today.getTime();
  const days = Math.ceil(diffMs / 86400000);
  const overdue = days < 0;

  return (
    <>
      {/* Editable header fields */}
      <div className="relative flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          {/* Project type */}
          {editMode === 'project_type' ? (
            <div className="flex items-center gap-1.5">
              <input
                ref={inputRef}
                type="text"
                value={values.project_type}
                onChange={(e) => setValues((s) => ({ ...s, project_type: e.target.value }))}
                onKeyDown={(e) => handleKeyDown(e, 'project_type')}
                disabled={saving}
                className="glass focus-ring w-full max-w-md rounded-lg px-2 py-0.5 text-[12px] font-bold uppercase tracking-widest text-amber-600 dark:text-amber-300 placeholder:text-gray-400 dark:placeholder:text-white/25 focus:outline-none"
              />
              <SaveCancelButtons saving={saving} onSave={() => void saveField('project_type')} onCancel={cancelEdit} labels={labels} />
            </div>
          ) : (
            <button
              type="button"
              onClick={() => startEdit('project_type')}
              className="group/value inline-flex items-center gap-1 text-[12px] font-bold uppercase tracking-widest text-amber-300"
              title="Click to edit"
            >
              <span className="truncate">{values.project_type}</span>
              <EditPencil />
            </button>
          )}

          {/* Client name */}
          {editMode === 'client_name' ? (
            <div className="mt-1 flex items-center gap-1.5">
              <input
                ref={inputRef}
                type="text"
                value={values.client_name}
                onChange={(e) => setValues((s) => ({ ...s, client_name: e.target.value }))}
                onKeyDown={(e) => handleKeyDown(e, 'client_name')}
                disabled={saving}
                className="glass focus-ring w-full max-w-md rounded-lg px-2 py-0.5 text-2xl font-extrabold tracking-tight text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 focus:outline-none"
              />
              <SaveCancelButtons saving={saving} onSave={() => void saveField('client_name')} onCancel={cancelEdit} labels={labels} />
            </div>
          ) : (
            <button
              type="button"
              onClick={() => startEdit('client_name')}
              className="mt-1 group/value inline-flex items-center gap-1 text-2xl font-extrabold tracking-tight text-gray-900 dark:text-white"
              title="Click to edit"
            >
              <span className="truncate">{values.client_name}</span>
              <EditPencil />
            </button>
          )}
        </div>

        {/* Status badge + status buttons slot */}
        {statusSlot && (
          <div className="flex flex-wrap items-center gap-3">{statusSlot}</div>
        )}
      </div>

      {/* Editable stat cards */}
      <dl className="relative mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        {/* Budget — editable */}
        <StatCard label={labels.budget}>
          {editMode === 'budget' ? (
            <div className="flex items-center gap-1.5">
              <input
                ref={inputRef}
                type="number"
                value={String(values.budget)}
                onChange={(e) => setValues((s) => ({ ...s, budget: e.target.value }))}
                onKeyDown={(e) => handleKeyDown(e, 'budget')}
                disabled={saving}
                className="glass focus-ring w-full rounded-lg px-2 py-0.5 font-mono text-lg font-bold text-gray-900 dark:text-white focus:outline-none"
              />
              <SaveCancelButtons saving={saving} onSave={() => void saveField('budget')} onCancel={cancelEdit} labels={labels} />
            </div>
          ) : (
            <button
              type="button"
              onClick={() => startEdit('budget')}
              className="group/value flex items-center gap-1"
              title={labels.edit}
            >
              <span className="font-mono text-lg font-bold text-gray-900 dark:text-white">
                {formatMoney(Number(values.budget), values.currency)}
              </span>
              <EditPencil />
            </button>
          )}
        </StatCard>

        {/* Deadline — editable */}
        <StatCard label={labels.deadline}>
          {editMode === 'deadline' ? (
            <div className="flex items-center gap-1.5">
              <input
                ref={inputRef}
                type="date"
                value={values.deadline}
                onChange={(e) => setValues((s) => ({ ...s, deadline: e.target.value }))}
                onKeyDown={(e) => handleKeyDown(e, 'deadline')}
                disabled={saving}
                className="glass focus-ring w-full rounded-lg px-2 py-0.5 font-mono text-lg font-bold text-gray-900 dark:text-white focus:outline-none"
              />
              <SaveCancelButtons saving={saving} onSave={() => void saveField('deadline')} onCancel={cancelEdit} labels={labels} />
            </div>
          ) : (
            <button
              type="button"
              onClick={() => startEdit('deadline')}
              className="group/value flex items-center gap-1"
              title={labels.edit}
            >
              <span className="font-mono text-lg font-bold text-gray-900 dark:text-white">
                {values.deadline}
              </span>
              <EditPencil />
            </button>
          )}
        </StatCard>

        {/* Days left — read-only, computed */}
        <StatCard label={labels.daysLeft}>
          <span className={`font-mono text-lg font-bold ${
            overdue ? 'text-red-500 dark:text-red-400' : days <= 3 ? 'text-amber-600 dark:text-amber-300' : 'text-gray-900 dark:text-white'
          }`}>
            {overdue ? `${Math.abs(days)}d ${labels.overdue}` : days === 0 ? labels.dueToday : `${days}d`}
          </span>
        </StatCard>

        {/* Created — read-only */}
        <StatCard label={labels.created}>
          <span className="font-mono text-lg font-bold text-gray-900 dark:text-white">{createdAt}</span>
        </StatCard>
      </dl>

      {error && (
        <p className="mt-2 text-[12px] font-medium text-red-400">{error}</p>
      )}
    </>
  );
}

// ─── Helper components ───────────────────────────────────────────────────────

function StatCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-white/[0.04] bg-gray-50 dark:bg-white/[0.02] p-3 transition-colors hover:border-gray-300 dark:hover:border-white/[0.08]">
      <dt className="text-[11px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{label}</dt>
      <dd className="mt-1.5">{children}</dd>
    </div>
  );
}

function EditPencil() {
  return (
    <svg className="h-3 w-3 text-gray-300 dark:text-white/20 opacity-0 transition-opacity group-hover/value:opacity-100" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.683.6.6-2.683a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Z" />
    </svg>
  );
}

function SaveCancelButtons({ saving, onSave, onCancel, labels }: { saving: boolean; onSave: () => void; onCancel: () => void; labels: Props['labels'] }) {
  return (
    <div className="flex flex-shrink-0 items-center gap-1">
      <button
        type="button"
        onClick={onSave}
        disabled={saving}
        title={labels.save}
        className="flex h-7 w-7 items-center justify-center rounded-lg border border-emerald-400/30 bg-emerald-400/10 text-emerald-300 transition-colors hover:bg-emerald-400/20 disabled:opacity-40"
      >
        <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clipRule="evenodd" />
        </svg>
      </button>
      <button
        type="button"
        onClick={onCancel}
        disabled={saving}
        title={labels.cancel}
        className="flex h-7 w-7 items-center justify-center rounded-lg border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/[0.04] text-gray-400 dark:text-white/40 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.08] hover:text-gray-600 dark:hover:text-white/70 disabled:opacity-40"
      >
        <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
          <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
        </svg>
      </button>
    </div>
  );
}

// ─── Utils ───────────────────────────────────────────────────────────────────

function formatMoney(amount: number, currency: string): string {
  const symbols: Record<string, string> = { CNY: '¥', USD: '$', EUR: '€', GBP: '£', JPY: '¥' };
  const symbol = symbols[currency] ?? '';
  return `${symbol}${amount.toLocaleString()}`;
}
