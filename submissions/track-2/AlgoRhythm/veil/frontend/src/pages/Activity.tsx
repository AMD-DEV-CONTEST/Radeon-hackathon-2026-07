import { useEffect, useState } from 'react'
import { useApp } from '@/context/AppContext'
import { api } from '@/lib/api'
import { can } from '@/types'
import type { AuditEntry } from '@/types'
import { EmptyState } from '@/components/ui/EmptyState'
import { StatusDot } from '@/components/ui/StatusDot'
import { Clock, Lock } from 'lucide-react'
import { cn, formatDate } from '@/lib/utils'

export function ActivityPage() {
  const { auth } = useApp()
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [chainOk, setChainOk] = useState<boolean | null>(null)
  const [chainDetail, setChainDetail] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!auth || !can(auth.role, 'view_audit')) return
    api.getAuditLog(200)
      .then(d => {
        setEntries(d.entries)
        setChainOk(d.chain_ok)
        setChainDetail(d.detail)
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [auth])

  if (!auth) return null

  if (!can(auth.role, 'view_audit')) {
    return (
      <div className="max-w-2xl mx-auto px-8 py-16">
        <EmptyState
          icon={<Lock />}
          title="Access restricted"
          description="The audit log is only accessible to the Auditor role."
        />
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto px-8 py-8">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Audit Log</h1>
          <p className="text-sm text-gray-500 mt-1">HMAC-chained immutable log of all system events</p>
        </div>
        {chainOk !== null && (
          <div className={cn(
            'flex items-center gap-2 px-3 py-2 rounded-md border text-sm',
            chainOk
              ? 'border-green-200 bg-green-50 text-green-700'
              : 'border-red-200 bg-red-50 text-red-700',
          )}>
            <StatusDot variant={chainOk ? 'online' : 'offline'} />
            <span className="font-medium">{chainOk ? 'Chain intact' : 'Chain BROKEN'}</span>
          </div>
        )}
      </div>

      {chainDetail && (
        <div className={cn(
          'mb-4 px-4 py-3 rounded-md border text-xs font-mono',
          chainOk ? 'border-gray-200 bg-gray-50 text-gray-600' : 'border-red-200 bg-red-50 text-red-700',
        )}>
          {chainDetail}
        </div>
      )}

      {error && (
        <div className="mb-4 px-4 py-3 rounded-md border border-red-200 bg-red-50 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-px">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="animate-pulse h-12 bg-gray-100 rounded-md" />
          ))}
        </div>
      ) : entries.length === 0 ? (
        <div className="bg-white border border-gray-200 rounded-lg">
          <EmptyState
            icon={<Clock />}
            title="No audit entries"
            description="Events will appear here as the system operates."
          />
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          {/* Header */}
          <div className="grid grid-cols-[56px_140px_140px_1fr_100px] gap-4 px-4 py-2.5 border-b border-gray-100 bg-gray-50">
            <span className="section-label">#</span>
            <span className="section-label">Timestamp</span>
            <span className="section-label">Actor</span>
            <span className="section-label">Event</span>
            <span className="section-label text-right">Hash</span>
          </div>
          <div className="divide-y divide-gray-100 max-h-[600px] overflow-y-auto">
            {[...entries].reverse().map(entry => (
              <div
                key={entry.seq}
                className="grid grid-cols-[56px_140px_140px_1fr_100px] gap-4 px-4 py-2.5 hover:bg-gray-50 transition-colors"
              >
                <span className="text-2xs font-mono text-gray-400 tabular-nums">{entry.seq}</span>
                <span className="text-2xs font-mono text-gray-500 tabular-nums">
                  {formatDate(entry.ts_ms / 1000)}
                </span>
                <span className="text-2xs font-mono text-gray-600 truncate">{entry.actor}</span>
                <div>
                  <span className="text-xs text-gray-800">{entry.action}</span>
                  {entry.payload && Object.keys(entry.payload).length > 0 && (
                    <div className="mt-0.5 flex flex-wrap gap-2">
                      {Object.entries(entry.payload).slice(0, 3).map(([k, v]) => (
                        <span key={k} className="text-2xs font-mono text-gray-400">
                          {k}: {String(v).slice(0, 24)}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <span className="text-2xs font-mono text-gray-300 text-right truncate tabular-nums">
                  {(entry.entry_hash || '').slice(0, 8)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
