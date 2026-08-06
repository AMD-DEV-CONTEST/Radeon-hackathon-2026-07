import {
  Bot,
  Boxes,
  Brain,
  ChevronDown,
  Flame,
  Gamepad2,
  GitBranch,
  LayoutDashboard,
  Layers,
  LogOut,
  Menu,
  Package,
  Server,
  User,
  UserPlus,
  X,
  Zap,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Button } from '../ui/button'
import { LanguageSwitcher } from './LanguageSwitcher'
import { cn } from '../../lib/utils'
import { useAuth } from '../../lib/authContext'
import { prefetchRoute } from '../../lib/routePrefetch'
import { useT } from '../../i18n'
import type { LucideIcon } from 'lucide-react'

/* ------------------------------------------------------------------ */
/*  Navigation structure                                               */
/* ------------------------------------------------------------------ */

interface NavLink {
  name: string
  href: string
  icon?: LucideIcon
}

interface NavGroup {
  name: string
  children: NavLink[]
}

type NavEntry = NavLink | NavGroup

function isGroup(e: NavEntry): e is NavGroup {
  return 'children' in e
}

/* ------------------------------------------------------------------ */
/*  Dropdown component (shared by Build + User)                        */
/* ------------------------------------------------------------------ */

function Dropdown({
  trigger,
  children,
  align = 'left',
}: {
  trigger: React.ReactNode
  children: React.ReactNode
  align?: 'left' | 'right'
}) {
  const [open, setOpen] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  const scheduleClose = () => {
    timerRef.current = setTimeout(() => setOpen(false), 150)
  }
  const cancelClose = () => {
    if (timerRef.current) clearTimeout(timerRef.current)
  }

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  return (
    <div
      ref={ref}
      className="relative"
      onMouseEnter={() => {
        cancelClose()
        setOpen(true)
      }}
      onMouseLeave={scheduleClose}
    >
      {trigger}
      {open && (
        <div
          className={cn(
            'absolute top-full mt-1 z-50 min-w-[200px] rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--popover))] p-1.5 shadow-lg',
            align === 'right' ? 'right-0' : 'left-0',
          )}
        >
          {children}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Navbar                                                             */
/* ------------------------------------------------------------------ */

export function Navbar() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const t = useT()

  const pathname = location.pathname

  const navEntries: NavEntry[] = useMemo(
    () => [
      { name: t('nav.robots'), href: '/robots' },
      { name: t('nav.setup'), href: '/setup' },
      {
        name: t('nav.lab'),
        children: [
          { name: t('nav.datasets'), href: '/datasets', icon: Layers },
          { name: t('nav.training'), href: '/training', icon: Flame },
          { name: t('nav.models'), href: '/models', icon: Boxes },
          { name: t('nav.skills'), href: '/skills', icon: Zap },
          { name: t('nav.workflow'), href: '/workflow', icon: GitBranch },
          { name: t('nav.teleop'), href: '/teleop', icon: Gamepad2 },
          { name: t('nav.inference'), href: '/inference', icon: Brain },
          // Reachy Apps 是单机型页，与平台级入口平级不成立；但 Reachy 页内暂无入口，
          // 移除会孤儿化该页——保留至 T2-2 通用工作台落地后随机器人页内导航自然解决（M43 决策）。
          { name: t('nav.reachyApps'), href: '/robots/reachy_mini/apps', icon: Package },
        ],
      },
      { name: t('nav.remoteCompute'), href: '/settings/remote-compute', icon: Server },
    ],
    [t],
  )

  const isActive = (href: string) => {
    if (href === '/') return pathname === '/'
    return pathname === href || pathname.startsWith(href + '/')
  }

  const isGroupActive = (group: NavGroup) =>
    group.children.some((c) => isActive(c.href))

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  const linkClass = (active: boolean) =>
    cn(
      'relative px-4 py-2 text-sm font-medium transition-colors rounded-full',
      active
        ? 'text-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10'
        : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--muted))]',
    )

  const activeDot = (
    <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-1 h-1 bg-[hsl(var(--primary))] rounded-full" />
  )

  return (
    <header className="sticky top-0 z-50 w-full border-b border-white/[0.06] bg-[var(--ink)]/80 backdrop-blur-xl supports-[backdrop-filter]:bg-[var(--ink)]/70">
      <div className="container mx-auto px-4">
        <div className="flex h-16 items-center justify-between">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--ember)]/15 ring-1 ring-[var(--ember)]/25">
              <Bot className="h-5 w-5 text-[var(--ember)]" />
            </div>
            <span className="font-display text-lg font-bold tracking-tight">BotverseX</span>
          </Link>

          {/* Desktop Navigation */}
          <nav className="hidden md:flex items-center gap-1">
            {navEntries.map((entry) => {
              if (isGroup(entry)) {
                const groupActive = isGroupActive(entry)
                return (
                  <Dropdown
                    key={entry.name}
                    trigger={
                      <button className={cn(linkClass(groupActive), 'flex items-center gap-1')}>
                        {entry.name}
                        <ChevronDown className="h-3.5 w-3.5" />
                        {groupActive && activeDot}
                      </button>
                    }
                  >
                    {entry.children.map((child) => {
                      const Icon = child.icon
                      const active = isActive(child.href)
                      return (
                        <Link
                          key={child.href}
                          to={child.href}
                          onMouseEnter={() => prefetchRoute(child.href)}
                          onFocus={() => prefetchRoute(child.href)}
                          className={cn(
                            'flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors',
                            active
                              ? 'text-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10'
                              : 'text-[hsl(var(--popover-foreground))] hover:bg-[hsl(var(--muted))]',
                          )}
                        >
                          {Icon && <Icon className="h-4 w-4 shrink-0" />}
                          {child.name}
                        </Link>
                      )
                    })}
                  </Dropdown>
                )
              }

              const active = isActive(entry.href)
              const tourId =
                entry.href === '/setup'
                  ? 'nav-setup'
                  : entry.href === '/robots'
                    ? 'nav-robots'
                    : undefined
              return (
                <Link
                  key={entry.name}
                  to={entry.href}
                  onMouseEnter={() => prefetchRoute(entry.href)}
                  onFocus={() => prefetchRoute(entry.href)}
                  className={linkClass(active)}
                  data-tour={tourId}
                >
                  {entry.name}
                  {active && activeDot}
                </Link>
              )
            })}
          </nav>

          {/* User Menu (desktop) — 实验室工位仅 Pro 多机管理员需要，日常不占用顶栏 */}
          <div className="hidden md:flex items-center gap-2">
            <LanguageSwitcher />
            {user ? (
              <Dropdown
                align="right"
                trigger={
                  <button className="flex items-center gap-2 px-3 py-2 rounded-full text-sm transition-colors hover:bg-[hsl(var(--muted))]">
                    <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[hsl(var(--primary))]/15">
                      <User className="h-4 w-4 text-[hsl(var(--primary))]" />
                    </div>
                    <span className="max-w-[100px] truncate text-xs font-medium">
                      {user.username}
                    </span>
                    {user.entitlements?.display_name && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                        {user.entitlements.display_name}
                      </span>
                    )}
                    <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                  </button>
                }
              >
                <div className="px-3 py-2 border-b border-[hsl(var(--border))] mb-1">
                  <div className="text-sm font-medium truncate">{user.username}</div>
                  <div className="text-xs text-muted-foreground truncate">{user.email}</div>
                </div>
                <Link
                  to="/dashboard"
                  className={cn(
                    'flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors',
                    isActive('/dashboard')
                      ? 'text-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10'
                      : 'text-[hsl(var(--popover-foreground))] hover:bg-[hsl(var(--muted))]',
                  )}
                >
                  <LayoutDashboard className="h-4 w-4" />
                  {t('common.dashboard')}
                </Link>
                <button
                  onClick={handleLogout}
                  className="flex w-full items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-[hsl(var(--popover-foreground))] hover:bg-[hsl(var(--muted))] transition-colors"
                >
                  <LogOut className="h-4 w-4" />
                  {t('common.logout')}
                </button>
              </Dropdown>
            ) : (
              <div className="flex items-center gap-2">
                <Button variant="ghost" size="sm" onClick={() => navigate('/login')}>
                  {t('common.login')}
                </Button>
                <Button size="sm" onClick={() => navigate('/login?mode=register')}>
                  <UserPlus className="h-4 w-4 mr-1.5" />
                  {t('common.register')}
                </Button>
              </div>
            )}
          </div>

          {/* Mobile Menu Button */}
          <div className="flex items-center gap-1.5 md:hidden">
            <LanguageSwitcher />
            <button
              className="p-2 rounded-lg hover:bg-[hsl(var(--muted))]"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            >
              {mobileMenuOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
            </button>
          </div>
        </div>

        {/* Mobile Navigation */}
        {mobileMenuOpen && (
          <nav className="md:hidden py-4 border-t border-[hsl(var(--border))]/50">
            <div className="flex flex-col gap-1">
              {navEntries.map((entry) => {
                if (isGroup(entry)) {
                  return (
                    <div key={entry.name}>
                      <div className="px-4 pt-3 pb-1 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
                        {entry.name}
                      </div>
                      {entry.children.map((child) => {
                        const Icon = child.icon
                        const active = isActive(child.href)
                        return (
                          <Link
                            key={child.href}
                            to={child.href}
                            onMouseEnter={() => prefetchRoute(child.href)}
                            onClick={() => {
                              prefetchRoute(child.href)
                              setMobileMenuOpen(false)
                            }}
                            className={cn(
                              'flex items-center gap-2.5 px-4 py-3 text-sm font-medium rounded-lg transition-colors',
                              active
                                ? 'text-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10'
                                : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--muted))]',
                            )}
                          >
                            {Icon && <Icon className="h-4 w-4 shrink-0" />}
                            {child.name}
                          </Link>
                        )
                      })}
                    </div>
                  )
                }
                const active = isActive(entry.href)
                const tourId =
                  entry.href === '/setup'
                    ? 'nav-setup'
                    : entry.href === '/robots'
                      ? 'nav-robots'
                      : undefined
                return (
                  <Link
                    key={entry.name}
                    to={entry.href}
                    onClick={() => setMobileMenuOpen(false)}
                    className={cn(
                      'px-4 py-3 text-sm font-medium rounded-lg transition-colors',
                      active
                        ? 'text-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10'
                        : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--muted))]',
                    )}
                    data-tour={tourId}
                  >
                    {entry.name}
                  </Link>
                )
              })}

              <div className="mt-2 pt-2 border-t border-[hsl(var(--border))]/50">
                {user ? (
                  <button
                    onClick={() => {
                      setMobileMenuOpen(false)
                      handleLogout()
                    }}
                    className="flex w-full items-center gap-2.5 px-4 py-3 text-sm font-medium rounded-lg text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--muted))] transition-colors"
                  >
                    <LogOut className="h-4 w-4" />
                    {t('common.logout')}
                  </button>
                ) : (
                  <div className="flex gap-2 px-4 py-3">
                    <Button
                      variant="outline"
                      className="flex-1"
                      onClick={() => {
                        setMobileMenuOpen(false)
                        navigate('/login')
                      }}
                    >
                      {t('common.login')}
                    </Button>
                    <Button
                      className="flex-1"
                      onClick={() => {
                        setMobileMenuOpen(false)
                        navigate('/login?mode=register')
                      }}
                    >
                      <UserPlus className="h-4 w-4 mr-1.5" />
                      {t('common.register')}
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </nav>
        )}
      </div>
    </header>
  )
}
