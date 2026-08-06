import { useEffect } from 'react'
import { useApp } from '@/context/AppContext'
import { api } from '@/lib/api'
import { StatusDot } from '@/components/ui/StatusDot'
import { cn } from '@/lib/utils'

export function TopBar() {
  const { auth, selftest, setSelftest } = useApp()

  useEffect(() => {
    if (!auth || selftest) return   // already loaded — don't call twice
    let cancelled = false
    api.selftest()
      .then(d => { if (!cancelled) setSelftest(d) })
      .catch(() => {})              // fail silently in TopBar; Security page shows error
    return () => { cancelled = true }
  }, [auth, selftest, setSelftest])

  if (!auth) return null

  const egressOk  = selftest?.egress_blocked   ?? null
  const chainOk   = selftest?.audit_chain_ok   ?? null
  const loading   = selftest === null

  return (
    <header className="h-12 flex items-center px-5 border-b border-gray-200 bg-white flex-shrink-0">
      <div className="flex-1" />

      <div className="flex items-center divide-x divide-gray-200">

        {/* Local inference — always known */}
        <div className="flex items-center gap-1.5 px-3 text-xs text-gray-500">
          <StatusDot variant="online" />
          <span className="font-mono">Local inference</span>
        </div>

        {/* Egress */}
        <div className={cn(
          'flex items-center gap-1.5 px-3 text-xs',
          loading       ? 'text-gray-400' :
          egressOk      ? 'text-gray-500' : 'text-red-600',
        )}>
          <StatusDot variant={loading ? 'idle' : egressOk ? 'online' : 'offline'} />
          <span className="font-mono">
            {loading ? 'Checking…' : egressOk ? 'Egress blocked' : 'Egress OPEN'}
          </span>
        </div>

        {/* Audit chain */}
        {!loading && chainOk !== null && (
          <div className={cn(
            'flex items-center gap-1.5 px-3 text-xs',
            chainOk ? 'text-gray-500' : 'text-red-600',
          )}>
            <StatusDot variant={chainOk ? 'online' : 'offline'} />
            <span className="font-mono">
              Chain {chainOk ? 'intact' : 'BROKEN'}
              {selftest && ` · ${selftest.audit_entries}`}
            </span>
          </div>
        )}

        {/* Role badge */}
        <div className="pl-3">
          <span className={cn(
            'inline-flex items-center px-2.5 py-1 rounded text-2xs font-medium uppercase tracking-wide',
            auth.role === 'auditor'  ? 'bg-gray-900 text-white' :
            auth.role === 'redactor' ? 'bg-gray-100 text-gray-700' :
                                       'bg-gray-50 text-gray-500',
          )}>
            {auth.role}
          </span>
        </div>
      </div>
    </header>
  )
}
