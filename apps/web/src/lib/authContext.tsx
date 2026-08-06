import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { Navigate, useLocation } from 'react-router-dom'

import {
  AuthRequiredError,
  clearAuthRequired,
  getToken,
  getUser,
  isAuthRequired,
  login as apiLogin,
  logout as apiLogout,
  onAuthChange,
  onAuthRequired,
  refreshUser,
  register as apiRegister,
  type AuthUser,
} from './auth'

export { AuthRequiredError }

interface AuthContextValue {
  user: AuthUser | null
  token: string | null
  loading: boolean
  /** 会话过期（401 静默登出）标记——Layout 据此显示重新登录横幅（M51） */
  authRequired: boolean
  dismissAuthRequired: () => void
  login: (email: string, password: string) => Promise<AuthUser>
  register: (input: { username: string; email: string; password: string }) => Promise<AuthUser>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getToken())
  const [user, setUser] = useState<AuthUser | null>(() => getUser())
  const [loading, setLoading] = useState<boolean>(() => Boolean(getToken()))
  const [authRequired, setAuthRequired] = useState<boolean>(() => isAuthRequired())

  useEffect(() => {
    const unsub = onAuthRequired(() => setAuthRequired(isAuthRequired()))
    return unsub
  }, [])

  useEffect(() => {
    const unsub = onAuthChange((t, u) => {
      setToken(t)
      setUser(u)
    })
    return unsub
  }, [])

  // Boot: refresh /me if a cached token exists.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      if (getToken() && !getUser()) {
        try {
          await refreshUser()
        } catch {
          /* already handled by refreshUser */
        }
      }
      if (!cancelled) setLoading(false)
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const u = await apiLogin(email, password)
    return u
  }, [])

  const register = useCallback(
    async (input: { username: string; email: string; password: string }) => {
      const u = await apiRegister(input)
      return u
    },
    [],
  )

  const logout = useCallback(() => {
    apiLogout()
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      loading,
      authRequired,
      dismissAuthRequired: () => clearAuthRequired(),
      login,
      register,
      logout,
    }),
    [user, token, loading, authRequired, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { token, loading } = useAuth()
  const location = useLocation()
  if (loading) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
        正在加载账号…
      </div>
    )
  }
  if (!token) {
    const redirect = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?redirect=${redirect}`} replace />
  }
  return <>{children}</>
}
