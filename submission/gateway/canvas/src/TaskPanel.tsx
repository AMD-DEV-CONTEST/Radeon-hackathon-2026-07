import { useEffect, useState, useCallback } from 'react'
import {
  Check,
  Copy,
  Database,
  File,
  FileCode,
  ImageIcon,
  Package,
} from 'lucide-react'

const API_BASE = import.meta.env.VITE_ORCHESTRATOR_URL ?? 'http://111.228.42.18:8000'

type Artifact = {
  id: string
  task_id: string
  attempt_id: string | null
  artifact_type: string
  uri: string
  sha256: string | null
  metadata: Record<string, unknown>
  created_at: string
}

async function fetchArtifacts(taskId: string): Promise<Artifact[]> {
  const r = await fetch(`${API_BASE}/tasks/${taskId}/artifacts`)
  if (!r.ok) throw new Error(`artifacts ${r.status}`)
  return r.json() as Promise<Artifact[]>
}

function typeColor(t: string): string {
  const map: Record<string, string> = {
    code: '#3b82f6', file: '#3b82f6',
    screenshot: '#8b5cf6', image: '#8b5cf6',
    data: '#f59e0b', json: '#f59e0b',
  }
  return map[t] ?? '#64748b'
}

function TypeIcon({ t }: { t: string }) {
  if (t === 'code' || t === 'file') return <FileCode size={12} />
  if (t === 'data' || t === 'json') return <Database size={12} />
  if (t === 'image' || t === 'screenshot') return <ImageIcon size={12} />
  return <File size={12} />
}

function CopyBtn({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  const copy = () => {
    void navigator.clipboard.writeText(text).then(() => {
      setDone(true)
      setTimeout(() => setDone(false), 1400)
    })
  }
  return (
    <button onClick={copy} title="Copy" style={s.copyBtn}>
      {done ? <Check size={11} color="#22c55e" /> : <Copy size={11} />}
    </button>
  )
}

interface TaskPanelProps {
  taskId: string
}

export function TaskPanel({ taskId }: TaskPanelProps) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(() => {
    fetchArtifacts(taskId)
      .then((rows) => { setArtifacts(rows); setErr(null) })
      .catch((e: Error) => setErr(e.message))
  }, [taskId])

  useEffect(() => {
    setArtifacts([])
    load()
    const t = window.setInterval(load, 5000)
    return () => window.clearInterval(t)
  }, [load])

  if (err) return <div style={s.errBox}>{err}</div>

  if (!artifacts.length) return (
    <div style={s.empty}>
      <Package size={14} color="#475569" />
      <span>No artifacts yet</span>
    </div>
  )

  return (
    <div style={s.list}>
      {artifacts.map((a) => (
        <div key={a.id} style={s.row}>
          <div style={s.rowHead}>
            <span style={{ ...s.badge, color: typeColor(a.artifact_type) }}>
              <TypeIcon t={a.artifact_type} />
              {a.artifact_type}
            </span>
            <span style={s.ts}>{new Date(a.created_at).toLocaleTimeString()}</span>
          </div>
          <div style={s.uriRow}>
            <span style={s.uri} title={a.uri}>{a.uri}</span>
            <CopyBtn text={a.uri} />
          </div>
          {a.sha256 && (
            <span style={s.sha}>{a.sha256.slice(0, 16)}…</span>
          )}
        </div>
      ))}
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  list: { display: 'flex', flexDirection: 'column', gap: 6 },
  row: {
    background: 'rgba(148,163,184,0.04)',
    border: '1px solid rgba(148,163,184,0.10)',
    borderRadius: 6,
    padding: '7px 10px',
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  rowHead: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  badge: {
    display: 'flex', alignItems: 'center', gap: 4,
    fontSize: 11, fontWeight: 600, letterSpacing: '0.3px', textTransform: 'uppercase',
  },
  ts: { fontSize: 10, color: '#475569' },
  uriRow: { display: 'flex', alignItems: 'center', gap: 6 },
  uri: {
    fontSize: 11, color: '#94a3b8',
    fontFamily: 'Consolas, monospace',
    flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  copyBtn: {
    background: 'none', border: 'none', cursor: 'pointer',
    padding: '2px 4px', color: '#64748b', flexShrink: 0,
  },
  sha: { fontSize: 10, color: '#475569', fontFamily: 'Consolas, monospace' },
  empty: { display: 'flex', alignItems: 'center', gap: 8, padding: '10px 0', fontSize: 12, color: '#475569' },
  errBox: { fontSize: 11, color: '#ef4444', padding: '6px 0' },
}
