import { useCallback, useEffect, useMemo, useState, type ChangeEvent } from 'react'
import { useAuth } from '../auth/AuthContext'
import { EmptyState, ErrorBanner, LoadingBlock } from './feedback'
import {
  TASK_ALLOWED_TRANSITIONS,
  type ConfirmationRecord,
  type OperationAuditRecord,
  type PhaseFTaskStatus,
  type TaskChangeRecord,
  type TaskImportDiff,
  type TaskImportResult,
  type TaskRecord,
} from '../api/dto'

const STATUS_LABELS: Record<PhaseFTaskStatus, string> = {
  pending_confirmation: '待确认', not_started: '未开始', in_progress: '进行中',
  mostly_completed: '基本完成', completed: '已完成', delayed: '已延期', cancelled: '已取消',
}

const STATUS_FILTER_OPTIONS: PhaseFTaskStatus[] = [
  'pending_confirmation', 'not_started', 'in_progress', 'mostly_completed',
  'completed', 'delayed', 'cancelled',
]

type TabId = 'tasks' | 'queue' | 'import' | 'audit'

function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function statusLabel(status: string): string {
  return STATUS_LABELS[status as PhaseFTaskStatus] ?? status
}

/** Allowed targets come from the mirrored state machine; the SERVER remains
 * the single authority and rejects anything else (TASK_INVALID_TRANSITION). */
function allowedTargets(status: string): PhaseFTaskStatus[] {
  return TASK_ALLOWED_TRANSITIONS[status as PhaseFTaskStatus] ?? []
}

