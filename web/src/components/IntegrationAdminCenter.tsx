import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/errors'
import { useAuth } from '../auth/AuthContext'
import { ErrorBanner, LoadingBlock } from './feedback'
import type { AdminHealth, BackupEntry, IntegrationExecutionResult, ScmPreviewRequest, ScmPreviewResponse } from '../api/dto'

const emptyChange: ScmPreviewRequest = {
  project_id: '', target: 'github_issues', operation: 'create', items: [{ title: '', body: '' }],
}

export function IntegrationAdminCenter({ projectId }: { projectId: string }) {
  const { client } = useAuth()
  const [change, setChange] = useState<ScmPreviewRequest>({ ...emptyChange, project_id: projectId })
  const [preview, setPreview] = useState<ScmPreviewResponse | null>(null)
  const [result, setResult] = useState<IntegrationExecutionResult | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => setChange((current) => ({ ...current, project_id: projectId })), [projectId])
  const updateItem = (field: 'title' | 'body', value: string) => setChange((current) => ({ ...current, items: [{ ...current.items[0], [field]: value }] }))
  const createPreview = async () => {
    if (!change.items[0]?.title.trim()) return
    setPending(true); setError(null); setResult(null)
    try { setPreview(await client.previewScmChange(change)) } catch (cause) { setError(cause as Error) } finally { setPending(false) }
  }
  const execute = async () => {
    if (!preview || !window.confirm('确认执行这项已预览的变更吗？系统将把它记录为一次外部协作平台写入。')) return
    setPending(true); setError(null)
    try { setResult(await client.executeScmChange(change, preview.confirmation_id)); setPreview(null) } catch (cause) { setError(cause as Error) } finally { setPending(false) }
  }

  return <section className="card integration-center" aria-label="受控集成中心">
    <div className="card-title"><div><h2>受控集成</h2><p>请先预览；任何写入操作都必须由人工确认服务端签发的精确变更内容。</p></div></div>
    {error ? <ErrorBanner error={error} onRetry={() => void createPreview()} /> : null}
    <div className="integration-form">
      <label>目标系统<select value={change.target} disabled={pending || Boolean(preview)} onChange={(event) => setChange((item) => ({ ...item, target: event.target.value as ScmPreviewRequest['target'] }))}><option value="github_issues">GitHub Issues</option><option value="jira">Jira</option></select></label>
      <label>操作<select value={change.operation} disabled={pending || Boolean(preview)} onChange={(event) => setChange((item) => ({ ...item, operation: event.target.value as ScmPreviewRequest['operation'] }))}><option value="create">创建</option><option value="update">更新</option></select></label>
      <label>事项标题<input value={change.items[0]?.title ?? ''} disabled={pending || Boolean(preview)} onChange={(event) => updateItem('title', event.target.value)} placeholder="简短的变更标题" /></label>
      <label>说明<textarea value={change.items[0]?.body ?? ''} disabled={pending || Boolean(preview)} onChange={(event) => updateItem('body', event.target.value)} placeholder="可选说明" /></label>
    </div>
    {!preview ? <button type="button" className="primary" disabled={pending || !change.items[0]?.title.trim()} onClick={() => void createPreview()}>1. 预览变更</button> : <div className="preview-box"><h3>2. 核对精确变更</h3><pre>{JSON.stringify(preview.preview, null, 2)}</pre><p className="muted">此页面不会接收或展示令牌、密钥、Webhook 地址或其他凭据。</p><div className="actions"><button type="button" className="primary" disabled={pending} onClick={() => void execute()}>3. 确认并执行</button><button type="button" disabled={pending} onClick={() => setPreview(null)}>放弃预览</button></div></div>}
    {result ? <div className="execution-result"><strong>{result.summary}</strong><pre>{JSON.stringify(result.details, null, 2)}</pre><p className="muted">连接器审计会记录这次执行。系统不会自动回滚；如需回滚，请遵循目标系统已审核的回滚流程。</p></div> : null}
  </section>
}

