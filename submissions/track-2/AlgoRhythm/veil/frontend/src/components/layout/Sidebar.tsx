import { cn } from '@/lib/utils'
import { useApp, type Page } from '@/context/AppContext'
import {
  LayoutDashboard, FileText, Activity, Shield,
  Clock, LogOut, ChevronRight,
} from 'lucide-react'

const NAV_ITEMS: { id: Page; label: string; icon: typeof LayoutDashboard; auditorOnly?: boolean }[] = [
  { id: 'overview',  label: 'Overview',  icon: LayoutDashboard },
  { id: 'documents', label: 'Documents', icon: FileText },
  { id: 'audit',     label: 'Workspace', icon: Activity },
  { id: 'activity',  label: 'Audit Log', icon: Clock, auditorOnly: true },
  { id: 'security',  label: 'Security',  icon: Shield },
]

export function Sidebar() {
  const { auth, logout, currentPage, setCurrentPage } = useApp()

  if (!auth) return null

  const visibleItems = NAV_ITEMS.filter(item =>
    !item.auditorOnly || auth.role === 'auditor'
  )

  return (
    <aside className="w-56 flex-shrink-0 border-r border-gray-200 bg-white flex flex-col h-full">
      {/* Brand */}
      <div className="px-4 py-4 border-b border-gray-100">
        <div className="flex items-baseline gap-2">
          <span className="text-base font-bold tracking-tight text-gray-900">VEIL</span>
          <span className="text-2xs text-gray-400 tracking-wide">Privacy Audit</span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-3 px-2 space-y-0.5" role="navigation" aria-label="Main navigation">
        {visibleItems.map(({ id, label, icon: Icon }) => {
          const active = currentPage === id
          return (
            <button
              key={id}
              onClick={() => setCurrentPage(id)}
              className={cn(
                'w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors duration-100 text-left',
                active
                  ? 'bg-gray-100 text-gray-900 font-medium'
                  : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900',
              )}
              aria-current={active ? 'page' : undefined}
            >
              <Icon size={15} className={cn(active ? 'text-gray-700' : 'text-gray-400')} />
              {label}
              {active && <ChevronRight size={12} className="ml-auto text-gray-400" />}
            </button>
          )
        })}
      </nav>

      {/* Bottom: role + logout */}
      <div className="border-t border-gray-100 p-3">
        <div className="flex items-center gap-2 px-2 py-1.5 mb-1">
          <div className="w-6 h-6 rounded-full bg-gray-900 flex items-center justify-center">
            <span className="text-2xs font-bold text-white uppercase">
              {auth.role[0]}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium text-gray-900 capitalize">{auth.role}</p>
            <p className="text-2xs text-gray-400">Authenticated</p>
          </div>
        </div>
        <button
          onClick={logout}
          className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-sm text-gray-500 hover:text-gray-900 hover:bg-gray-50 transition-colors"
        >
          <LogOut size={14} />
          Sign out
        </button>
      </div>
    </aside>
  )
}
