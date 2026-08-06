import { useState } from 'react'
import { useApp } from '@/context/AppContext'
import { api } from '@/lib/api'
import { StatusDot } from '@/components/ui/StatusDot'
import { cn } from '@/lib/utils'
import { RefreshCw, ShieldCheck, ShieldAlert, Lock, Server } from 'lucide-react'

export function SecurityPage() {
  const { auth, selftest, setSelftest } = useApp()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  function load() {
    if (!auth) return
    setLoading(true)
    setError('')
    api.selftest()
      .then(d => { setSelftest(d); setLoading(false) })
      .catch(err => {
        setError(err.message ?? 'Request failed')
        setLoading(false)
      })
  }

  if (!auth) return null

  const data = selftest
  const overall = data ? (data.egress_blocked && data.audit_chain_ok) : null
  // Show skeleton only on initial load (no cached data yet)
  const initialLoad = data === null && !error && !loading

  return (
    <div className="max-w-3xl mx-auto px-8 py-8">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Security</h1>
          <p className="text-sm text-gray-500 mt-1">System security posture and local execution guarantees</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-900 transition-colors disabled:opacity-40"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 rounded-md border border-red-200 bg-red-50 text-sm text-red-700">
          <span className="font-medium">Could not reach selftest endpoint:</span> {error}
          <span className="block mt-1 text-xs text-red-500">
            Click <strong>Refresh</strong> to retry, or check the TopBar — it shows the same data if it loaded successfully there.
          </span>
        </div>
      )}

      {/* Overall status banner */}
      {data && (
        <div className={cn(
          'flex items-center gap-3 p-4 rounded-lg border mb-6',
          overall ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50',
        )}>
          {overall
            ? <ShieldCheck size={20} className="text-green-600 flex-shrink-0" />
            : <ShieldAlert size={20} className="text-red-600 flex-shrink-0" />}
          <div>
            <p className={cn('font-medium text-sm', overall ? 'text-green-800' : 'text-red-800')}>
              {overall ? 'All security controls active' : 'Security control failure detected'}
            </p>
            <p className={cn('text-xs mt-0.5', overall ? 'text-green-600' : 'text-red-600')}>
              {overall
                ? 'Egress is blocked and audit chain is intact. Safe to operate.'
                : 'One or more security controls have failed. Do not process sensitive documents.'}
            </p>
          </div>
        </div>
      )}

      {/* If TopBar hasn't loaded yet either, show a prompt */}
      {initialLoad && !error && (
        <div className="mb-4 px-4 py-3 rounded-md border border-gray-200 bg-gray-50 text-sm text-gray-600">
          Status loading… The TopBar fetches this automatically after login. Or click <strong>Refresh</strong> to load now.
        </div>
      )}

      <div className="space-y-4">
        {/* Egress guard */}
        <SecurityCard
          icon={<Lock size={16} />}
          title="Egress guard"
          description="All outbound network requests are blocked except to the local vLLM endpoint. This is the structural guarantee that no document content leaves the machine."
          loading={loading || (initialLoad && !data)}
          status={data ? (data.egress_blocked ? 'ok' : 'fail') : 'loading'}
          statusLabel={data
            ? (data.egress_blocked ? 'Blocked' : 'OPEN — critical failure')
            : (error ? 'Unavailable' : '…')}
          rows={data ? [
            ['Status',        data.egress_blocked ? '✓ All external traffic blocked' : '✗ Egress is OPEN'],
            ['Allowed hosts', (data.allowed_hosts ?? []).join(', ') || 'none'],
            ['Detail',        data.egress_detail ?? '—'],
          ] : []}
        />

        {/* Audit chain */}
        <SecurityCard
          icon={<ShieldCheck size={16} />}
          title="Audit chain integrity"
          description="Every event is appended to an HMAC-chained log. Any tampering with past entries breaks the chain and is immediately detectable."
          loading={loading || (initialLoad && !data)}
          status={data ? (data.audit_chain_ok ? 'ok' : 'fail') : 'loading'}
          statusLabel={data
            ? (data.audit_chain_ok ? `Intact · ${data.audit_entries} entries` : 'BROKEN — chain tampered')
            : (error ? 'Unavailable' : '…')}
          rows={data ? [
            ['Chain',   data.audit_chain_ok ? '✓ Intact' : '✗ Broken'],
            ['Entries', String(data.audit_entries ?? '—')],
            ['Detail',  data.audit_detail ?? '—'],
          ] : []}
        />

        {/* Local inference — hardcoded, always known */}
        <SecurityCard
          icon={<Server size={16} />}
          title="Local inference"
          description="All LLM inference runs on vLLM bound to 127.0.0.1:8000. The vLLM endpoint is never exposed to the tunnel port."
          loading={false}
          status="ok"
          statusLabel="Local (loopback)"
          rows={[
            ['Endpoint', 'http://127.0.0.1:8000/v1'],
            ['Model',    'Qwen/Qwen2.5-14B-Instruct-AWQ'],
            ['GPU',      'AMD Radeon RX 7900 XTX (ROCm)'],
            ['Exposure', 'None — loopback only'],
          ]}
        />

        {/* Role capabilities */}
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <div className="flex items-center gap-2.5 mb-1">
              <Lock size={16} className="text-gray-500" />
              <h2 className="text-sm font-semibold text-gray-900">Role separation</h2>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Re-identification reasoning is never surfaced to Redactors or Viewers — handing it to them would turn VEIL into a distribution channel for the exact inference it prevents.
            </p>
          </div>
          <div className="px-5 py-4">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 text-gray-500 font-medium">Capability</th>
                  <th className="text-center py-2 text-gray-500 font-medium">Auditor</th>
                  <th className="text-center py-2 text-gray-500 font-medium">Redactor</th>
                  <th className="text-center py-2 text-gray-500 font-medium">Viewer</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {([
                  ['Run audit',        true,  false, false],
                  ['View findings',    true,  true,  false],
                  ['View reasoning',   true,  false, false],
                  ['View evidence',    true,  false, false],
                  ['Apply redactions', true,  true,  false],
                  ['Export report',    true,  true,  false],
                  ['View audit log',   true,  false, false],
                  ['View risk score',  true,  true,  true],
                  ['View document',    true,  true,  true],
                ] as [string, boolean, boolean, boolean][]).map(([cap, a, r, v]) => (
                  <tr key={cap}>
                    <td className="py-2 text-gray-700">{cap}</td>
                    <td className="py-2 text-center">{a ? <span className="text-green-600">✓</span> : <span className="text-gray-200">—</span>}</td>
                    <td className="py-2 text-center">{r ? <span className="text-green-600">✓</span> : <span className="text-gray-200">—</span>}</td>
                    <td className="py-2 text-center">{v ? <span className="text-green-600">✓</span> : <span className="text-gray-200">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}

function SecurityCard({
  icon, title, description, loading, status, statusLabel, rows,
}: {
  icon: React.ReactNode
  title: string
  description: string
  loading: boolean
  status: 'ok' | 'fail' | 'loading'
  statusLabel: string
  rows: [string, string][]
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
      <div className="flex items-start justify-between px-5 py-4 border-b border-gray-100">
        <div className="flex items-center gap-2.5">
          <span className="text-gray-500">{icon}</span>
          <div>
            <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
            <p className="text-xs text-gray-500 mt-0.5 max-w-lg">{description}</p>
          </div>
        </div>
        <div className={cn(
          'flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium flex-shrink-0 ml-4',
          status === 'ok'   ? 'border-green-200 bg-green-50 text-green-700' :
          status === 'fail' ? 'border-red-200 bg-red-50 text-red-700' :
                              'border-gray-200 bg-gray-50 text-gray-400',
        )}>
          <StatusDot variant={
            loading           ? 'idle' :
            status === 'ok'   ? 'online' :
            status === 'fail' ? 'offline' : 'idle'
          } />
          {loading ? '…' : statusLabel}
        </div>
      </div>
      {rows.length > 0 && (
        <div className="px-5 py-3">
          <dl className="space-y-1.5">
            {rows.map(([k, v]) => (
              <div key={k} className="flex items-baseline gap-4">
                <dt className="text-2xs text-gray-400 w-28 flex-shrink-0">{k}</dt>
                <dd className="text-2xs font-mono text-gray-700 flex-1 break-all">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  )
}
