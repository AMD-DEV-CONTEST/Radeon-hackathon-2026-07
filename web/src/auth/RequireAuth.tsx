import { Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from './AuthContext'
import { FullScreenLoading } from '../components/feedback'

/**
 * Route guard for protected routes (UI-0 acceptance): an unauthenticated user
 * is redirected to /login, preserving the intended destination so they return
 * after signing in.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return <FullScreenLoading label="正在恢复登录状态…" />
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  return <>{children}</>
}
