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
  key_points?: string[]
  example?: string | null
  pitfall?: string | null
  status: string
}

// LearnPage — 学习会话：揭示 explanation/key points/example/pitfall/source，
// 仅标记单元学习完成（不评分、不调度）。
export function LearnPage({ skillId, onBack }: { skillId: number; onBack: () => void }) {
  const [skill, setSkill] = useState<{ id: number; name: string } | null>(null)
  const [units, setUnits] = useState<Unit[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [draft, setDraft] = useState("")

  const load = () => {
    setLoading(true); setError("")
    void api.getSkill(skillId).then((d: any) => {
      setSkill({ id: d.id, name: d.name })
      setLoading(false)
    }).catch((e) => { setError((e as Error).message); setLoading(false) })
    void api.getSkillUnits(skillId).then((d) => {
      const verified = d.units.filter((u) => u.status === "verified")
      setUnits(verified)
      setLoading(false)
      if (verified.length === 0) { setError("该技能还没有已验证的学习单元"); return }
      // refresh/deep-link recovery: resume the active learn session (idempotent;
      // the server returns the existing active session) and restore the draft
      void api.startLearningSession(skillId).then((r) => {
        const sid = r.session?.id ?? null
        setSessionId(sid)
        if (sid != null) setDraft(loadDraft(sid, verified[0].id))
      }).catch(() => { /* no active session yet */ })
    }).catch((e) => { setError((e as Error).message); setLoading(false) })
  }
  useEffect(load, [skillId])

  const startLearn = async () => {
    setError("")
    try {
      const r = await api.startLearningSession(skillId)
      setSessionId(r.session?.id ?? null)
      if (r.session?.id != null) {
        setDraft(loadDraft(r.session.id, units[0]?.id ?? 0))
      }
      load()
    } catch (e) { setError((e as Error).message) }
  }

  const onDraft = (text: string) => {
    setDraft(text)
    if (sessionId != null && units[0] != null) saveDraft(sessionId, units[0].id, text)
  }

  const finishUnit = () => {
    if (sessionId != null && units[0] != null) clearDraft(sessionId, units[0].id)
    setDraft(""); setSessionId(null); load()
  }

  if (loading) return <div className="flex min-h-dvh items-center justify-center"><Spinner className="h-6 w-6" /></div>
  if (error && units.length === 0) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-10">
        <button onClick={onBack} className="mb-4 text-sm text-zinc-500 hover:text-accent">← 返回技能</button>
        <Card>
          <CardBody className="py-12 text-center">
            <div className="text-4xl">🌾</div>
            <h2 className="mt-3 text-lg font-semibold text-ink">暂无学习内容</h2>
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
          <h1 className="text-xl font-bold text-ink">学习 · {skill?.name}</h1>
          <p className="mt-1 text-sm text-zinc-500">揭示内容 → 用自己的话复述，草稿自动保存在本会话。</p>
        </div>
        <Badge tone="default">{units.length} 个单元</Badge>
      </div>

      {units.map((u, i) => (
        <Card key={u.id} className="mb-4">
          <CardHeader title={`单元 ${i + 1}`} right={<Badge tone="muted">verified</Badge>} />
          <CardBody className="space-y-3">
            <div className="text-base font-medium text-ink">{u.content}</div>
            {u.key_points && u.key_points.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {u.key_points.map((kp) => <Badge key={kp} tone="warn">{kp}</Badge>)}
              </div>
            )}
            {u.example && <p className="text-sm text-zinc-600">示例：{u.example}</p>}
            {u.pitfall && <p className="text-sm text-amber-700">易错点：{u.pitfall}</p>}
            {u.source_quote && <p className="rounded-lg bg-paper-soft px-3 py-2 text-xs text-zinc-500">来源：{u.source_quote}</p>}
          </CardBody>
        </Card>
      ))}

      {sessionId != null && units.length > 0 && (
        <Card>
          <CardHeader title="费曼复述" sub="写下你对本单元的理解（刷新后会自动恢复）" />
          <CardBody className="space-y-3">
            <textarea
              value={draft}
              onChange={(e) => onDraft(e.target.value)}
              placeholder="用自己的话复述这个单元…"
              className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-ink outline-none placeholder:text-zinc-400 focus:border-accent focus:ring-2 focus:ring-accent/20"
              rows={4}
              aria-label="费曼复述草稿"
            />
            <div className="flex gap-2">
              <Button onClick={finishUnit}>标记本单元完成</Button>
            </div>
          </CardBody>
        </Card>
      )}
      {units.length > 0 && sessionId == null && (
        <Card>
          <CardBody className="space-y-3">
            <Button onClick={startLearn}>开始学习</Button>
          </CardBody>
        </Card>
      )}
      {sessionId != null && <p className="mt-2 text-xs text-zinc-400">草稿键：{draftKey(sessionId, units[0]?.id ?? 0)}</p>}
    </div>
  )
}
