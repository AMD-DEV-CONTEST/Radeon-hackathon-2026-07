import type { ReactNode } from 'react'
import { useAuth } from '../auth/AuthContext'

const appVersion = typeof __APP_VERSION__ === 'undefined' ? '0.1.0' : __APP_VERSION__

/** App shell: top navigation bar with brand, current user, and sign-out. */
export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  return (
    <div>
      <nav className="topnav">
        <span className="brand">ProjectPack 智能办公助手 <small className="app-version" title="前端发布版本">v{appVersion}</small></span>
        <span className="user">
          <span>{user?.display_name ?? user?.username ?? '访客'}</span>
          <button type="button" className="retry" onClick={logout}>
            退出登录
          </button>
        </span>
      </nav>
      <main className="main">{children}</main>
    </div>
  )
}