export function AdminOperations() {
  const { client } = useAuth()
  const [health, setHealth] = useState<AdminHealth | null>(null)
  const [backups, setBackups] = useState<BackupEntry[]>([])
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)
  const load = useCallback(async (background = false) => {
    if (!background) setLoading(true)
    setError(null)
    try { const [nextHealth, nextBackups] = await Promise.all([client.getAdminHealth(), client.listBackups()]); setHealth(nextHealth); setBackups(nextBackups) }
    catch (cause) { if (cause instanceof ApiError && cause.status === 403) { setHealth(null); setBackups([]); return }; setError(cause as Error) }
    finally { if (!background) setLoading(false) }
  }, [client])
  useEffect(() => {
    void load()
    const timer = window.setInterval(() => {
      if (!document.hidden) void load(true)
    }, 5000)
    return () => window.clearInterval(timer)
  }, [load])
  if (loading && !health) return null
  if (!health && !error) return null
  return <section className="card admin-operations" aria-label="系统管理">
    <div className="card-title"><div><h2>系统运维</h2><p>仅系统管理员可见的运行指标。为保护安全，凭据和文件系统路径不会显示。</p></div><button type="button" onClick={() => void load()}>刷新</button></div>
    {error ? <ErrorBanner error={error} onRetry={() => void load()} /> : null}
    {health ? <><div className="grid"><Stat label="健康状态" value={systemStatus(health.status)} /><Stat label="排队调用" value={health.queue_status.queued_calls} /><Stat label="缓存命中率" value={`${(health.cache_stats.hit_rate * 100).toFixed(1)}%`} /><Stat label="备份数量" value={backups.length} /></div>
      <dl className="admin-details"><dt>模型</dt><dd>{health.model_metadata.model_name || '不可用'} · {health.model_metadata.quantization || '未知'} · 上下文 {health.model_metadata.context_size || '—'}</dd><dt>队列</dt><dd>{health.queue_status.active_llm_calls} 个 LLM 调用中 / {health.queue_status.active_embedding_calls} 个嵌入调用中 / {health.queue_status.total_errors} 个错误</dd><dt>缓存</dt><dd>{health.cache_stats.size} / {health.cache_stats.max_entries} 条目；已淘汰 {health.cache_stats.evictions} 条</dd><dt>最近失败</dt><dd>{health.issues.length ? health.issues.map((issue) => systemMessage(issue.message ?? issue.code ?? '未知问题')).join('；') : '暂无上报'}</dd><dt>备份状态</dt><dd>{backups[0] ? `${systemStatus(backups[0].status)} · ${backups[0].timestamp || backups[0].name}` : '暂无备份'}</dd></dl>
      {health.gpu_metrics.length ? <p className="muted">GPU：{health.gpu_metrics.map((gpu) => `${gpu.name || `设备 ${gpu.device_id}`} · 显存 ${gpu.vram_used_mb.toFixed(0)}/${gpu.vram_total_mb.toFixed(0)} MB · 利用率 ${gpu.utilization_pct.toFixed(0)}% · ${gpu.temperature_c.toFixed(0)}°C`).join('；')}</p> : null}
    </> : <LoadingBlock label="正在加载系统运行状态…" />}
  </section>
}

function Stat({ label, value }: { label: string; value: string | number }) { return <div className="stat"><div className="value">{value}</div><div className="label">{label}</div></div> }
function systemStatus(value: string) { return ({ critical: '严重', healthy: '正常', warning: '警告', unavailable: '不可用', unknown: '未知', completed: '已完成', failed: '失败' } as Record<string, string>)[value] ?? value }
function systemMessage(value: string) { return ({ 'LLM endpoint not reachable': 'LLM 服务端点不可达', 'No backup available': '暂无备份' } as Record<string, string>)[value] ?? value }
