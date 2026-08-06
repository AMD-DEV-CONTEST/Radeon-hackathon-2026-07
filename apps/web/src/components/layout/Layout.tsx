import { Navbar } from './Navbar'
import { CopilotWidget } from '../copilot/CopilotWidget'
import { ProductTour } from '../onboarding/ProductTour'
import { TourFab } from '../onboarding/TourLauncher'
import { PageGuideStrip } from '../onboarding/PageGuideStrip'
import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../../lib/authContext'

interface LayoutProps {
  children: React.ReactNode
}

export function Layout({ children }: LayoutProps) {
  const { pathname } = useLocation()
  const hideFooter = pathname.startsWith('/robots/')
  /** Catalog / home owns its own full-bleed composition (product landing, not dashboard). */
  const fullBleed = pathname === '/' || pathname === '/robots'
  const { authRequired, dismissAuthRequired } = useAuth()

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {authRequired && (
        <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-200">
          <span>登录已过期，部分数据与操作不可用。</span>
          <Link
            to={`/login?redirect=${encodeURIComponent(pathname)}`}
            className="font-medium text-[var(--paper)] underline underline-offset-2"
          >
            重新登录
          </Link>
          <button
            type="button"
            onClick={dismissAuthRequired}
            className="text-amber-200/60 underline-offset-2 hover:text-amber-100 hover:underline"
          >
            知道了
          </button>
        </div>
      )}
      <Navbar />
      <main
        className={
          fullBleed
            ? 'flex-1 min-h-0 w-full'
            : 'container mx-auto px-4 py-6 flex-1 min-h-0'
        }
      >
        {!fullBleed && <PageGuideStrip />}
        {children}
      </main>
      {!hideFooter && !fullBleed && (
        <footer className="border-t border-[hsl(var(--border))]/50 bg-[hsl(var(--background))]/95 shrink-0">
          <div className="container mx-auto px-4 py-4">
            <div className="flex items-center justify-center text-xs text-[hsl(var(--muted-foreground))]">
              <span>&copy; {new Date().getFullYear()} Botverse X</span>
            </div>
          </div>
        </footer>
      )}
      <CopilotWidget />
      <ProductTour />
      <TourFab />
    </div>
  )
}