export function TaskWorkbench({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const { client, user } = useAuth()
  const [tab, setTab] = useState<TabId>('tasks')
  const [tasks, setTasks] = useState<TaskRecord[]>([])
  const [queue, setQueue] = useState<ConfirmationRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  const [statusFilter, setStatusFilter] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [nextTasks, nextQueue] = await Promise.all([
        client.listTasks(projectId, statusFilter || undefined),
        client.listConfirmationQueue(projectId, 'pending'),
      ])
      setTasks(nextTasks)
      setQueue(nextQueue)
    } catch (cause) {
      setError(cause as Error)
    } finally {
      setLoading(false)
    }
  }, [client, projectId, statusFilter])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!loading && canWrite && tab === 'tasks' && tasks.length === 0 && queue.length === 0) {
      setTab('import')
    }
  }, [canWrite, loading, queue.length, tab, tasks.length])

  return (
    <section id="task-workbench" className="card task-workbench" aria-label="任务工作台">
      <div className="card-title">
        <div>
          <h2>任务工作台</h2><p>确认候选任务、导入任务表，并在审计记录下维护任务状态。</p>
        </div>
      </div>
      <div className="tab-bar" role="tablist" aria-label="任务工作台分区">
        <button type="button" role="tab" aria-selected={tab === 'tasks'} className={tab === 'tasks' ? 'tab selected' : 'tab'} onClick={() => setTab('tasks')}>任务（{tasks.length}）</button>
        <button type="button" role="tab" aria-selected={tab === 'queue'} className={tab === 'queue' ? 'tab selected' : 'tab'} onClick={() => setTab('queue')}>待确认队列（{queue.length}）</button>
        {canWrite ? <button type="button" role="tab" aria-selected={tab === 'import'} className={tab === 'import' ? 'tab selected' : 'tab'} onClick={() => setTab('import')}>导入 CSV/XLSX</button> : null}
        <button type="button" role="tab" aria-selected={tab === 'audit'} className={tab === 'audit' ? 'tab selected' : 'tab'} onClick={() => setTab('audit')}>审计记录</button>
      </div>
      {error ? <ErrorBanner error={error} onRetry={() => void load()} /> : null}
      {loading ? <LoadingBlock label="正在加载任务工作台…" /> : null}
      {!loading && tab === 'tasks' ? (
        <TaskListPanel projectId={projectId} tasks={tasks} statusFilter={statusFilter}
          onStatusFilter={setStatusFilter} onChanged={load} canWrite={canWrite} />
      ) : null}
      {!loading && tab === 'queue' ? (
        <ConfirmationQueuePanel projectId={projectId} queue={queue}
          operator={canWrite ? user?.username ?? '' : ''} canWrite={canWrite} onChanged={load} />
      ) : null}
      {!loading && tab === 'import' && canWrite ? (
        <ImportPanel projectId={projectId} operator={user?.username ?? ''} onImported={load} />
      ) : null}
      {!loading && tab === 'audit' ? <AuditPanel projectId={projectId} /> : null}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Tasks: list + client-side filters + detail (history, transitions)
// ---------------------------------------------------------------------------

function TaskListPanel({ projectId, tasks, statusFilter, onStatusFilter, onChanged, canWrite }: {
  projectId: string; tasks: TaskRecord[]; statusFilter: string
  onStatusFilter: (value: string) => void; onChanged: () => Promise<void>; canWrite: boolean
}) {
  const [ownerFilter, setOwnerFilter] = useState('')
  const [priorityFilter, setPriorityFilter] = useState('')
  const [dueBefore, setDueBefore] = useState('')
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)

  const owners = useMemo(
    () => [...new Set(tasks.map((task) => task.owner).filter((o): o is string => Boolean(o)))].sort(),
    [tasks],
  )
  const priorities = useMemo(
    () => [...new Set(tasks.map((task) => task.priority).filter(Boolean))].sort(),
    [tasks],
  )

  // Server filters by status; owner/priority/due-date narrowing is client-side.
  const visible = useMemo(() => tasks.filter((task) => {
    if (ownerFilter && task.owner !== ownerFilter) return false
    if (priorityFilter && task.priority !== priorityFilter) return false
    if (dueBefore && (!task.due_date || task.due_date > dueBefore)) return false
    return true
  }), [tasks, ownerFilter, priorityFilter, dueBefore])

  const selectedTask = visible.find((task) => task.id === selectedTaskId)
    ?? tasks.find((task) => task.id === selectedTaskId)
    ?? null

  return (
    <div>
      <div className="filter-bar" aria-label="任务筛选">
        <label>状态
          <select value={statusFilter} onChange={(event) => onStatusFilter(event.target.value)}>
            <option value="">全部</option>
            {STATUS_FILTER_OPTIONS.map((status) => <option key={status} value={status}>{STATUS_LABELS[status]}</option>)}
          </select>
        </label>
        <label>负责人
          <select value={ownerFilter} onChange={(event) => setOwnerFilter(event.target.value)}>
            <option value="">全部</option>
            {owners.map((owner) => <option key={owner} value={owner}>{owner}</option>)}
          </select>
        </label>
        <label>优先级
          <select value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value)}>
            <option value="">全部</option>
            {priorities.map((priority) => <option key={priority} value={priority}>{priority}</option>)}
          </select>
        </label>
        <label>截止日期早于
          <input type="date" value={dueBefore} onChange={(event) => setDueBefore(event.target.value)} />
        </label>
      </div>
      {visible.length === 0 ? (
        <EmptyState title="没有符合当前筛选条件的任务"
          hint="可导入任务表，或在待确认队列中接受候选任务。" />
      ) : (
        <div className="task-layout">
          <table aria-label="任务列表">
            <thead><tr><th>任务名称</th><th>状态</th><th>负责人</th><th>优先级</th><th>截止日期</th></tr></thead>
            <tbody>
              {visible.map((task) => (
                <tr key={task.id} className={task.id === selectedTaskId ? 'selected-row' : ''}
                  onClick={() => setSelectedTaskId(task.id)}>
                  <td>{task.title}</td>
                  <td><span className={`state status-${task.status}`}>{statusLabel(task.status)}</span></td>
                  <td>{task.owner ?? '—'}</td>
                  <td>{task.priority || '—'}</td>
                  <td>{task.due_date ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {selectedTask ? (
            <TaskDetail key={selectedTask.id} projectId={projectId} task={selectedTask}
              onChanged={onChanged} canWrite={canWrite} />
          ) : <p className="muted">选择一项任务可查看详情、变更历史和状态流转。</p>}
        </div>
      )}
    </div>
  )
}

function TaskDetail({ projectId, task, onChanged, canWrite }: {
  projectId: string; task: TaskRecord; onChanged: () => Promise<void>; canWrite: boolean
}) {
  const { client } = useAuth()
  const [history, setHistory] = useState<TaskChangeRecord[]>([])
  const [historyError, setHistoryError] = useState<Error | null>(null)
  const [target, setTarget] = useState('')
  const [reason, setReason] = useState('')
  const [pending, setPending] = useState(false)
  const [transitionError, setTransitionError] = useState<Error | null>(null)

  const loadHistory = useCallback(async () => {
    setHistoryError(null)
    try {
      setHistory(await client.getTaskHistory(projectId, task.id))
    } catch (cause) {
      setHistoryError(cause as Error)
    }
  }, [client, projectId, task.id])

  useEffect(() => { void loadHistory() }, [loadHistory])

  const targets = allowedTargets(task.status)

  const submitTransition = async () => {
    if (!target || !reason.trim() || pending) return
    setPending(true)
    setTransitionError(null)
    try {
      await client.transitionTask(projectId, task.id, {
        status: target as PhaseFTaskStatus,
        reason: reason.trim(),
      })
      setTarget('')
      setReason('')
      await Promise.all([onChanged(), loadHistory()])
    } catch (cause) {
      // Server-side rejection (e.g. TASK_INVALID_TRANSITION) surfaces here.
      setTransitionError(cause as Error)
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="task-detail" aria-label="任务详情">
      <h3>{task.title}</h3>
      <dl>
        <dt>状态</dt><dd>{statusLabel(task.status)}</dd><dt>负责人</dt><dd>{task.owner ?? '—'}</dd><dt>优先级</dt><dd>{task.priority || '—'}</dd><dt>截止日期</dt><dd>{task.due_date ?? '—'}</dd><dt>验收标准</dt><dd>{task.acceptance_criteria || '—'}</dd><dt>依赖项</dt><dd>{task.dependencies.length > 0 ? task.dependencies.join(', ') : '—'}</dd><dt>来源</dt><dd>{task.source_ref ?? '—'}</dd>
        {task.confirmed_by ? (
          <>
            <dt>确认人</dt><dd>{task.confirmed_by}（{formatDate(task.confirmed_at)}）</dd><dt>确认依据</dt><dd>{task.confirmation_basis ?? '—'}</dd>
          </>
        ) : null}
        <dt>更新时间</dt><dd>{formatDate(task.updated_at)}</dd>
      </dl>

      <h4>变更状态</h4>
      {!canWrite ? <p className="muted">只读访客不能变更任务状态。</p> : targets.length === 0 ? (
        <p className="muted">该任务已处于最终状态，不能继续流转。</p>
      ) : (
        <div className="transition-form">
          <select aria-label="目标状态" value={target} onChange={(event) => setTarget(event.target.value)}><option value="">请选择目标状态…</option>
            {targets.map((status) => <option key={status} value={status}>{STATUS_LABELS[status]}</option>)}
          </select>
          <textarea aria-label="状态变更原因" placeholder="变更原因（必填，会记录在历史中）"
            value={reason} rows={2} maxLength={2000}
            onChange={(event) => setReason(event.target.value)} />
          <button type="button" className="primary" disabled={pending || !target || !reason.trim()}
            onClick={() => void submitTransition()}>确认变更</button>
        </div>
      )}
      {transitionError ? <ErrorBanner error={transitionError} /> : null}

      <h4>变更历史</h4>
      {historyError ? <ErrorBanner error={historyError} onRetry={() => void loadHistory()} /> : null}
      {history.length === 0 ? <p className="muted">暂未记录状态变更。</p> : (
        <ul className="history-list">
          {history.map((entry) => (
            <li key={entry.id}>
              <strong>{entry.from_status ? `${statusLabel(entry.from_status)} → ` : ''}{statusLabel(entry.to_status)}</strong>
              <span>{formatDate(entry.changed_at)}{entry.changed_by ? ` · ${entry.changed_by}` : ''}</span>
              {entry.change_reason ? <small>{entry.change_reason}</small> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Confirmation queue: accept / modify / ignore with reason + evidence
// ---------------------------------------------------------------------------

function ConfirmationQueuePanel({ projectId, queue, operator, canWrite, onChanged }: {
  projectId: string; queue: ConfirmationRecord[]; operator: string; canWrite: boolean; onChanged: () => Promise<void>
}) {
  const { client } = useAuth()
  const [openId, setOpenId] = useState<number | null>(null)
  const [action, setAction] = useState<'accept' | 'modify' | 'ignore'>('accept')
  const [basis, setBasis] = useState('')
  const [notes, setNotes] = useState('')
  const [modTitle, setModTitle] = useState('')
  const [modOwner, setModOwner] = useState('')
  const [modDue, setModDue] = useState('')
  const [modPriority, setModPriority] = useState('')
  const [pending, setPending] = useState(false)
  const [actionError, setActionError] = useState<Error | null>(null)

  const openItem = (item: ConfirmationRecord) => {
    setOpenId(item.id)
    setAction('accept')
    setBasis('')
    setNotes('')
    setModTitle(item.candidate_title)
    setModOwner(item.candidate_owner ?? '')
    setModDue(item.candidate_due_date ?? '')
    setModPriority(item.candidate_priority ?? '')
    setActionError(null)
  }

  const submit = async (item: ConfirmationRecord) => {
    if (pending || !operator) return
    setPending(true)
    setActionError(null)
    try {
      await client.processConfirmation(projectId, item.task_id, {
        action,
        confirmation_basis: basis.trim() || null,
        confirmation_notes: notes.trim() || null,
        ...(action === 'modify'
          ? {
              modified_title: modTitle.trim() || null,
              modified_owner: modOwner.trim() || null,
              modified_due_date: modDue || null,
              modified_priority: modPriority.trim() || null,
            }
          : {}),
      })
      setOpenId(null)
      await onChanged()
    } catch (cause) {
      setActionError(cause as Error)
    } finally {
      setPending(false)
    }
  }

  if (queue.length === 0) {
    return <EmptyState title="待确认队列为空" hint="从会议纪要提取的候选任务会在这里等待人工确认。" />
  }

  return (
    <div aria-label="待确认队列">
      {queue.map((item) => (
        <div key={item.id} className="queue-item">
          <div className="queue-summary">
            <div>
              <strong>{item.candidate_title}</strong>
              <p className="muted">
                {item.candidate_owner ? `负责人：${item.candidate_owner} · ` : ''}{item.candidate_due_date ? `截止日期：${item.candidate_due_date} · ` : ''}来源：{item.source_kind}{item.source_ref ? `（${item.source_ref}）` : ''} · 置信度：{(item.confidence * 100).toFixed(0)}%
              </p>
              {item.candidate_acceptance ? <p className="muted">验收标准：{item.candidate_acceptance}</p> : null}
            </div>
            {canWrite ? <button type="button" className="text-button" onClick={() => openId === item.id ? setOpenId(null) : openItem(item)}>
              {openId === item.id ? '收起' : '审核'}
            </button> : <span className="muted">只读</span>}
          </div>
          {openId === item.id ? (
            <div className="queue-form">
              <div className="filter-bar">
                <label>处理决定
                  <select aria-label="处理决定" value={action} onChange={(event) => setAction(event.target.value as typeof action)}>
                    <option value="accept">按原样接受</option><option value="modify">修改后接受</option><option value="ignore">忽略</option>
                  </select>
                </label>
              </div>
              {action === 'modify' ? (
                <div className="filter-bar">
                  <label>任务名称<input value={modTitle} onChange={(event) => setModTitle(event.target.value)} /></label><label>负责人<input value={modOwner} onChange={(event) => setModOwner(event.target.value)} /></label><label>截止日期<input type="date" value={modDue} onChange={(event) => setModDue(event.target.value)} /></label><label>优先级<input value={modPriority} onChange={(event) => setModPriority(event.target.value)} /></label>
                </div>
              ) : null}
              <textarea aria-label="确认依据" placeholder="本次决定的依据或证据"
                rows={2} value={basis} onChange={(event) => setBasis(event.target.value)} />
              <textarea aria-label="确认备注" placeholder="备注（可选）"
                rows={2} value={notes} onChange={(event) => setNotes(event.target.value)} />
              {!operator ? <p className="muted">需要登录身份才能记录该决定。</p> : null}
              <button type="button" className="primary" disabled={pending || !operator}
                onClick={() => void submit(item)}>记录决定</button>
              {actionError ? <ErrorBanner error={actionError} /> : null}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// CSV / XLSX import: preview first (dry-run), then explicit confirm
// ---------------------------------------------------------------------------

function ImportPanel({ projectId, operator, onImported }: {
  projectId: string; operator: string; onImported: () => Promise<void>
}) {
  const { client } = useAuth()
  const [file, setFile] = useState<File | null>(null)
  const [diff, setDiff] = useState<TaskImportDiff | null>(null)
  const [result, setResult] = useState<TaskImportResult | null>(null)
  const [skipDuplicates, setSkipDuplicates] = useState(true)
  const [overwriteConflicts, setOverwriteConflicts] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const pick = async (event: ChangeEvent<HTMLInputElement>) => {
    const next = event.target.files?.[0] ?? null
    event.target.value = ''
    if (!next || pending) return
    setFile(next)
    setDiff(null)
    setResult(null)
    setError(null)
    setPending(true)
    try {
      setDiff(await client.previewTaskImport(projectId, next))
    } catch (cause) {
      setError(cause as Error)
      setFile(null)
    } finally {
      setPending(false)
    }
  }

  const confirm = async () => {
    if (!file || pending || !operator) return
    setPending(true)
    setError(null)
    try {
      setResult(await client.confirmTaskImport(projectId, file, skipDuplicates, overwriteConflicts))
      setDiff(null)
      setFile(null)
      await onImported()
    } catch (cause) {
      setError(cause as Error)
    } finally {
      setPending(false)
    }
  }

  const previewColumns = diff && diff.preview.length > 0 ? Object.keys(diff.preview[0]) : []

  return (
    <div aria-label="任务导入">
      <p className="muted">第 1 步：选择 CSV/XLSX 文件预览差异。第 2 步：确认后才写入正式任务。</p>
      <div className="actions">
        <label className="file-button">选择任务文件
          <input type="file" accept=".csv,.xlsx,.xls" disabled={pending} onChange={(event) => void pick(event)} />
        </label>
        {file ? <span className="muted">已选择：{file.name}</span> : null}
      </div>
      {pending ? <LoadingBlock label="正在请求服务端…" /> : null}
      {error ? <ErrorBanner error={error} /> : null}
      {diff ? (
        <div className="import-preview">
          <div className="grid">
            <div className="stat"><div className="value">{diff.new_rows}</div><div className="label">新增行</div></div><div className="stat"><div className="value">{diff.duplicate_rows}</div><div className="label">重复行</div></div><div className="stat"><div className="value">{diff.conflict_rows}</div><div className="label">冲突行</div></div>
          </div>
          {diff.preview.length > 0 ? (
            <table aria-label="导入预览行">
              <thead><tr>{previewColumns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
              <tbody>
                {diff.preview.map((row, index) => (
                  <tr key={index}>{previewColumns.map((column) => <td key={column}>{row[column] ?? ''}</td>)}</tr>
                ))}
              </tbody>
            </table>
          ) : <p className="muted">文件不包含数据行。</p>}
          <div className="actions import-options">
            <label><input type="checkbox" checked={skipDuplicates}
              onChange={(event) => setSkipDuplicates(event.target.checked)} /> 跳过重复项</label>
            <label><input type="checkbox" checked={overwriteConflicts}
              onChange={(event) => setOverwriteConflicts(event.target.checked)} /> 覆盖冲突项</label>
            <button type="button" className="primary" disabled={pending || !operator} onClick={() => void confirm()}>
              确认导入
            </button>
          </div>
          {!operator ? <p className="muted">需要登录身份才能确认导入。</p> : null}
        </div>
      ) : null}
      {result ? (
        <div className="grid" aria-label="导入结果">
          <div className="stat"><div className="value">{result.imported}</div><div className="label">已导入</div></div><div className="stat"><div className="value">{result.skipped}</div><div className="label">已跳过</div></div><div className="stat"><div className="value">{result.errors}</div><div className="label">错误</div></div>
        </div>
      ) : null}
      {result && result.details.length > 0 ? (
        <ul className="history-list">{result.details.map((detail, index) => <li key={index}><small>{detail}</small></li>)}</ul>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Audit log
// ---------------------------------------------------------------------------

function AuditPanel({ projectId }: { projectId: string }) {
  const { client } = useAuth()
  const [records, setRecords] = useState<OperationAuditRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setRecords(await client.getTaskAuditLog(projectId, 100))
    } catch (cause) {
      setError(cause as Error)
    } finally {
      setLoading(false)
    }
  }, [client, projectId])

  useEffect(() => { void load() }, [load])

  return (
    <div aria-label="审计记录">
      {error ? <ErrorBanner error={error} onRetry={() => void load()} /> : null}
      {loading ? <LoadingBlock label="正在加载审计记录…" /> : records.length === 0 ? (
        <EmptyState title="还没有审计记录" hint="任务确认、导入和状态变更都会记录在这里。" />
      ) : (
        <table aria-label="审计条目"><thead><tr><th>时间</th><th>操作</th><th>对象</th><th>操作人</th><th>详情</th></tr></thead>
          <tbody>
            {records.map((record) => (
              <tr key={record.id}>
                <td>{formatDate(record.created_at)}</td>
                <td>{record.operation}</td>
                <td>{record.entity_type} · {record.entity_id}</td>
                <td>{record.operator ?? '—'}</td>
                <td className="audit-details">{record.details ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
