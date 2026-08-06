import { useEffect, useState } from "react"
import { api } from "../lib/api"
import { Button } from "../components/ui/Button"
import { Card, CardBody, CardHeader } from "../components/ui/Card"
import { Badge } from "../components/ui/Badge"
import { Spinner } from "../components/ui/Spinner"
import { saveDraft, loadDraft, clearDraft, draftKey } from "../lib/drafts"

interface Unit {
  id: number
  skill_id: number
  content: string
  source_quote?: string | null
  status: string
}

// AssessmentPage — 首次评估：隐藏答案内容，给出来源提示，用户凭记忆回忆；
// 服务端重算权威评分；草稿按 (sessionId, unitId) 键存于 sessionStorage。
export function AssessmentPage({ skillId, onBack }: {
  skillId: number
  onBack: () => void
}) {
  const [skill, setSkill] = useState<{ id: number; name: string } | null>(null)
  const [units, setUnits] = useState<Unit[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [unitId, setUnitId] = useState<number | null>(null)
  const [draft, setDraft] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<string>("")

  const load = () => {
    setLoading(true); setError(""); setResult("")
    void api.getSkill(skillId).then((d: any) => {
      setSkill({ id: d.id, name: d.name })
      setLoading(false)
    }).catch((e) => { setError((e as Error).message); setLoading(false) })
    void api.getSkillUnits(skillId).then((d) => {
      const verified = d.units.filter((u) => u.status === "verified")
      setUnits(verified)
      setLoading(false)
      if (verified.length === 0) setError("该技能还没有已验证的学习单元")
    }).catch((e) => { setError((e as Error).message); setLoading(false) })
  }
  useEffect(load, [skillId])

  const start = async () => {
    setError(""); setResult("")
    try {
      const r = await api.startLearningSession(skillId)
      const sid = r.session?.id ?? null
      const uid = units[0]?.id ?? null
      setSessionId(sid); setUnitId(uid)
      if (sid != null && uid != null) setDraft(loadDraft(sid, uid))
    } catch (e) { setError((e as Error).message) }
  }

  const submit = async () => {
    if (sessionId == null || unitId == null || !draft.trim() || submitting) return
    setSubmitting(true); setError("")
    try {
      const r = await api.submitAssessment(sessionId, unitId, `assess-${Date.now()}`, draft)
      setResult(`评分：${r.attempt?.score ?? "?"}/5`)
      clearDraft(sessionId, unitId)
      setDraft("")
    } catch (e) {
      setError((e as Error).message)
    } finally { setSubmitting(false) }
  }

  if (loading) return <div className="flex min-h-dvh items-center justify-center"><Spinner className="h-6 w-6" /></div>
  if (error && units.length === 0) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-10">
        <button onClick={onBack} className="mb-4 text-sm text-zinc-500 hover:text-accent">← 返回技能</button>
        <Card>
          <CardBody className="py-12 text-center">
            <div className="text-4xl">📝</div>
            <h2 className="mt-3 text-lg font-semibold text-ink">暂无可评估内容</h2>
            <p className="mt-2 text-sm text-zinc-500">{error}</p>
            <div className="mt-5"><Button onClick={onBack}>返回技能详情</Button></div>
          </CardBody>
        </Card>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-2xl px-6 py-8">
      <button onClick={onBack} className="mb-4 text-sm text-zinc-500 hover:text-accent">← 返回技能</button>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-ink">首次评估 · {skill?.name}</h1>
          <p className="mt-1 text-sm text-zinc-500">不看答案，凭来源提示回忆关键点。刷新会恢复草稿。</p>
        </div>
        <Badge tone="default">{units.length} 个单元</Badge>
      </div>

      {sessionId == null ? (
        <Card>
          <CardBody className="py-10 text-center">
            <p className="text-sm text-zinc-500">准备好后开始评估：</p>
            <div className="mt-4"><Button onClick={start}>开始评估</Button></div>
          </CardBody>
        </Card>
      ) : (
        <Card>
          <CardHeader title="回忆关键点" sub="提示来自原始来源（隐藏答案）" />
          <CardBody className="space-y-3">
            <div className="rounded-lg bg-paper-soft px-4 py-3 text-sm text-zinc-600">
              来源提示：{units[0]?.source_quote ?? "（无）"}
            </div>
            <textarea
              value={draft}
              onChange={(e) => { setDraft(e.target.value); if (sessionId != null && unitId != null) saveDraft(sessionId, unitId, e.target.value) }}
              placeholder="凭记忆写下这个单元的关键点…"
              className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-ink outline-none placeholder:text-zinc-400 focus:border-accent focus:ring-2 focus:ring-accent/20"
              rows={5}
              aria-label="回忆输入"
            />
            <div className="flex items-center gap-3">
              <Button onClick={submit} disabled={submitting || !draft.trim()}>
                {submitting ? <><Spinner /> 评估中</> : "提交评估"}
              </Button>
              <Button variant="ghost" onClick={() => { if (sessionId != null && unitId != null) { clearDraft(sessionId, unitId); setDraft("") } }}>清空草稿</Button>
            </div>
            {result && <p className="text-sm font-medium text-accent">{result}</p>}
            {error && <p className="text-sm text-red-600">{error}</p>}
          </CardBody>
        </Card>
      )}
      {sessionId != null && unitId != null && (
        <p className="mt-2 text-xs text-zinc-400">草稿键：{draftKey(sessionId, unitId)}</p>
      )}
    </div>
  )
}
