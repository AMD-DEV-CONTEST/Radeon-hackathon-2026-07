import { useEffect, useState } from "react"
import { api } from "../lib/api"
import { Card, CardBody, CardHeader } from "../components/ui/Card"
import { Button } from "../components/ui/Button"
import { Progress } from "../components/ui/Progress"
import { Badge } from "../components/ui/Badge"
import { Spinner } from "../components/ui/Spinner"

interface GardenItem {
  skill_id: number
  name: string
  growth_value: number
  status: string
  learned_verified: number
  total_verified: number
  overdue_count: number
}

const statusTone = (s: string) => (s === "成熟" ? "success" : s === "衰退" ? "danger" : s === "生长中" ? "default" : "muted") as "success" | "danger" | "default" | "muted"

// GardenPage — 从 Todo 2 派生公式渲染花园状态与到期工作（非固定 growth）。
export function GardenPage({ onOpen, onUpload, refreshKey }: {
  onOpen: (id: number) => void
  onUpload: () => void
  refreshKey: number
}) {
  const [gardens, setGardens] = useState<GardenItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    setLoading(true); setError("")
    void api.gardenList().then((d) => {
      setGardens(d.gardens); setLoading(false)
    }).catch((e) => { setError((e as Error).message); setLoading(false) })
  }, [refreshKey])

  if (loading) return <div className="flex min-h-dvh items-center justify-center"><Spinner className="h-6 w-6" /></div>
  if (error) return <div className="mx-auto max-w-5xl px-8 py-8 text-sm text-red-600">{error}</div>

  const due = gardens.filter((g) => g.overdue_count > 0)

  return (
    <div className="mx-auto max-w-5xl px-6 py-8 md:px-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-ink">技能花园</h1>
          <p className="mt-1 text-sm text-zinc-500">生长值由已验证单元覆盖与掌握度派生；到期复习会让植物衰退。</p>
        </div>
        <Button onClick={onUpload}>＋ 上传新资料</Button>
      </div>

      {due.length > 0 && (
        <Card className="mb-6 border-amber-200 bg-amber-50">
          <CardBody className="flex flex-wrap items-center gap-2">
            <Badge tone="warn">⏰ 到期复习 {due.length}</Badge>
            {due.map((g) => (
              <button key={g.skill_id} onClick={() => onOpen(g.skill_id)}
                className="rounded-full border border-amber-300 bg-white px-3 py-1 text-xs text-amber-800 hover:bg-amber-100">
                {g.name}（{g.overdue_count} 单元）
              </button>
            ))}
          </CardBody>
        </Card>
      )}

      {gardens.length === 0 ? (
        <Card>
          <CardBody className="py-16 text-center">
            <div className="text-4xl">🌱</div>
            <p className="mt-3 text-sm text-zinc-500">花园还是空的。上传一份学习资料，让 Agent 抽取并验证单元开始生长吧。</p>
            <Button className="mt-4" onClick={onUpload}>开始上传</Button>
          </CardBody>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {gardens.map((g) => {
            const tone = statusTone(g.status)
            return (
              <button key={g.skill_id} onClick={() => onOpen(g.skill_id)} className="text-left">
                <Card className="h-full transition-shadow hover:shadow-md">
                  <CardHeader
                    title={g.name}
                    right={<Badge tone={tone}>{g.status}</Badge>}
                    sub={`${g.learned_verified}/${g.total_verified} 已验证单元已学`}
                  />
                  <CardBody>
                    <div className="mb-1 flex items-center justify-between text-xs text-zinc-500">
                      <span>生长值（派生）</span>
                      <span className="font-semibold text-accent">{g.growth_value} / 100</span>
                    </div>
                    <Progress value={g.growth_value} />
                    <div className="mt-3 flex items-center gap-2 text-xs">
                      {g.overdue_count > 0
                        ? <Badge tone="danger">{g.overdue_count} 个单元到期</Badge>
                        : <Badge tone="muted">无到期复习</Badge>}
                    </div>
                  </CardBody>
                </Card>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
