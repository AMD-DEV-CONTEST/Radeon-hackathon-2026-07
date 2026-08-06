import { useEffect, useState } from "react"
import { api } from "../lib/api"
import { Button } from "../components/ui/Button"
import { Card, CardBody, CardHeader } from "../components/ui/Card"
import { Badge } from "../components/ui/Badge"
import { Spinner } from "../components/ui/Spinner"
import { saveDraft, loadDraft, clearDraft, draftKey } from "../lib/drafts"

interface ReviewUnit {
  id: number
  source_quote?: string | null
  source_start?: number | null
  source_end?: number | null
}

interface Attempt {
  score?: number
  status?: string
  needs_retry?: number
}

// ReviewPage — 到期复习：隐藏答案，给出来源提示，凭记忆回忆；
// 服务端提交（submitReview）重算评分并调度；支持一次覆盖（override）；
// 草稿按 (sessionId, unitId) 键存 sessionStorage，刷新/续接恢复。
export function ReviewPage({ skillId, onExit }: {
  skillId: number
  onExit: () => void
}) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [units, setUnits] = useState<ReviewUnit[]>([])
  const [index, setIndex] = useState(0)
  const [draft, setDraft] = useState("")
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState<Attempt | null>(null)
  const [done, setDone] = useState(false)
  const [overridden, setOverridden] = useState(false)

  const unit = units[index]
  const unitId = unit?.id ?? 0

  // resume: startReviewSession returns the existing active session when present
  const start = async () => {
    setLoading(true); setError("")
    try {
      const r = await api.startReviewSession(skillId)
      const sid = r.session?.id ?? null
      setSessionId(sid)
      setUnits((r.units as ReviewUnit[]) ?? [])
      setIndex(0)
      setDone((r.units ?? []).length === 0)
      setFeedback(null)
      if (sid != null && (r.units ?? []).length > 0) {
        setDraft(loadDraft(sid, (r.units as ReviewUnit[])[0].id))
      }
    } catch (e) {
      setError((e as Error).message)
    } finally { setLoading(false) }
  }
  useEffect(() => { void start() }, [skillId])

  const onDraft = (text: string) => {
    setDraft(text)
    if (sessionId != null && unitId != null) saveDraft(sessionId, unitId, text)
  }

  const submit = async () => {
    if (sessionId == null || unitId == null || !draft.trim() || busy) return
    setBusy(true); setError("")
    try {
      const r = await api.submitReview(sessionId, unitId, `review-${Date.now()}`, draft)
      setFeedback({ score: r.attempt?.score, status: r.attempt?.status, needs_retry: r.attempt?.needs_retry })
      clearDraft(sessionId, unitId)
      setDraft("")
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  const doOverride = async () => {
    if (sessionId == null || unitId == null || overridden || busy) return
    setBusy(true); setError("")
    try {
      await api.overrideReview(sessionId, unitId)
      setOverridden(true)
      setFeedback({ score: 3, status: "judged", needs_retry: 0 })
      clearDraft(sessionId, unitId)
      setDraft("")
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  const next = () => {
    if (index + 1 < units.length) {
      const nextIdx = index + 1
      setIndex(nextIdx)
      setFeedback(null)
      setOverridden(false)
      if (sessionId != null) setDraft(loadDraft(sessionId, units[nextIdx].id))
    } else {
      setDone(true)
    }
  }

  const abandon = async () => {
    if (sessionId != null) {
      try { await api.abandonSession(sessionId) } catch { /* best-effort */ }
      for (const u of units) clearDraft(sessionId, u.id)
    }
    onExit()
  }

  if (loading) return <div className="flex min-h-dvh items-center justify-center"><Spinner className="h-6 w-6" /></div>

  if (error && !sessionId) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-10">
        <button onClick={onExit} className="mb-4 text-sm text-zinc-500 hover:text-accent">← 返回技能</button>
        <Card>
          <CardBody className="py-12 text-center">
            <div className="text-4xl">🔕</div>
            <h2 className="mt-3 text-lg font-semibold text-ink">暂无可复习单元</h2>
            <p className="mt-2 text-sm text-zinc-500">{error}</p>
            <div className="mt-5"><Button onClick={onExit}>返回技能详情</Button></div>
          </CardBody>
        </Card>
      </div>
    )
  }

  if (done) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-10">
        <button onClick={onExit} className="mb-4 text-sm text-zinc-500 hover:text-accent">← 返回技能</button>
        <Card>
          <CardBody className="py-12 text-center">
            <div className="text-4xl">🌳</div>
            <h2 className="mt-3 text-xl font-bold text-ink">本轮复习完成</h2>
            <p className="mt-2 text-sm text-zinc-500">所有到期单元已按 SM-2 调度下一次复习。</p>
            <div className="mt-6"><Button onClick={onExit}>返回技能</Button></div>
          </CardBody>
        </Card>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-2xl px-6 py-8">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <button onClick={abandon} className="text-sm text-zinc-500 hover:text-accent">← 放弃并返回</button>
          <div className="mt-1 flex items-center gap-2">
            <h1 className="text-lg font-bold text-ink">到期复习</h1>
            <Badge tone="default">{index + 1}/{units.length}</Badge>
          </div>
        </div>
      </div>

      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}

      <Card>
        <CardHeader title="回忆关键点" sub="提示来自原始来源（答案已隐藏）" />
        <CardBody className="space-y-3">
          <div className="rounded-lg bg-paper-soft px-4 py-3 text-sm text-zinc-600">
            来源提示：{unit?.source_quote ?? "（无）"}
          </div>
          <textarea
            value={draft}
            onChange={(e) => onDraft(e.target.value)}
            placeholder="凭记忆写下这个单元的关键点…"
            className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-ink outline-none placeholder:text-zinc-400 focus:border-accent focus:ring-2 focus:ring-accent/20"
            rows={5}
            aria-label="复习回忆输入"
          />
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={submit} disabled={busy || !draft.trim()}>
              {busy ? <><Spinner /> 提交中</> : "提交回忆"}
            </Button>
            <Button variant="ghost" onClick={doOverride} disabled={overridden || busy}>
              {overridden ? "已覆盖" : "一次覆盖（记 3 分，间隔≤3 天）"}
            </Button>
            {feedback && (
              <Button variant="secondary" onClick={next}>下一个 →</Button>
            )}
          </div>
          {feedback && (
            <div className="rounded-lg bg-accent-dim px-4 py-3 text-sm">
              <span className="font-semibold text-accent">服务端评分：{feedback.score ?? "?"}/5</span>
              {feedback.needs_retry ? " · 需重试（间隔重置 1 天）" : " · 通过"}
            </div>
          )}
        </CardBody>
      </Card>
      {sessionId != null && unitId != null && (
        <p className="mt-2 text-xs text-zinc-400">草稿键：{draftKey(sessionId, unitId)}</p>
      )}
    </div>
  )
}
