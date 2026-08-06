import { useEffect, useRef, useState } from "react"
import { api } from "../lib/api"
import { Button } from "../components/ui/Button"
import { Card, CardBody, CardHeader } from "../components/ui/Card"
import { Badge } from "../components/ui/Badge"
import { Spinner } from "../components/ui/Spinner"

interface Run {
  id: number
  material_id: number
  skill_id?: number | null
  status: string
  model?: string | null
  error_detail?: string | null
  retries?: number
  created_at?: string
}

// ProcessingPage — 提取作业状态页（/processing/:runId）：轮询直到 verified/failed，
// failed 提供重试按钮（有界），verified 后自动刷新全局并显示"查看技能"入口。
export function ProcessingPage({ runId, skillId, onBack, refresh, onViewSkill }: {
  runId: number
  skillId: number | null
  onBack: () => void
  refresh: () => void
  onViewSkill?: (skillId: number) => void
}) {
  const [run, setRun] = useState<Run | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [retrying, setRetrying] = useState(false)
  const [deleting, setDeleting] = useState(false)
  // 轮询状态：初载 + 定时轮询（setInterval，不依赖 status 触发——单次请求失败
  // 不会杀死轮询，直到终态或组件卸载才停止）
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = () => {
    setError("")
    void api.getExtractionRun(runId).then((d: any) => {
      setRun(d); setLoading(false)
    }).catch(() => { /* 保留当前 run，等待下一轮；不置 loading=false 以免闪屏 */ })
  }

  useEffect(() => {
    setLoading(true); setError("")
    load()
    // 每 1.5s 轮询一次直到终态；clear 由终态 effect 或卸载执行
    pollRef.current = setInterval(load, 1500)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [runId])

  // 终态（verified/failed）停止轮询 + 同步一次全局数据
  const terminalRef = useRef<string | null>(null)
  useEffect(() => {
    if (run && (run.status === "verified" || run.status === "failed")) {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
      if (terminalRef.current !== run.status) {
        terminalRef.current = run.status
        refresh()
      }
    }
  }, [run?.status, refresh])

  const retry = async () => {
    setRetrying(true); setError("")
    try {
      await api.retryExtractionRun(runId)
      setRun((r) => r ? { ...r, status: "queued" } : r)
      // 重新开始轮询（终态 effect 之前停掉了 interval）
      terminalRef.current = null
      if (!pollRef.current) pollRef.current = setInterval(load, 1500)
      refresh()
    } catch (e) { setError((e as Error).message) } finally { setRetrying(false) }
  }

  const del = async () => {
    if (!window.confirm(`删除提取作业 #${runId} 及其产生的单元？`)) return
    setDeleting(true); setError("")
    try {
      await api.deleteExtractionRun(runId)
      refresh()
      onBack()
    } catch (e) { setError((e as Error).message); setDeleting(false) }
  }

  if (loading && !run) return <div className="flex min-h-dvh items-center justify-center"><Spinner className="h-6 w-6" /></div>
  if (error && !run) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-10">
        <button onClick={onBack} className="mb-4 text-sm text-zinc-500 hover:text-accent">← 返回花园</button>
        <Card>
          <CardBody className="py-12 text-center">
            <div className="text-4xl">🔍</div>
            <h2 className="mt-3 text-lg font-semibold text-ink">作业不存在</h2>
            <p className="mt-2 text-sm text-zinc-500">{error}</p>
            <div className="mt-5"><Button onClick={onBack}>返回花园</Button></div>
          </CardBody>
        </Card>
      </div>
    )
  }

  const tone = run?.status === "verified" ? "success" : run?.status === "failed" ? "danger" : "default"

  return (
    <div className="mx-auto max-w-2xl px-6 py-8">
      <button onClick={onBack} className="mb-4 text-sm text-zinc-500 hover:text-accent">← 返回花园</button>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-ink">提取作业 #{run?.id}</h1>
          <p className="mt-1 text-sm text-zinc-500">材料 #{run?.material_id} · 模型 {run?.model ?? "未知"}</p>
        </div>
        <Badge tone={tone}>{run?.status}</Badge>
      </div>

      <Card>
        <CardHeader title="状态" sub={run?.status === "verified" ? "验证完成，可开始学习" : "正在本地 GPU 上处理…"} />
        <CardBody className="space-y-3">
          {(run?.status === "queued" || run?.status === "running") && (
            <div className="flex items-center gap-2 text-sm text-zinc-500">
              <Spinner className="h-4 w-4" /> 正在提取并验证学习单元…
            </div>
          )}
          {run?.status === "failed" && (
            <div className="space-y-2">
              <p className="text-sm text-red-600">{run.error_detail ?? "提取失败"}</p>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={retry} disabled={retrying}>
                  {retrying ? <><Spinner /> 重试中</> : `重试（已重试 ${run.retries ?? 0} 次）`}
                </Button>
                <Button variant="danger" onClick={del} disabled={deleting}>
                  {deleting ? "删除中…" : "删除"}
                </Button>
              </div>
            </div>
          )}
          {run?.status === "verified" && (
            <div className="space-y-2">
              <p className="text-sm text-emerald-700">全部单元已通过来源校验与 entailment 验证，可以开始学习了。</p>
              <div className="flex gap-2">
                {(skillId !== null || run.skill_id != null) && onViewSkill && (
                  <Button onClick={() => onViewSkill!(Number(skillId ?? run.skill_id))}>查看技能</Button>
                )}
                <Button variant="danger" onClick={del} disabled={deleting}>
                  {deleting ? "删除中…" : "删除该提取及其单元"}
                </Button>
              </div>
            </div>
          )}
          {error && <p className="text-sm text-red-600">{error}</p>}
        </CardBody>
      </Card>
    </div>
  )
}
