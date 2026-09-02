import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { EmptyState, ErrorBanner, LoadingBlock } from './feedback'
import type { CommentEntry, ProjectMemberEntry, ReportApprovalEntry, ReportDraftEntry, RiskCenterEntry } from '../api/dto'

const RISK_ACTIONS = ['acknowledge', 'resolve', 'dismiss', 'reopen'] as const
const APPROVALS = ['approved', 'rejected', 'request_changes'] as const

function formatDate(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value || '—' : parsed.toLocaleString()
}

function download(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = filename
  link.click()
  URL.revokeObjectURL(href)
}

export function RiskReportCenter({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const { client, user } = useAuth()
  const [tab, setTab] = useState<'risks' | 'reports'>('risks')
  const [risks, setRisks] = useState<RiskCenterEntry[]>([])
  const [reports, setReports] = useState<ReportDraftEntry[]>([])
  const [members, setMembers] = useState<ProjectMemberEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  const [showWorkspace, setShowWorkspace] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [nextRisks, nextReports, nextMembers] = await Promise.all([
        client.listRisks(projectId), client.listReportDrafts(projectId), client.listMembers(projectId),
      ])
      setRisks(nextRisks); setReports(nextReports); setMembers(nextMembers)
    } catch (cause) { setError(cause as Error) } finally { setLoading(false) }
  }, [client, projectId])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (risks.length > 0 || reports.length > 0) setShowWorkspace(true)
  }, [reports.length, risks.length])
  const role = members.find((member) => member.user_id === user?.user_id)?.role
  const canManage = role === 'admin' || role === 'pm'

  if (!loading && !error && !showWorkspace && risks.length === 0 && reports.length === 0) {
    return <section id="risk-report-center" className="card deferred-center" aria-label="风险与报告中心">
      <div><h2>风险与报告</h2><p>完成项目报告运行后，系统会在这里集中展示风险、报告草稿与审批记录。</p></div>
      <div className="deferred-center-content"><strong>当前没有需要处理的风险或报告。</strong><span>这是正常的首次使用状态，不需要先在这里填写内容。</span>
        {canWrite ? <button type="button" onClick={() => setShowWorkspace(true)}>查看报告草稿工作区</button> : null}
      </div>
    </section>
  }

  return <section id="risk-report-center" className="card risk-report-center" aria-label="风险与报告中心">
    <div className="card-title"><div><h2>风险与报告中心</h2><p>查看项目风险，并准备可供审批的正式报告。</p></div><button type="button" onClick={() => void load()} disabled={loading}>刷新</button></div>
    <div className="tab-bar"><button type="button" className={`tab ${tab === 'risks' ? 'selected' : ''}`} onClick={() => setTab('risks')}>风险（{risks.length}）</button><button type="button" className={`tab ${tab === 'reports' ? 'selected' : ''}`} onClick={() => setTab('reports')}>报告（{reports.length}）</button></div>
    {error ? <ErrorBanner error={error} onRetry={() => void load()} /> : null}
    {loading ? <LoadingBlock label="正在加载风险与报告…" /> : null}
    {!loading && tab === 'risks' ? <RiskPanel projectId={projectId} risks={risks} members={members} canManage={canManage} canComment={canWrite} onChanged={load} /> : null}
    {!loading && tab === 'reports' ? <ReportPanel projectId={projectId} reports={reports} canManage={canManage} canWrite={canWrite} onChanged={load} /> : null}
  </section>
}

