import { useCallback, useEffect, useState } from 'react'
import PlannerPage from './pages/PlannerPage'
import JobsPage from './pages/JobsPage'
import AboutPage from './pages/AboutPage'
import LoginPage from './pages/LoginPage'
import { clearToken, getToken, setToken, setUnauthorizedHandler } from './api'

export type Tab = 'planner' | 'jobs' | 'about'

const TABS: { id: Tab; label: string }[] = [
  { id: 'planner', label: 'Create' },
  { id: 'jobs', label: 'Jobs' },
  { id: 'about', label: 'Status' },
]

function Brand() {
  return (
    <div className="flex items-center gap-3">
      <div className="clip-angled-sm flex h-9 w-9 shrink-0 items-center justify-center bg-gradient-to-br from-radeon-500 to-ember-600 text-[15px] font-black text-white glow-red-sm">
        LD
      </div>
      <div className="leading-tight">
        <div className="text-[15px] font-black italic tracking-tight text-fg">
          LIVE-SCIENCE
        </div>
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-dim">
          Document-to-video engine · AMD Radeon
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const [token, setTokenState] = useState<string | null>(() => getToken())
  const [tab, setTab] = useState<Tab>('planner')
  const [trackedJobId, setTrackedJobId] = useState<string | null>(null)

  useEffect(() => {
    setUnauthorizedHandler(() => setTokenState(null))
    return () => setUnauthorizedHandler(null)
  }, [])

  const handleLogin = useCallback((t: string) => {
    setToken(t)
    setTokenState(t)
  }, [])

  const handleLogout = useCallback(() => {
    clearToken()
    setTokenState(null)
    setTab('planner')
  }, [])

  const goJobs = useCallback((jobId?: string) => {
    if (jobId) setTrackedJobId(jobId)
    setTab('jobs')
  }, [])

  const clearTracked = useCallback(() => setTrackedJobId(null), [])

  if (!token) {
    return <LoginPage onLogin={handleLogin} />
  }

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-20 border-b border-line bg-ink-950/85 backdrop-blur">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <Brand />
          <nav className="flex items-center gap-1">
            {TABS.map((t) => {
              const active = tab === t.id
              return (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`relative px-4 py-2 text-sm transition-colors ${
                    active ? 'font-semibold text-fg' : 'text-mut hover:text-fg'
                  }`}
                >
                  {t.label}
                  {active && (
                    <span className="energy-line absolute inset-x-3 -bottom-px h-[2px] glow-red-sm" />
                  )}
                </button>
              )
            })}
            <button
              onClick={handleLogout}
              title="Log out"
              className="clip-angled-sm ml-2 border border-line px-3.5 py-1.5 text-sm text-mut transition-all hover:border-radeon-500/60 hover:text-radeon-400"
            >
              Log out
            </button>
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        {/* Pages stay mounted (hidden) so PlannerPage keeps its in-progress
            state across tab switches; JobsPage/AboutPage only poll while
            their tab is active. */}
        <div className={tab === 'planner' ? '' : 'hidden'}>
          <PlannerPage onSubmitted={goJobs} />
        </div>
        <div className={tab === 'jobs' ? '' : 'hidden'}>
          <JobsPage trackedJobId={trackedJobId} active={tab === 'jobs'} onTrackedDone={clearTracked} />
        </div>
        <div className={tab === 'about' ? '' : 'hidden'}>
          <AboutPage active={tab === 'about'} />
        </div>
      </main>

      <footer className="border-t border-line py-3 text-center font-mono text-[10px] uppercase tracking-[0.16em] text-dim">
        Live-Science · Local inference / Radeon ROCm ready · AMD DevMaster Track 1
      </footer>
    </div>
  )
}
