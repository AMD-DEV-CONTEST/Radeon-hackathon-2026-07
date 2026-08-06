'use client';

import { useEffect, useState, useRef } from 'react';
import { useLang } from '@/components/LanguageProvider';

interface KnowledgeDoc {
  id: string;
  title: string;
  content: string;
  doc_type: string;
  tags: string[];
  created_at: string;
}

const DOC_TYPES = ['contract', 'email', 'template', 'note'] as const;

function IconContract() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2Z" />
    </svg>
  );
}
function IconEmail() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path strokeLinecap="round" strokeLinejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 0 1-2.25 2.25h-15a2.25 2.25 0 0 1-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0 0 19.5 4.5h-15a2.25 2.25 0 0 0-2.25 2.25m19.5 0v.243a2.25 2.25 0 0 1-1.07 1.916l-7.5 4.615a2.25 2.25 0 0 1-2.36 0L3.32 8.91a2.25 2.25 0 0 1-1.07-1.916V6.75" />
    </svg>
  );
}
function IconTemplate() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25A2.25 2.25 0 0 1 13.5 18v-2.25" />
    </svg>
  );
}
function IconNote() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0 1 15.75 21H5.25A2.25 2.25 0 0 1 3 18.75V8.25A2.25 2.25 0 0 1 5.25 6H10" />
    </svg>
  );
}

const TYPE_ICON: Record<string, React.ReactNode> = {
  contract: <IconContract />,
  email: <IconEmail />,
  template: <IconTemplate />,
  note: <IconNote />,
};

const TYPE_COLOR: Record<string, string> = {
  contract: 'border-violet-500/20 bg-violet-500/5 text-violet-600 dark:border-violet-400/20 dark:bg-violet-400/5 dark:text-violet-300',
  email:    'border-teal-500/20 bg-teal-500/5 text-teal-600 dark:border-teal-400/20 dark:bg-teal-400/5 dark:text-teal-300',
  template: 'border-amber-500/20 bg-amber-500/5 text-amber-600 dark:border-amber-400/20 dark:bg-amber-400/5 dark:text-amber-300',
  note:     'border-gray-300 bg-gray-100 text-gray-500 dark:border-white/10 dark:bg-white/[0.04] dark:text-white/50',
};

