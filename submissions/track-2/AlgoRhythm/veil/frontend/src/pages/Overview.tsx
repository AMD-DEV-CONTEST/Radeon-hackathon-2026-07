import { useApp } from '@/context/AppContext'
import { can } from '@/types'
import { RiskBadge } from '@/components/ui/Badge'
import { FileText, Activity, Shield, ArrowRight, AlertTriangle } from 'lucide-react'
import { formatUtility, riskToPercent } from '@/lib/utils'
import { cn } from '@/lib/utils'

export function OverviewPage() {
  const { auth, documents, setCurrentPage, setSelectedDocumentId } = useApp()
  if (!auth) return null

  const auditedDocs = documents.filter(d => d.status !== 'uploaded')
  const criticalDocs = auditedDocs.filter(d => d.lastBand === 'CRITICAL' || d.lastBand === 'HIGH')
  const latestDoc = auditedDocs[0] ?? null

  return (
    <div className="max-w-5xl mx-auto px-8 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-gray-900">Overview</h1>
        <p className="text-sm text-gray-500 mt-1">
          Adversarial privacy audit platform · All inference local · Zero egress
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <MetricCard
          label="Documents audited"
          value={auditedDocs.length}
          sub={`${documents.length} total uploaded`}
          icon={<FileText size={16} />}
        />
        <MetricCard
          label="High/critical findings"
          value={criticalDocs.length}
          sub="requiring attention"
          icon={<AlertTriangle size={16} />}
          alert={criticalDocs.length > 0}
        />
        <MetricCard
          label="Avg utility retained"
          value={auditedDocs.length > 0
            ? formatUtility(auditedDocs.reduce((s, d) => s + (d.lastUtility ?? 0), 0) / auditedDocs.length)
            : '—'}
          sub="after redaction"
          icon={<Shield size={16} />}
        />
      </div>

      {/* Quick actions */}
      <div className="grid grid-cols-2 gap-4 mb-8">
        <QuickAction
          title="Upload and audit a document"
          description="Run five adversarial AI personas against a document to discover re-identification risks."
          actionLabel="Upload document"
          icon={<FileText size={20} />}
          onClick={() => setCurrentPage('documents')}
          disabled={!can(auth.role, 'run_attack')}
          disabledReason="Requires Auditor or Redactor role"
        />
        <QuickAction
          title="Open audit workspace"
          description="View findings, evidence, and apply targeted redactions to a previously audited document."
          actionLabel="Open workspace"
          icon={<Activity size={20} />}
          onClick={() => {
            if (latestDoc) setSelectedDocumentId(latestDoc.document_id)
            setCurrentPage('audit')
          }}
          disabled={auditedDocs.length === 0}
          disabledReason="Audit a document first"
        />
      </div>

      {/* Recent documents */}
      {documents.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-900">Recent documents</h2>
            <button
              onClick={() => setCurrentPage('documents')}
              className="text-xs text-gray-500 hover:text-gray-900 flex items-center gap-1"
            >
              View all <ArrowRight size={12} />
            </button>
          </div>
          <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 bg-white">
            {documents.slice(0, 5).map(doc => (
              <div
                key={doc.document_id}
                className="flex items-center gap-4 px-4 py-3 hover:bg-gray-50 cursor-pointer transition-colors"
                onClick={() => {
                  setSelectedDocumentId(doc.document_id)
                  setCurrentPage('audit')
                }}
              >
                <FileText size={14} className="text-gray-400 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">{doc.filename}</p>
                  <p className="text-xs text-gray-400 font-mono">
                    {doc.word_count.toLocaleString()} words · {doc.pages}p
                  </p>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  {doc.lastBand && <RiskBadge band={doc.lastBand} />}
                  {doc.lastUtility != null && (
                    <span className="text-xs text-gray-400 font-mono">
                      {formatUtility(doc.lastUtility)} utility
                    </span>
                  )}
                  <StatusPill status={doc.status} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Role capability notice for restricted roles */}
      {auth.role === 'viewer' && (
        <div className="mt-6 p-4 bg-gray-50 border border-gray-200 rounded-lg">
          <p className="text-sm text-gray-600">
            <span className="font-medium">Viewer role:</span> You can view audit results and risk scores.
            Contact an Auditor to run new audits or apply redactions.
          </p>
        </div>
      )}
    </div>
  )
}

function MetricCard({
  label, value, sub, icon, alert = false,
}: {
  label: string; value: string | number; sub: string; icon: React.ReactNode; alert?: boolean
}) {
  return (
    <div className={cn(
      'bg-white border rounded-lg p-5',
      alert && typeof value === 'number' && value > 0
        ? 'border-amber-200 bg-amber-50'
        : 'border-gray-200',
    )}>
      <div className={cn(
        'flex items-center gap-2 mb-3',
        alert && typeof value === 'number' && value > 0 ? 'text-amber-600' : 'text-gray-400',
      )}>
        {icon}
        <span className="text-2xs uppercase tracking-widest font-semibold">{label}</span>
      </div>
      <div className={cn(
        'text-3xl font-bold tabular-nums',
        alert && typeof value === 'number' && value > 0 ? 'text-amber-700' : 'text-gray-900',
      )}>
        {value}
      </div>
      <p className="text-xs text-gray-400 mt-1">{sub}</p>
    </div>
  )
}

function QuickAction({
  title, description, actionLabel, icon, onClick, disabled, disabledReason,
}: {
  title: string; description: string; actionLabel: string; icon: React.ReactNode;
  onClick: () => void; disabled?: boolean; disabledReason?: string;
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-5">
      <div className="text-gray-400 mb-3">{icon}</div>
      <h3 className="text-sm font-semibold text-gray-900 mb-1">{title}</h3>
      <p className="text-xs text-gray-500 mb-4 leading-relaxed">{description}</p>
      <button
        onClick={onClick}
        disabled={disabled}
        title={disabled ? disabledReason : undefined}
        className={cn(
          'flex items-center gap-1.5 text-xs font-medium transition-colors',
          disabled
            ? 'text-gray-300 cursor-not-allowed'
            : 'text-gray-900 hover:text-gray-600',
        )}
      >
        {actionLabel} <ArrowRight size={12} />
      </button>
    </div>
  )
}

function StatusPill({ status }: { status: string }) {
  const styles = {
    uploaded:  'bg-gray-100 text-gray-500',
    audited:   'bg-blue-50 text-blue-700',
    verified:  'bg-green-50 text-green-700',
  }[status] ?? 'bg-gray-100 text-gray-500'

  return (
    <span className={cn('text-2xs px-2 py-0.5 rounded font-medium capitalize', styles)}>
      {status}
    </span>
  )
}
