import { lazy, Suspense, useEffect, type ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/layout/Layout'
import { TourProvider } from './components/onboarding/TourProvider'
import { Robots } from './pages/Robots'
import { Login } from './pages/Login'
import { AuthProvider, RequireAuth } from './lib/authContext'
import { prefetchCommonRoutes } from './lib/routePrefetch'

const Dashboard = lazy(() => import('./pages/Dashboard').then((m) => ({ default: m.Dashboard })))
const RobotSO101 = lazy(() => import('./pages/RobotSO101').then((m) => ({ default: m.RobotSO101 })))
const RobotReachyMini = lazy(() =>
  import('./pages/RobotReachyMini').then((m) => ({ default: m.RobotReachyMini })),
)
const RobotB601 = lazy(() =>
  import('./pages/RobotB601').then((m) => {
    if (!m.RobotB601) {
      throw new Error('RobotB601 export missing — hard-refresh or restart vite (stale HMR cache)')
    }
    return { default: m.RobotB601 }
  }),
)
const RobotLeKiwi = lazy(() =>
  import('./pages/RobotLeKiwi').then((m) => ({ default: m.RobotLeKiwi })),
)
const RobotPreview = lazy(() =>
  import('./pages/RobotPreview').then((m) => ({ default: m.RobotPreview })),
)
const RobotVirtualPlay = lazy(() =>
  import('./pages/RobotVirtualPlay').then((m) => ({ default: m.RobotVirtualPlay })),
)
const ReachyMiniApps = lazy(() => import('./pages/ReachyMiniApps'))
const Datasets = lazy(() => import('./pages/Datasets').then((m) => ({ default: m.Datasets })))
const DatasetDetail = lazy(() =>
  import('./pages/DatasetDetail').then((m) => ({ default: m.DatasetDetail })),
)
const Models = lazy(() => import('./pages/Models').then((m) => ({ default: m.Models })))
const Training = lazy(() => import('./pages/Training').then((m) => ({ default: m.Training })))
const Compare = lazy(() => import('./pages/Compare').then((m) => ({ default: m.Compare })))
const AIHub = lazy(() => import('./pages/AIHub').then((m) => ({ default: m.AIHub })))
const AIHubDetail = lazy(() => import('./pages/AIHubDetail').then((m) => ({ default: m.AIHubDetail })))
const AIHubLeaderboard = lazy(() =>
  import('./pages/AIHubLeaderboard').then((m) => ({ default: m.AIHubLeaderboard })),
)
const WorkflowEditor = lazy(() =>
  import('./components/workflow/WorkflowEditor').then((m) => ({ default: m.WorkflowEditor })),
)
const Teleop = lazy(() => import('./pages/Teleop').then((m) => ({ default: m.Teleop })))
const Inference = lazy(() => import('./pages/Inference').then((m) => ({ default: m.Inference })))
const Skills = lazy(() => import('./pages/Skills').then((m) => ({ default: m.Skills })))
const Setup = lazy(() => import('./pages/Setup').then((m) => ({ default: m.Setup })))
const RemoteComputeSettings = lazy(() =>
  import('./pages/RemoteComputeSettings').then((m) => ({ default: m.RemoteComputeSettings })),
)

function PageLoader() {
  return (
    <div className="container mx-auto px-4 py-8 space-y-4 animate-pulse">
      <div className="h-8 w-48 rounded-lg bg-[hsl(var(--muted))]/50" />
      <div className="h-4 w-72 rounded bg-[hsl(var(--muted))]/30" />
      <div className="grid gap-4 md:grid-cols-2">
        <div className="h-40 rounded-xl bg-[hsl(var(--muted))]/25" />
        <div className="h-40 rounded-xl bg-[hsl(var(--muted))]/25" />
      </div>
    </div>
  )
}

function RoutePrefetchBoot() {
  useEffect(() => {
    const run = () => prefetchCommonRoutes()
    if ('requestIdleCallback' in window) {
      const id = window.requestIdleCallback(run, { timeout: 2500 })
      return () => window.cancelIdleCallback(id)
    }
    const t = window.setTimeout(run, 1200)
    return () => window.clearTimeout(t)
  }, [])
  return null
}

function LazyPage({ children }: { children: ReactNode }) {
  return <Suspense fallback={<PageLoader />}>{children}</Suspense>
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <RoutePrefetchBoot />
        <TourProvider>
          <Routes>
            <Route path="/login" element={<Login />} />

            {/* Home / robots catalog — eager load for fast first paint */}
            <Route path="/" element={<Layout><Robots /></Layout>} />
            <Route path="/robots" element={<Layout><Robots /></Layout>} />
            {/* 没真机也能玩：短链直达最厚的虚拟体验（Reachy 云端状态机） */}
            <Route
              path="/play"
              element={<Navigate to="/robots/reachy_mini?guide=virtual&play=1" replace />}
            />
            {/* 所有 runtime 的纯前端虚拟玩法（拖滑条驱动 URDF） */}
            <Route
              path="/robots/:runtimeId/play"
              element={
                <Layout>
                  <LazyPage>
                    <RobotVirtualPlay />
                  </LazyPage>
                </Layout>
              }
            />

            <Route
              path="/robots/so101"
              element={
                <Layout>
                  <LazyPage>
                    <RobotSO101 />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/robots/reachy_mini"
              element={
                <Layout>
                  <LazyPage>
                    <RobotReachyMini />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/robots/reachy_mini/apps"
              element={
                <Layout>
                  <LazyPage>
                    <ReachyMiniApps />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/robots/b601_rs"
              element={
                <Layout>
                  <LazyPage>
                    <RobotB601 />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/robots/b601_dm"
              element={
                <Layout>
                  <LazyPage>
                    <RobotB601 />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/robots/bi_b601_dm"
              element={
                <Layout>
                  <LazyPage>
                    <RobotB601 />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/robots/lekiwi"
              element={
                <Layout>
                  <LazyPage>
                    <RobotLeKiwi />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/robots/amazing_hand"
              element={
                <Layout>
                  <LazyPage>
                    <RobotPreview runtimeId="amazing_hand" />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/robots/unitree_g1"
              element={
                <Layout>
                  <LazyPage>
                    <RobotPreview runtimeId="unitree_g1" />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/ai-hub"
              element={
                <Layout>
                  <LazyPage>
                    <AIHub />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/ai-hub/model/:repo_id"
              element={
                <Layout>
                  <LazyPage>
                    <AIHubDetail />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/ai-hub/leaderboard"
              element={
                <Layout>
                  <LazyPage>
                    <AIHubLeaderboard />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/skills"
              element={
                <Layout>
                  <LazyPage>
                    <Skills />
                  </LazyPage>
                </Layout>
              }
            />
            <Route path="/pricing" element={<Navigate to="/robots" replace />} />
            <Route
              path="/setup"
              element={
                <Layout>
                  <LazyPage>
                    <Setup />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/settings/remote-compute"
              element={
                <Layout>
                  <LazyPage>
                    <RemoteComputeSettings />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/datasets"
              element={
                <Layout>
                  <LazyPage>
                    <Datasets />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/datasets/:datasetId"
              element={
                <Layout>
                  <LazyPage>
                    <DatasetDetail />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/datasets/:datasetId/compare/:modelKey"
              element={
                <Layout>
                  <LazyPage>
                    <Compare />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/models"
              element={
                <Layout>
                  <LazyPage>
                    <Models />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/training"
              element={
                <Layout>
                  <LazyPage>
                    <Training />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/workflow"
              element={
                <Layout>
                  <LazyPage>
                    <WorkflowEditor />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/teleop"
              element={
                <Layout>
                  <LazyPage>
                    <Teleop />
                  </LazyPage>
                </Layout>
              }
            />
            <Route
              path="/inference"
              element={
                <Layout>
                  <LazyPage>
                    <Inference />
                  </LazyPage>
                </Layout>
              }
            />

            <Route
              path="/dashboard"
              element={
                <RequireAuth>
                  <Layout>
                    <LazyPage>
                      <Dashboard />
                    </LazyPage>
                  </Layout>
                </RequireAuth>
              }
            />
          </Routes>
        </TourProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