export default function KnowledgePage() {
  const { t } = useLang();
  const k = t.knowledge;
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({ title: '', content: '', doc_type: 'note' as string });
  const [deleting, setDeleting] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [form, setForm] = useState({ title: '', content: '', doc_type: 'note' as string });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const editTextareaRef = useRef<HTMLTextAreaElement>(null);

  async function load() {
    setError(null);
    try {
      const res = await fetch('/api/knowledge');
      if (!res.ok) throw new Error('Failed to load documents');
      const d = (await res.json()) as { docs: KnowledgeDoc[] };
      setDocs(d.docs ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load documents');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title.trim() || !form.content.trim()) return;
    setError(null);
    setSaving(true);
    try {
      const res = await fetch('/api/knowledge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!res.ok) throw new Error('Failed to save document');
      setForm({ title: '', content: '', doc_type: 'note' });
      setShowForm(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save document');
    } finally {
      setSaving(false);
    }
  }

  async function del(id: string) {
    setError(null);
    setDeleting(id);
    try {
      const res = await fetch(`/api/knowledge?id=${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to delete document');
      setDocs((prev) => prev.filter((d) => d.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete document');
    } finally {
      setDeleting(null);
    }
  }

  function startEdit(doc: KnowledgeDoc) {
    setEditingId(doc.id);
    setEditForm({ title: doc.title, content: doc.content, doc_type: doc.doc_type });
    setTimeout(() => editTextareaRef.current?.focus(), 50);
  }

  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editingId || !editForm.title.trim() || !editForm.content.trim()) return;
    setError(null);
    setSaving(true);
    try {
      const res = await fetch('/api/knowledge', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: editingId, ...editForm }),
      });
      if (!res.ok) throw new Error('Failed to update document');
      setEditingId(null);
      setEditForm({ title: '', content: '', doc_type: 'note' });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update document');
    } finally {
      setSaving(false);
    }
  }

  function cancelEdit() {
    setEditingId(null);
    setEditForm({ title: '', content: '', doc_type: 'note' });
  }

  const filtered = search.trim()
    ? docs.filter(
        (d) =>
          d.title.toLowerCase().includes(search.toLowerCase()) ||
          d.content.toLowerCase().includes(search.toLowerCase())
      )
    : docs;

  return (
    <div className="space-y-8 animate-fade-up">
      {/* Error banner */}
      {error && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-red-300 bg-red-50 px-4 py-3 dark:border-red-400/20 dark:bg-red-400/5">
          <p className="text-[13px] font-medium text-red-600 dark:text-red-300">{error}</p>
          <button
            type="button"
            onClick={() => setError(null)}
            className="text-red-500 transition-colors hover:text-red-700 dark:text-red-400 dark:hover:text-red-200"
          >
            <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 6l8 8M14 6l-8 8" />
            </svg>
          </button>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-[20px] font-bold tracking-tight text-gray-900 dark:text-white">{k.title}</h1>
          <p className="mt-1 text-[14px] text-gray-500 dark:text-white/40">{k.subtitle}</p>
        </div>
        <button
          type="button"
          onClick={() => { setShowForm(true); setTimeout(() => textareaRef.current?.focus(), 50); }}
          className="inline-flex items-center gap-2 rounded-xl bg-amber-500 px-5 py-2.5 text-[14px] font-bold text-black transition-all duration-200 hover:bg-amber-400 dark:bg-amber-400 dark:hover:bg-amber-300"
        >
          {k.addDoc}
        </button>
      </div>

      {/* Add form */}
      {showForm && (
        <form
          onSubmit={(e) => void submit(e)}
          className="glass-strong animate-slide-down rounded-2xl p-6 space-y-4"
        >
          <h2 className="text-[15px] font-bold text-gray-800 dark:text-white/80">{k.newDoc}</h2>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{k.titleLabel}</label>
              <input
                type="text"
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                placeholder={k.titlePlaceholder}
                className="glass focus-ring w-full rounded-xl px-4 py-2.5 text-[14px] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 focus:outline-none"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{k.typeLabel}</label>
              <div className="flex gap-2">
                {DOC_TYPES.map((tp) => (
                  <button
                    key={tp}
                    type="button"
                    onClick={() => setForm((f) => ({ ...f, doc_type: tp }))}
                    className={`rounded-lg border px-3 py-2 text-[12px] font-semibold transition-all ${
                      form.doc_type === tp
                        ? TYPE_COLOR[tp]
                        : 'border-gray-200 text-gray-500 hover:text-gray-700 dark:border-white/[0.06] dark:text-white/35 dark:hover:text-white/60'
                    }`}
                  >
                    {TYPE_ICON[tp]} {k.docTypes[tp]}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-[11px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{k.contentLabel}</label>
            <textarea
              ref={textareaRef}
              value={form.content}
              onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
              rows={14}
              placeholder={k.subtitle}
              className="glass focus-ring w-full resize-y rounded-xl px-4 py-3 text-[13px] leading-relaxed text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 focus:outline-none"
            />
          </div>

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={saving || !form.title.trim() || !form.content.trim()}
              className="inline-flex items-center gap-2 rounded-xl bg-amber-500 dark:bg-amber-400 px-5 py-2.5 text-[13px] font-bold text-black transition-all disabled:opacity-40"
            >
              {saving ? k.saving : k.saveDoc}
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="rounded-xl px-4 py-2.5 text-[13px] text-gray-500 transition-colors hover:text-gray-700 dark:text-white/40 dark:hover:text-white/70"
            >
              {k.cancel}
            </button>
          </div>
        </form>
      )}

      {/* Edit form */}
      {editingId && (() => {
        const doc = docs.find((d) => d.id === editingId);
        if (!doc) return null;
        return (
        <form
          onSubmit={(e) => void saveEdit(e)}
          className="glass-strong animate-slide-down rounded-2xl p-6 space-y-4"
        >
          <h2 className="text-[15px] font-bold text-gray-800 dark:text-white/80">{k.newDoc}</h2>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{k.titleLabel}</label>
              <input
                type="text"
                value={editForm.title}
                onChange={(e) => setEditForm((f) => ({ ...f, title: e.target.value }))}
                placeholder={k.titlePlaceholder}
                className="glass focus-ring w-full rounded-xl px-4 py-2.5 text-[14px] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 focus:outline-none"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{k.typeLabel}</label>
              <div className="flex gap-2">
                {DOC_TYPES.map((tp) => (
                  <button
                    key={tp}
                    type="button"
                    onClick={() => setEditForm((f) => ({ ...f, doc_type: tp }))}
                    className={`rounded-lg border px-3 py-2 text-[12px] font-semibold transition-all ${
                      editForm.doc_type === tp
                        ? TYPE_COLOR[tp]
                        : 'border-gray-200 text-gray-500 hover:text-gray-700 dark:border-white/[0.06] dark:text-white/35 dark:hover:text-white/60'
                    }`}
                  >
                    {TYPE_ICON[tp]} {k.docTypes[tp]}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-[11px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{k.contentLabel}</label>
            <textarea
              ref={editTextareaRef}
              value={editForm.content}
              onChange={(e) => setEditForm((f) => ({ ...f, content: e.target.value }))}
              rows={14}
              placeholder={k.subtitle}
              className="glass focus-ring w-full resize-y rounded-xl px-4 py-3 text-[13px] leading-relaxed text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 focus:outline-none"
            />
          </div>

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={saving || !editForm.title.trim() || !editForm.content.trim()}
              className="inline-flex items-center gap-2 rounded-xl bg-amber-500 dark:bg-amber-400 px-5 py-2.5 text-[13px] font-bold text-black transition-all disabled:opacity-40"
            >
              {saving ? k.saving : k.saveDoc}
            </button>
            <button
              type="button"
              onClick={cancelEdit}
              className="rounded-xl px-4 py-2.5 text-[13px] text-gray-500 transition-colors hover:text-gray-700 dark:text-white/40 dark:hover:text-white/70"
            >
              {k.cancel}
            </button>
          </div>
        </form>
        );
      })()}

      {/* Search */}
      {docs.length > 0 && (
        <div className="relative">
          <svg className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400 dark:text-white/30" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM2 9a7 7 0 1 1 12.452 4.391l3.328 3.329a.75.75 0 1 1-1.06 1.06l-3.329-3.328A7 7 0 0 1 2 9Z" clipRule="evenodd" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={k.searchPlaceholder}
            className="glass focus-ring w-full rounded-xl py-2.5 pl-10 pr-4 text-[14px] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 focus:outline-none"
          />
        </div>
      )}

      {/* Document list */}
      {loading ? (
        <div className="space-y-3">
          {[1,2,3].map((i) => <div key={i} className="glass h-24 animate-pulse rounded-2xl" />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="glass flex flex-col items-center justify-center rounded-2xl px-8 py-20 text-center">
          <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-gray-200 bg-gray-100 dark:border-white/[0.06] dark:bg-white/[0.03]">
            <svg className="h-7 w-7 text-gray-400 dark:text-white/25" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A9 9 0 0 0 18 10.5a8.967 8.967 0 0 0-2.042-4.458ZM12 3.75a8.967 8.967 0 0 1 4.042 1.333M12 3.75a8.967 8.967 0 0 0-4.042 1.333" />
            </svg>
          </div>
          <p className="text-[15px] font-semibold text-gray-700 dark:text-white/70">
            {search ? k.noMatch : k.noDocs}
          </p>
          <p className="mt-1 text-[13px] text-gray-500 dark:text-white/35">
            {search ? k.noMatchDesc : k.noDocsDesc}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((doc) => (
            <div key={doc.id} className="glass glass-hover group rounded-2xl p-5 transition-all duration-200">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3 min-w-0 flex-1">
                  <span className="flex-shrink-0 mt-0.5 text-violet-600/80 dark:text-violet-300/80">{TYPE_ICON[doc.doc_type] ?? <IconNote />}</span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="text-[14px] font-bold text-gray-900 dark:text-white/90">{doc.title}</h3>
                      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold ${TYPE_COLOR[doc.doc_type] ?? TYPE_COLOR.note}`}>
                        {k.docTypes[doc.doc_type as keyof typeof k.docTypes] ?? doc.doc_type}
                      </span>
                    </div>
                    <p className="mt-1.5 line-clamp-3 text-[13px] leading-relaxed text-gray-500 dark:text-white/40">
                      {doc.content}
                    </p>
                    <p className="mt-2 font-mono text-[11px] tabular-nums text-gray-400 dark:text-white/20">
                      {new Date(doc.created_at).toLocaleDateString()}
                      {' · '}
                      {doc.content.length.toLocaleString()} {k.chars}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <button
                    type="button"
                    onClick={() => startEdit(doc)}
                    title={k.edit ?? 'Edit'}
                    className="rounded-lg p-2 text-gray-400 transition-all hover:bg-blue-500/10 hover:text-blue-500 dark:text-white/30 dark:hover:bg-blue-400/10 dark:hover:text-blue-400"
                  >
                    <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.683.6.6-2.683a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    onClick={() => void del(doc.id)}
                    disabled={deleting === doc.id}
                    title={k.delete ?? 'Delete'}
                    className="rounded-lg p-2 text-gray-400 transition-all hover:bg-red-500/10 hover:text-red-500 dark:text-white/30 dark:hover:bg-red-400/10 dark:hover:text-red-400 disabled:opacity-50"
                  >
                    {deleting === doc.id ? (
                      <svg className="h-4 w-4 animate-spin-slow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="12" cy="12" r="9" strokeOpacity=".25" />
                        <path d="M12 3a9 9 0 0 1 9 9" />
                      </svg>
                    ) : (
                      <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clipRule="evenodd" />
                      </svg>
                    )}
                  </button>
                </div>
              </div>
            </div>
          ))}
          <p className="text-right text-[12px] text-gray-400 dark:text-white/20">
            {filtered.length} {k.of} {docs.length} {k.documents}
          </p>
        </div>
      )}
    </div>
  );
}