function RiskPanel({ projectId, risks, members, canManage, canComment, onChanged }: { projectId: string; risks: RiskCenterEntry[]; members: ProjectMemberEntry[]; canManage: boolean; canComment: boolean; onChanged: () => Promise<void> }) {
  const { client } = useAuth()
  const [severity, setSeverity] = useState('')
  const [lifecycle, setLifecycle] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [assignee, setAssignee] = useState('')
  const [note, setNote] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const selected = risks.find((risk) => risk.record_id === selectedId) ?? null
  const visible = useMemo(() => risks.filter((risk) => (!severity || risk.severity === severity) && (!lifecycle || risk.lifecycle === lifecycle)), [risks, severity, lifecycle])

  const act = async (action: typeof RISK_ACTIONS[number]) => {
    if (!selected || pending) return
    const high = selected.severity === 'high' || selected.severity === 'critical'
    if ((action === 'resolve' || action === 'dismiss') && high && !window.confirm(`Confirm ${action} for this ${selected.severity} risk? This action is audited.`)) return
    setPending(true); setError(null)
    try { await client.updateRiskLifecycle(projectId, selected.record_id, { action, note }); setNote(''); await onChanged() } catch (cause) { setError(cause as Error) } finally { setPending(false) }
  }
  const assign = async () => {
    if (!selected || !assignee || pending) return
    setPending(true); setError(null)
    try { await client.assignRisk(projectId, selected.record_id, { risk_id: selected.record_id, assignee_user_id: assignee }); await onChanged() } catch (cause) { setError(cause as Error) } finally { setPending(false) }
  }

  return <div className="risk-layout"><div>
    <div className="filter-bar"><label>严重程度<select value={severity} onChange={(e) => setSeverity(e.target.value)}><option value="">全部</option><option>critical</option><option>high</option><option>medium</option><option>low</option></select></label><label>状态<select value={lifecycle} onChange={(e) => setLifecycle(e.target.value)}><option value="">全部</option><option>active</option><option>acknowledged</option><option>resolved</option><option>dismissed</option><option>expired</option></select></label></div>
    {error ? <ErrorBanner error={error} /> : null}
    {visible.length === 0 ? <EmptyState title="没有符合条件的风险" hint="风险扫描发现证据不足、临近截止或依赖阻塞时，会在此生成风险。" /> : <table><thead><tr><th>风险</th><th>严重程度</th><th>状态</th><th>负责人</th><th>讨论数</th></tr></thead><tbody>{visible.map((risk) => <tr key={risk.record_id} className={risk.record_id === selectedId ? 'selected-row' : ''} onClick={() => { setSelectedId(risk.record_id); setAssignee(risk.assigned_to ?? '') }}><td>{risk.title}</td><td><span className={`risk-${risk.severity}`}>{risk.severity}</span></td><td>{risk.lifecycle}</td><td>{risk.assignee_name ?? '未分配'}</td><td>{risk.comment_count}</td></tr>)}</tbody></table>}
  </div>{selected ? <aside className="task-detail"><h3>{selected.title}</h3><p>{selected.description || '未记录补充说明。'}</p><dl><dt>风险 ID</dt><dd>{selected.record_id}</dd><dt>严重程度</dt><dd>{selected.severity}</dd><dt>状态</dt><dd>{selected.lifecycle}</dd><dt>创建时间</dt><dd>{formatDate(selected.created_at)}</dd></dl>{canManage ? <><label>分配负责人<select value={assignee} onChange={(e) => setAssignee(e.target.value)}><option value="">选择成员</option>{members.filter((m) => m.role !== 'guest').map((member) => <option key={member.user_id} value={member.user_id}>{member.display_name}（{member.role}）</option>)}</select></label><button type="button" disabled={!assignee || pending} onClick={() => void assign()}>分配</button><textarea aria-label="风险处理备注" value={note} onChange={(e) => setNote(e.target.value)} placeholder="处理备注（会随生命周期变更记录）" /> <div className="actions">{RISK_ACTIONS.map((action) => <button key={action} type="button" disabled={pending} onClick={() => void act(action)}>{action}</button>)}</div></> : <p className="muted">只有项目经理或管理员可以分配或关闭风险。</p>}<Discussion projectId={projectId} entityType="risk" entityId={selected.record_id} canComment={canComment} /></aside> : null}</div>
}

