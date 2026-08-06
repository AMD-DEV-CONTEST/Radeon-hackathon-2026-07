export default function Sidebar({
  conversations,
  activeConversationId,
  onOpenConversation,
  documents,
  selectedDocuments,
  onToggleDocument,
  onUpload,
  uploading,
}) {
  return (
    <aside className="panel flex h-full flex-col gap-6 p-5">
      <div>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">AgentFlow AI</h2>
          <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 text-[10px] font-semibold text-cyan-300">
            Track 2
          </span>
        </div>
        <p className="text-sm text-slate-400">
          Autonomous multi-agent automation with Planner, Research, Memory, Tool, and Reviewer agents.
        </p>
      </div>

      <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
        <label className="mb-3 block text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">
          Upload PDF / TXT / MD
        </label>
        <label className="flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-cyan-500/40 bg-slate-900/70 px-4 py-6 text-center text-sm text-slate-300 transition hover:border-cyan-400 hover:bg-slate-900">
          <span className="mb-2 text-base font-medium text-white">Drop local knowledge</span>
          <span className="text-xs text-slate-400">Use offline RAG with ChromaDB</span>
          <input
            type="file"
            accept=".pdf,.txt,.md"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) onUpload(file)
              event.target.value = ''
            }}
          />
        </label>
        {uploading ? <p className="mt-3 text-xs text-cyan-300">Indexing document…</p> : null}
      </div>

      <section className="min-h-0 flex-1 overflow-hidden">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Document context</h3>
          <span className="text-xs text-slate-500">{documents.length}</span>
        </div>
        <div className="scroll-area max-h-52 space-y-2 overflow-auto pr-1">
          {documents.length === 0 ? (
            <div className="rounded-2xl border border-white/8 bg-white/4 p-3 text-xs text-slate-500">
              Upload a PDF brief, PRD, or notes file to activate Research Agent retrieval.
            </div>
          ) : (
            documents.map((doc) => {
              const selected = selectedDocuments.includes(doc.id)
              return (
                <button
                  key={doc.id}
                  type="button"
                  onClick={() => onToggleDocument(doc.id)}
                  className={`w-full rounded-2xl border px-3 py-3 text-left transition ${
                    selected
                      ? 'border-cyan-400/60 bg-cyan-500/10 text-white'
                      : 'border-white/8 bg-white/4 text-slate-300 hover:border-white/15 hover:bg-white/8'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="line-clamp-2 text-sm font-medium">{doc.filename}</p>
                      <p className="mt-1 text-xs text-slate-400">
                        {doc.page_count} page(s) • {doc.chunk_count} chunks
                      </p>
                    </div>
                    <span className={`status-pill ${selected ? 'status-online' : 'status-idle'}`}>
                      {selected ? 'Active' : 'Idle'}
                    </span>
                  </div>
                </button>
              )
            })
          )}
        </div>
      </section>

      <section className="min-h-0 overflow-hidden">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Conversations</h3>
          <span className="text-xs text-slate-500">{conversations.length}</span>
        </div>
        <div className="scroll-area max-h-64 space-y-2 overflow-auto pr-1">
          {conversations.length === 0 ? (
            <div className="rounded-2xl border border-white/8 bg-white/4 p-3 text-xs text-slate-500">
              Your autonomous runs and chat history will appear here.
            </div>
          ) : (
            conversations.map((conversation) => (
              <button
                key={conversation.id}
                type="button"
                onClick={() => onOpenConversation(conversation.id)}
                className={`w-full rounded-2xl border px-3 py-3 text-left transition ${
                  activeConversationId === conversation.id
                    ? 'border-fuchsia-400/60 bg-fuchsia-500/10 text-white'
                    : 'border-white/8 bg-white/4 text-slate-300 hover:border-white/15 hover:bg-white/8'
                }`}
              >
                <p className="line-clamp-2 text-sm font-medium">{conversation.title}</p>
                <p className="mt-1 line-clamp-2 text-xs text-slate-400">{conversation.last_message_preview}</p>
              </button>
            ))
          )}
        </div>
      </section>
    </aside>
  )
}
