import { useEffect, useState } from "react"
import { createRouter, type Route } from "./lib/router"
import { GardenPage } from "./pages/GardenPage"
import { UploadPage } from "./pages/UploadPage"
import { SkillDetailPage } from "./pages/SkillDetailPage"
import { SourcePage } from "./pages/SourcePage"
import { ReviewPage } from "./pages/ReviewPage"
import { LearnPage } from "./pages/LearnPage"
import { AssessmentPage } from "./pages/AssessmentPage"
import { ProcessingPage } from "./pages/ProcessingPage"
import { api } from "./lib/api"

export type View = "garden" | "upload"

// useRouter — subscribe to history changes (popstate/pushState) via the router
function useRouter() {
  const [router] = useState(() => createRouter())
  const [, force] = useState(0)
  useEffect(() => router.subscribe(() => force((n) => n + 1)), [router])
  return router
}

interface GardenNav {
  skill_id: number
  name: string
  growth_value: number
  status: string
}

export default function App() {
  const router = useRouter()
  const route = router.route
  const [skills, setSkills] = useState<GardenNav[]>([])
  const [refreshKey, setRefreshKey] = useState(0)
  // 上传跳转到 processing 时记住 skillId，供 verified 后"查看技能"跳转
  const [runSkillId, setRunSkillId] = useState<number | null>(null)

  const refresh = () => setRefreshKey((k) => k + 1)
  useEffect(() => { void api.gardenList().then((d) => setSkills(d.gardens)).catch(() => {}) }, [refreshKey])

  const skillId = router.skillId
  const runId = router.runId

  // invalid-ID routes render an accessible recovery state
  if ((route.name === "skill" || route.name === "source" || route.name === "learn" || route.name === "assessment" || route.name === "review")
      && skillId === null) {
    return <RecoveryState label="无效的技能 ID" path={route.name} onHome={() => router.navigate({ name: "garden" })} />
  }
  if (route.name === "source" && router.materialId === null) {
    return <RecoveryState label="无效的源文档 ID" path="source" onHome={() => router.navigate({ name: "garden" })} />
  }
  if (route.name === "processing" && runId === null) {
    return <RecoveryState label="无效的作业 ID" path="processing" onHome={() => router.navigate({ name: "garden" })} />
  }
  if (route.name === "invalid") {
    return <RecoveryState label="页面不存在" path={route.path} onHome={() => router.navigate({ name: "garden" })} />
  }

  const navigate = (r: Route) => router.navigate(r)
  const openSkill = (id: number) => navigate({ name: "skill", skillId: String(id) })

  let main: React.ReactNode
  switch (route.name) {
    case "garden":
      main = <GardenPage onOpen={openSkill}
        onUpload={() => navigate({ name: "upload" })} refreshKey={refreshKey} />
      break
    case "upload":
      main = <UploadPage onImported={(runId, skillId) => { setRunSkillId(skillId); navigate({ name: "processing", runId: String(runId) }); refresh() }} />
      break
    case "processing":
      main = <ProcessingPage runId={runId as number} skillId={runSkillId}
        onBack={() => { refresh(); navigate({ name: "garden" }) }}
        refresh={refresh}
        onViewSkill={(sid: number) => { refresh(); navigate({ name: "skill", skillId: String(sid) }) }} />
      break
    case "skill":
      main = <SkillDetailPage skillId={skillId as number}
        onBack={() => { refresh(); navigate({ name: "garden" }) }}
        onReview={() => navigate({ name: "review", skillId: String(skillId) })}
        onLearn={() => navigate({ name: "learn", skillId: String(skillId) })}
        onAssessment={() => navigate({ name: "assessment", skillId: String(skillId) })}
        onProcessing={(rid) => navigate({ name: "processing", runId: String(rid) })}
        onSource={(mid) => navigate({ name: "source", skillId: String(skillId), materialId: String(mid) })} />
      break
    case "source":
      main = <SourcePage materialId={router.materialId as number} skillId={skillId as number}
        onBack={() => navigate({ name: "skill", skillId: String(skillId) })} />
      break
    case "learn":
      main = <LearnPage skillId={skillId as number} onBack={() => navigate({ name: "skill", skillId: String(skillId) })} />
      break
    case "assessment":
      main = <AssessmentPage skillId={skillId as number}
        onBack={() => navigate({ name: "skill", skillId: String(skillId) })} />
      break
    case "review":
      main = <ReviewPage skillId={skillId as number}
        onExit={() => { navigate({ name: "skill", skillId: String(skillId) }); refresh() }} />
      break
    default:
      main = <RecoveryState label="未知路由" path={(route as { name?: string }).name ?? ""} onHome={() => navigate({ name: "garden" })} />
  }

  return (
    <div className="flex min-h-dvh flex-col bg-paper md:flex-row">
      {/* sidebar: static on desktop, collapsible sheet on mobile (no fixed overflow) */}
      <aside className="w-full shrink-0 border-b border-zinc-200 bg-white md:flex md:w-60 md:flex-col md:border-r md:border-b-0">
        <div className="flex items-center justify-between border-b border-zinc-100 px-5 py-4 md:block">
          <div>
            <div className="text-base font-bold text-ink">学习花园</div>
            <div className="text-xs text-zinc-400">私有本地学习 Agent</div>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 py-2 md:flex-1 md:flex-col md:space-y-1 md:overflow-y-auto md:py-3" aria-label="主导航">
          <NavButton active={route.name === "garden"} onClick={() => navigate({ name: "garden" })}>🌱 技能花园</NavButton>
          <NavButton active={route.name === "upload"} onClick={() => navigate({ name: "upload" })}>📤 上传资料</NavButton>
          <div className="hidden pt-4 pb-1 px-3 text-xs font-medium text-zinc-400 md:block">我的技能</div>
          {skills.map((s) => (
            <NavButton key={s.skill_id} active={skillId === s.skill_id} onClick={() => openSkill(s.skill_id)}>
              <span className="block truncate">{s.name}</span>
              <span className="block text-xs text-zinc-400">{s.status} · 生长 {s.growth_value}</span>
            </NavButton>
          ))}
        </nav>
        <div className="hidden border-t border-zinc-100 px-5 py-3 text-xs text-zinc-400 md:block">
          推理：AMD Radeon · 全离线
        </div>
      </aside>

      <main className="min-h-dvh flex-1 overflow-x-hidden bg-paper">
        {main}
      </main>
    </div>
  )
}

function NavButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`shrink-0 rounded-lg px-3 py-2 text-left text-sm md:block md:w-full ${
        active ? "bg-accent-dim font-medium text-accent" : "text-ink-soft hover:bg-paper-soft"
      }`}
    >
      {children}
    </button>
  )
}

function RecoveryState({ label, path, onHome }: { label: string; path: string; onHome: () => void }) {
  return (
    <div className="flex min-h-dvh items-center justify-center p-6">
      <div role="alert" className="max-w-md text-center">
        <div className="text-4xl">🧭</div>
        <h1 className="mt-3 text-lg font-semibold text-ink">{label}</h1>
        <p className="mt-1 text-sm text-zinc-500">路径 /{path} 无法解析。你可以返回花园继续学习。</p>
        <button onClick={onHome}
          className="mt-5 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-light">
          返回花园
        </button>
      </div>
    </div>
  )
}
