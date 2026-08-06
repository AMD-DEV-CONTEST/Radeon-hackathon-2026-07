import { useEffect, useMemo, useState } from 'react'
import Composer from './components/Composer'
import MessageList from './components/MessageList'
import Sidebar from './components/Sidebar'
import StatusPanel from './components/StatusPanel'
import { api } from './lib/api'

function normalizeMessages(messages) {
  return (messages || []).map((message) => ({
    ...message,
    plan: message.plan || {},
    citations: message.citations || [],
    tools: message.tools || [],
    timeline: message.timeline || [],
    benchmark: message.benchmark || {},
  }))
}

export default function App() {
  const [health, setHealth] = useState(null)
  const [systemInfo, setSystemInfo] = useState(null)
  const [benchmarks, setBenchmarks] = useState(null)
  const [conversations, setConversations] = useState([])
  const [documents, setDocuments] = useState([])
  const [selectedDocuments, setSelectedDocuments] = useState([])
  const [activeConversationId, setActiveConversationId] = useState(null)
  const [messages, setMessages] = useState([])
  const [latestResponse, setLatestResponse] = useState(null)
  const [sending, setSending] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')

  async function refreshCoreData() {
    try {
      const [healthData, systemData, benchmarkData, conversationData, documentData] = await Promise.all([
        api.health(),
        api.systemInfo(),
        api.benchmarks(),
        api.conversations(),
        api.documents(),
      ])
      setHealth(healthData)
      setSystemInfo(systemData)
      setBenchmarks(benchmarkData)
      setConversations(conversationData)
      setDocuments(documentData)
    } catch (err) {
      setError(err.message)
    }
  }

  useEffect(() => {
    refreshCoreData()
    const interval = setInterval(refreshCoreData, 15000)
    return () => clearInterval(interval)
  }, [])

  async function openConversation(conversationId) {
    setError('')
    try {
      const conversation = await api.conversation(conversationId)
      setActiveConversationId(conversationId)
      setMessages(normalizeMessages(conversation.messages))
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleSend(message) {
    setSending(true)
    setError('')
    const optimisticUser = {
      id: `temp-${Date.now()}`,
      role: 'user',
      content: message,
      created_at: new Date().toISOString(),
      citations: [],
      tools: [],
      timeline: [],
      benchmark: {},
      plan: {},
    }
    setMessages((current) => [...current, optimisticUser])

    try {
      const response = await api.sendMessage({
        conversation_id: activeConversationId,
        message,
        document_ids: selectedDocuments,
      })

      setLatestResponse(response)
      setActiveConversationId(response.conversation_id)
      setMessages((current) => [
        ...current.filter((item) => item.id !== optimisticUser.id),
        optimisticUser,
        {
          id: response.message_id,
          role: 'assistant',
          content: response.response,
          created_at: new Date().toISOString(),
          model: response.model,
          plan: response.planner,
          citations: response.citations,
          tools: response.tools,
          timeline: response.timeline,
          benchmark: response.benchmark,
        },
      ])
      await refreshCoreData()
    } catch (err) {
      setMessages((current) => current.filter((item) => item.id !== optimisticUser.id))
      setError(err.message)
    } finally {
      setSending(false)
    }
  }

  async function handleUpload(file) {
    setUploading(true)
    setError('')
    try {
      const response = await api.uploadDocument(file)
      setDocuments((current) => [response.document, ...current])
      setSelectedDocuments((current) => [response.document.id, ...current])
      await refreshCoreData()
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  function toggleDocument(documentId) {
    setSelectedDocuments((current) =>
      current.includes(documentId) ? current.filter((item) => item !== documentId) : [...current, documentId],
    )
  }

  const banner = useMemo(() => latestResponse?.system_alert || error, [error, latestResponse])

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(34,211,238,0.18),_transparent_22%),radial-gradient(circle_at_right,_rgba(217,70,239,0.15),_transparent_24%),linear-gradient(180deg,#020617_0%,#020617_35%,#0f172a_100%)] text-slate-100">
      <div className="mx-auto grid min-h-screen max-w-[1800px] gap-5 p-4 xl:grid-cols-[320px_minmax(0,1fr)_360px]">
        <Sidebar
          conversations={conversations}
          activeConversationId={activeConversationId}
          onOpenConversation={openConversation}
          documents={documents}
          selectedDocuments={selectedDocuments}
          onToggleDocument={toggleDocument}
          onUpload={handleUpload}
          uploading={uploading}
        />

        <main className="flex min-h-[calc(100vh-2rem)] flex-col gap-5">
          <section className="panel flex items-center justify-between gap-4 p-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">Hackathon control room</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">AgentFlow AI</h1>
              <p className="mt-2 max-w-3xl text-sm leading-7 text-slate-400">
                Autonomous multi-agent task automation with local Ollama reasoning, ChromaDB RAG, SQLite memory, execution timelines, and benchmark telemetry.
              </p>
            </div>
            <div className="hidden rounded-3xl border border-white/8 bg-white/4 px-5 py-4 lg:block">
              <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Active documents</p>
              <p className="mt-2 text-2xl font-semibold text-white">{selectedDocuments.length}</p>
              <p className="mt-1 text-xs text-slate-400">Selected for Research Agent retrieval</p>
            </div>
          </section>

          {banner ? (
            <section className="rounded-3xl border border-amber-400/30 bg-amber-500/10 px-5 py-4 text-sm text-amber-100 shadow-lg shadow-amber-950/20">
              {banner}
            </section>
          ) : null}

          <section className="panel flex min-h-0 flex-1 flex-col gap-5 p-5">
            <MessageList messages={messages} sending={sending} />
            <Composer onSubmit={handleSend} disabled={sending} />
          </section>
        </main>

        <StatusPanel health={health} systemInfo={systemInfo} benchmarks={benchmarks} latestResponse={latestResponse} />
      </div>
    </div>
  )
}
