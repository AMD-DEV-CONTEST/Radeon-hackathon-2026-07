import { useEffect, useState } from "react"
import { api } from "../lib/api"
import { Button } from "../components/ui/Button"
import { Card, CardBody, CardHeader } from "../components/ui/Card"
import { Badge } from "../components/ui/Badge"
import { Spinner } from "../components/ui/Spinner"

interface Unit {
  id: number
  skill_id: number
  content: string
  source_quote?: string | null
  source_material?: string | null
  key_points?: string[]
  example?: string | null
  pitfall?: string | null
  status: string
}

interface Run {
  id: number
  material_id: number
  status: string
  model?: string | null
  error_detail?: string | null
  retries?: number
  created_at?: string
  material_text?: string
}

// SkillDetailPage — 材料/作业来源 + 已验证单元进度 + 仅有效下一步动作（Todo 10）。
export function SkillDetailPage({ skillId, onBack, onReview, onLearn, onAssessment, onProcessing, onSource }: {
  skillId: number
  onBack: () => void
  onReview: () => void
  onLearn: () => void
  onAssessment: () => void
  onProcessing: (runId: number) => void
  onSource: (materialId: number) => void
}) {
  const [garden, setGarden] = useState<{ name: string; growth_value: number; status: string } | null>(null)
  const [units, setUnits] = useState<Unit[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [deleting, setDeleting] = useState(false)

  const load = () => {
    setLoading(true); setError("")
    void api.garden(skillId).then((d: any) => { setGarden(d); setLoading(false) })
      .catch((e) => { setError((e as Error).message); setLoading(false) })
    void api.getSkillUnits(skillId).then((d) => { setUnits(d.units); setLoading(false) })
      .catch((e) => { setError((e as Error).message); setLoading(false) })
    void api.getSkillRuns(skillId).then((d) => { setRuns(d.runs); setLoading(false) })
      .catch(() => {})
  }
  useEffect(load, [skillId])

  // 有运行中/排队作业时轮询，提取完成后自动刷新单元列表（无需手动刷新）
  useEffect(() => {
    const hasPending = runs.some((r) => r.status === "queued" || r.status === "running")
    if (!hasPending) return
    const t = setTimeout(load, 1500)
    return () => clearTimeout(t)
  }, [runs])

  const del = async () => {
    if (!window.confirm(`删除技能「${garden?.name ?? skillId}」及其全部材料、单元、作业？此操作不可撤销。`)) return
    setDeleting(true); setError("")
    try {
      await api.deleteSkill(skillId)
      onBack()
    } catch (e) { setError((e as Error).message); setDeleting(false) }
  }

  if (loading) return <div className="flex min-h-dvh items-center justify-center"><Spinner className="h-6 w-6" /></div>
  if (error && !garden) return <div className="mx-auto max-w-4xl px-6 py-8 text-sm text-red-600">{error}</div>

  const verified = units.filter((u) => u.status === "verified")
  const preview = units.filter((u) => u.status === "preview")
  const pendingRuns = runs.filter((r) => r.status === "queued" || r.status === "running")
  const failedRuns = runs.filter((r) => r.status === "failed")

  return (
    <div className="mx-auto max-w-4xl px-6 py-8 md:px-8">
      <button onClick={onBack} className="mb-4 text-sm text-zinc-500 hover:text-accent">← 返回花园</button>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-ink">{garden?.name ?? `技能 #${skillId}`}</h1>
          <p className="mt-1 text-sm text-zinc-500">
            生长值 {garden?.growth_value ?? 0}/100（派生） · {garden?.status ?? "—"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={garden?.status === "成熟" ? "success" : garden?.status === "衰退" ? "danger" : "default"}>
            {garden?.status ?? "—"}
          </Badge>
          <Button variant="danger" onClick={del} disabled={deleting} className="!px-2 !py-1 text-xs">
            {deleting ? "删除中…" : "删除"}
          </Button>
        </div>
      </div>

      {/* 有效下一步：仅当有已验证单元时提供学习/评估；复习按到期进入 */}
      <Card className="mb-6">
        <CardHeader title="下一步"
          right={<div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={onLearn} disabled={verified.length === 0}>开始学习</Button>
            <Button variant="secondary" onClick={onAssessment} disabled={verified.length === 0}>首次评估</Button>
            <Button onClick={onReview} disabled={verified.length === 0}>到期复习</Button>
          </div>} />
        <CardBody className="text-sm text-zinc-500">
          {verified.length === 0
            ? "还没有已验证的学习单元：先上传资料并等待验证通过，才能开始学习。"
            : `${verified.length} 个已验证单元可学习；评估后会调度间隔复习。`}
        </CardBody>
      </Card>

      {/* 作业状态（来源 provenance） */}
      {runs.length > 0 && (
        <Card className="mb-6">
          <CardHeader title={`提取作业（${runs.length}）`} sub="材料 → 验证 来源追踪" />
          <CardBody className="space-y-2">
            {runs.map((r) => (
              <div key={r.id} className="flex items-start justify-between gap-3 rounded-lg border border-zinc-100 bg-paper-soft px-4 py-3">
                <div className="min-w-0">
                  <button onClick={() => onProcessing(r.id)} className="text-left text-sm font-medium text-accent hover:underline">
                    作业 #{r.id} · 材料 #{r.material_id}
                  </button>
                  <button onClick={() => onSource(r.material_id)}
                    className="ml-2 text-xs text-zinc-400 hover:text-accent hover:underline">
                    查看源文档
                  </button>
                  {r.material_text && <div className="mt-1 truncate text-xs text-zinc-400">{r.material_text.slice(0, 80)}…</div>}
                  {r.status === "failed" && r.error_detail && (
                    <div className="mt-1 text-xs text-red-600">失败：{r.error_detail}</div>
                  )}
                </div>
                <Badge tone={r.status === "verified" ? "success" : r.status === "failed" ? "danger" : "default"}>
                  {r.status}
                </Badge>
              </div>
            ))}
          </CardBody>
        </Card>
      )}

      {/* 已验证单元进度 */}
      <Card>
        <CardHeader title={`已验证单元（${verified.length}）`} sub="点击单元可查看来源" />
        <CardBody className="space-y-2">
          {verified.length === 0 && preview.length === 0 && <div className="py-8 text-center text-sm text-zinc-400">暂无单元</div>}
          {preview.length > 0 && !pendingRuns.length && !failedRuns.length && (
            <div className="rounded-lg bg-paper-soft px-4 py-3 text-sm text-zinc-500">
              有 {preview.length} 个预览单元等待验证。
            </div>
          )}
          {verified.map((u, i) => (
            <div key={u.id} className="rounded-lg border border-zinc-100 bg-paper-soft px-4 py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="text-sm text-ink">
                  <span className="mr-2 font-mono text-xs text-zinc-400">{i + 1}</span>
                  {u.content}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {u.source_material && (
                    <button onClick={() => onSource(Number(u.source_material))}
                      className="text-xs text-zinc-400 hover:text-accent hover:underline">
                      查看来源
                    </button>
                  )}
                  <Badge tone="success">verified</Badge>
                </div>
              </div>
              {u.key_points && u.key_points.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1 pl-6">
                  {u.key_points.map((kp) => <Badge key={kp} tone="warn">{kp}</Badge>)}
                </div>
              )}
              {u.source_quote && <div className="mt-1 pl-6 text-xs text-zinc-400">来源：{u.source_quote}</div>}
            </div>
          ))}
        </CardBody>
      </Card>
    </div>
  )
}
