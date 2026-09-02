import { useCallback, useEffect, useState, type ChangeEvent } from 'react'
import { useAuth } from '../auth/AuthContext'
import type { ProjectFileEntry } from '../api/dto'
import { EmptyState, ErrorBanner, LoadingBlock } from './feedback'

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function downloadTaskTemplate(): void {
  const csv = '\ufefftitle,assignee,deadline,priority,acceptance_criteria,original_source\n完成项目周报,张三,2026-08-01,high,周报包含本周进展、风险和下周计划,status.md\n'
  const href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = href
  link.download = '任务表模板.csv'
  link.click()
  URL.revokeObjectURL(href)
}

export function MaterialLibrary({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const { client } = useAuth()
  const [files, setFiles] = useState<ProjectFileEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setFiles(await client.listProjectFiles(projectId))
    } catch (cause) {
      setError(cause as Error)
    } finally {
      setLoading(false)
    }
  }, [client, projectId])

  useEffect(() => { void load() }, [load])

  const upload = async (event: ChangeEvent<HTMLInputElement>, taskFile: boolean) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || uploading) return
    setUploading(true)
    setError(null)
    try {
      await client.uploadProjectFile(projectId, file, taskFile)
      await load()
    } catch (cause) {
      setError(cause as Error)
    } finally {
      setUploading(false)
    }
  }

  const download = async (entry: ProjectFileEntry) => {
    setUploading(true)
    setError(null)
    try {
      const { blob, filename } = await client.downloadProjectFile(projectId, entry.relative_path)
      const href = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = href
      link.download = filename
      link.click()
      URL.revokeObjectURL(href)
    } catch (cause) {
      setError(cause as Error)
    } finally {
      setUploading(false)
    }
  }

  return <section id="project-materials" className="card material-library" aria-label="项目资料">
    <div className="card-title"><div><h2>项目资料</h2><p>先上传至少一份项目资料；任务可以上传 CSV/XLSX，或在任务工作台持续维护。</p></div>{canWrite ? <div className="upload-actions">
      <label className="file-button">上传项目资料<input type="file" disabled={uploading} accept=".md,.txt,.pdf,.docx,.xlsx" onChange={(event) => void upload(event, false)} /></label>
      <label className="file-button">上传任务表<input type="file" disabled={uploading} accept=".csv,.xlsx" onChange={(event) => void upload(event, true)} /></label>
      <button type="button" className="text-button" onClick={downloadTaskTemplate}>下载任务表模板</button>
    </div> : <p className="muted">只读访客不能上传或下载原始项目文件。</p>}</div>
    {error ? <ErrorBanner error={error} onRetry={() => void load()} /> : null}
    {loading ? <LoadingBlock label="正在加载项目资料…" /> : files.length === 0 ? <EmptyState title="还没有上传资料" hint="第一步：上传项目资料；第二步：上传任务表或在任务工作台创建任务；最后生成报告。" /> : <table><thead><tr><th>文件</th><th>类型</th><th>状态</th><th>大小</th><th>更新时间</th><th /></tr></thead><tbody>{files.map((file) => <tr key={file.relative_path}><td>{file.filename}</td><td>{file.is_task_file ? '任务表' : '项目资料'}</td><td><span className={`state state-${file.processing_status}`}>{file.processing_status === 'indexed' ? `已索引（v${file.index_version}）` : '已上传，下一次运行时索引'}</span></td><td>{formatBytes(file.size_bytes)}</td><td>{formatDate(file.updated_at)}</td><td>{canWrite ? <button type="button" className="text-button" disabled={uploading} onClick={() => void download(file)}>下载</button> : <span className="muted">只读</span>}</td></tr>)}</tbody></table>}
  </section>
}