function ReportPanel({ projectId, reports, canManage, canWrite, onChanged }: { projectId: string; reports: ReportDraftEntry[]; canManage: boolean; canWrite: boolean; onChanged: () => Promise<void> }) {
  const { client } = useAuth()
  const [selectedId, setSelectedId] = useState<string | null>(reports[0]?.id ?? null)
  const selected = reports.find((report) => report.id === selectedId) ?? null
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [comment, setComment] = useState('')
  const [approvals, setApprovals] = useState<ReportApprovalEntry[]>([])
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  useEffect(() => { if (!selectedId && reports[0]) setSelectedId(reports[0].id) }, [reports, selectedId])
  useEffect(() => { if (selected) { setTitle(selected.title); setContent(selected.content_md); void client.getReportApprovals(projectId, selected.id).then(setApprovals).catch((cause) => setError(cause as Error)) } }, [client, projectId, selected?.id])
  const refresh = async () => { await onChanged() }
  const save = async () => { if (!selected || pending || !canWrite) return; setPending(true); try { await client.updateReportDraft(projectId, selected.id, { title, content_md: content }); await refresh() } catch (cause) { setError(cause as Error) } finally { setPending(false) } }
  const create = async () => { if (!canWrite) return; const nextTitle = window.prompt('Draft title'); if (!nextTitle) return; setPending(true); try { const draft = await client.createReportDraft(projectId, { title: nextTitle, content_md: '# ' + nextTitle + '\n' }); await refresh(); setSelectedId(draft.id) } catch (cause) { setError(cause as Error) } finally { setPending(false) } }
  const submit = async () => { if (!selected || !canWrite) return; setPending(true); try { await client.submitReport(projectId, selected.id); await refresh() } catch (cause) { setError(cause as Error) } finally { setPending(false) } }
  const decide = async (decision: typeof APPROVALS[number]) => { if (!selected || !canManage) return; setPending(true); try { await client.decideReport(projectId, selected.id, { decision, comment }); setComment(''); await refresh(); setApprovals(await client.getReportApprovals(projectId, selected.id)) } catch (cause) { setError(cause as Error) } finally { setPending(false) } }
  const exportFile = async (format: 'pdf' | 'docx') => { if (!selected) return; setPending(true); try { const file = await client.downloadReport(projectId, selected.id, format); download(file.blob, file.filename) } catch (cause) { setError(cause as Error) } finally { setPending(false) } }
  const editable = canWrite && selected?.status === 'draft'

  return <div className="report-layout"><div className="report-list">{canWrite ? <button type="button" className="primary" disabled={pending} onClick={() => void create()}>新建草稿</button> : null}{reports.length === 0 ? <EmptyState title="没有报告草稿" hint="成员、项目经理或管理员可根据当前项目结论创建草稿。" /> : reports.map((report) => <button type="button" key={report.id} className={`run-row ${report.id === selectedId ? 'selected' : ''}`} onClick={() => setSelectedId(report.id)}><strong>{report.title}</strong><span>{report.status} · v{report.version}</span><small>{formatDate(report.updated_at)}</small></button>)}</div>{selected ? <div className="report-editor"><h3>{selected.title}</h3>{error ? <ErrorBanner error={error} /> : null}<label>标题<input value={title} onChange={(e) => setTitle(e.target.value)} disabled={!editable} /></label><div className="markdown-grid"><label>Markdown<textarea aria-label="报告 Markdown" value={content} onChange={(e) => setContent(e.target.value)} disabled={!editable} /></label><article className="markdown-preview"><h4>预览</h4><pre>{content}</pre><p className="muted">来源链接必须限定在当前项目。结构化引文导航将在后端提供报告引文记录后接入。</p></article></div><div className="actions">{editable ? <><button type="button" disabled={pending} onClick={() => void save()}>保存草稿</button><button type="button" disabled={pending} onClick={() => void submit()}>提交审批</button></> : null}<button type="button" disabled={pending} onClick={() => void exportFile('pdf')}>导出 PDF</button><button type="button" disabled={pending} onClick={() => void exportFile('docx')}>导出 DOCX</button></div>{canManage && selected.status === 'submitted' ? <div className="approval-box"><h4>审批决定</h4><textarea aria-label="审批意见" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="必填的审批意见或修改要求" /> <div className="actions">{APPROVALS.map((decision) => <button type="button" key={decision} disabled={pending} onClick={() => void decide(decision)}>{decision}</button>)}</div></div> : null}{!canManage && selected.status === 'submitted' ? <p className="muted">只有项目经理或管理员可以审批该报告。</p> : null}<h4>审批历史</h4>{approvals.length ? <ul className="history-list">{approvals.map((item) => <li key={item.id}><strong>{item.decision} by {item.approver_name}</strong><span>{item.comment || '无意见'}</span><small>{formatDate(item.created_at)}</small></li>)}</ul> : <p className="muted">尚无审批决定。</p>}<Discussion projectId={projectId} entityType="report" entityId={selected.id} canComment={canWrite} /></div> : <EmptyState title="选择一份报告" hint="选择草稿以查看、编辑、审批或导出。" />}</div>
}

function Discussion({ projectId, entityType, entityId, canComment }: { projectId: string; entityType: 'risk' | 'report'; entityId: string; canComment: boolean }) {
  const { client } = useAuth()
  const [items, setItems] = useState<CommentEntry[]>([])
  const [body, setBody] = useState('')
  const [error, setError] = useState<Error | null>(null)
  const load = useCallback(() => client.listComments(projectId, entityType, entityId).then(setItems).catch((cause) => setError(cause as Error)), [client, entityId, entityType, projectId])
  useEffect(() => { void load() }, [load])
  const post = async () => { if (!body.trim() || !canComment) return; try { await client.createComment(projectId, { entity_type: entityType, entity_id: entityId, body }); setBody(''); await load() } catch (cause) { setError(cause as Error) } }
  return <div className="discussion"><h4>讨论</h4>{error ? <ErrorBanner error={error} /> : null}{items.map((item) => <p key={item.id}><strong>{item.author_name}</strong> · {item.body}</p>)}{canComment ? <><textarea aria-label="讨论评论" value={body} onChange={(e) => setBody(e.target.value)} placeholder="添加项目讨论评论" /><button type="button" onClick={() => void post()}>发表评论</button></> : <p className="muted">只读访客不能发表评论。</p>}</div>
}
