import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { ApiClient } from '../api/client'
import type { TokenResponse, UserProfile } from '../api/dto'

// SECURITY: the access token lives ONLY in localStorage (per-session, cleared
// on logout). It is never written to console/logs and never committed to Git.
const TOKEN_KEY = 'radeon_workbench_token'

export interface AuthContextValue {
  client: ApiClient
  user: UserProfile | null
  token: string | null
  isAuthenticated: boolean
  /** True while the persisted token is being validated on startup. */
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

function loadToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

function saveToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    /* storage unavailable — treat as unauthenticated */
  }
}

function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* ignore */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => loadToken())
  const [user, setUser] = useState<UserProfile | null>(null)
  const [loading, setLoading] = useState<boolean>(true)

  const client = useMemo(
    () => new ApiClient({ getToken: () => loadToken() }),
    [],
  )

  // Login state recovery: validate a persisted token on startup. If it is no
  // longer valid (e.g. expired -> 401), drop it and force a re-login.
  useEffect(() => {
    let active = true
    if (!loadToken()) {
      setLoading(false)
      return
    }
    client
      .getMe()
      .then((u) => {
        if (!active) return
        setUser(u)
        setToken(loadToken())
      })
      .catch(() => {
        if (!active) return
        clearToken()
        setToken(null)
        setUser(null)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [client])

  const login = async (username: string, password: string): Promise<void> => {
    const resp: TokenResponse = await client.login({ username, password })
    saveToken(resp.access_token)
    setToken(resp.access_token)
    setUser({
      user_id: resp.user_id,
      username: resp.username,
      display_name: resp.display_name,
      is_active: true,
      is_system_admin: resp.is_system_admin,
    })
  }

  const logout = (): void => {
    clearToken()
    setToken(null)
    setUser(null)
  }

  const value = useMemo<AuthContextValue>(
    () => ({
      client,
      user,
      token,
      isAuthenticated: user !== null,
      loading,
      login,
      logout,
    }),
    [client, user, token, loading],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return ctx
}
