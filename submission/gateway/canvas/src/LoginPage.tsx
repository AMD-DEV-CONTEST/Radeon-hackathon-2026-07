import { useState, useCallback } from 'react'

const STREAMING_BASE = import.meta.env.VITE_STREAMING_URL ?? 'http://111.228.42.18:8001'
const TOKEN_KEY = 'uas_token'

export function storeToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function loadToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

interface LoginPageProps {
  onLogin: (token: string) => void
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password) return
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch(`${STREAMING_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
      })
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({})) as Record<string, unknown>
        setError((body['detail'] as string) ?? `Login failed (${resp.status})`)
        return
      }
      const data = await resp.json() as Record<string, unknown>
      const token = data['token'] as string | undefined
      if (!token) { setError('No token in response'); return }
      storeToken(token)
      onLogin(token)
    } catch (err) {
      setError((err as Error).message ?? 'Network error')
    } finally {
      setLoading(false)
    }
  }, [username, password, onLogin])

  return (
    <div style={styles.backdrop}>
      <div style={styles.card}>
        <div style={styles.header}>
          <span style={styles.logo}>UAS Canvas</span>
          <span style={styles.tagline}>Multi-agent command cockpit</span>
        </div>

        <form onSubmit={handleSubmit} style={styles.form}>
          <label style={styles.label}>
            Username
            <input
              style={styles.input}
              type="text"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={e => setUsername(e.target.value)}
              disabled={loading}
              placeholder="admin"
            />
          </label>

          <label style={styles.label}>
            Password
            <input
              style={styles.input}
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              disabled={loading}
            />
          </label>

          {error && <div style={styles.errorBox}>{error}</div>}

          <button type="submit" style={loading ? styles.btnDisabled : styles.btn} disabled={loading}>
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <div style={styles.footer}>
          Gateway: {STREAMING_BASE.replace(/^https?:\/\//, '')}
        </div>
      </div>
    </div>
  )
}

const styles = {
  backdrop: {
    width: '100vw',
    height: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#f8fafc',
  } as React.CSSProperties,

  card: {
    width: 360,
    background: '#ffffff',
    border: '1px solid #e5e7eb',
    borderRadius: 10,
    padding: '32px 28px 24px',
    boxShadow: '0 2px 12px rgba(0,0,0,0.06)',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 20,
  } as React.CSSProperties,

  header: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 4,
  } as React.CSSProperties,

  logo: {
    fontSize: 20,
    fontWeight: 600,
    color: '#111827',
    letterSpacing: '-0.3px',
  } as React.CSSProperties,

  tagline: {
    fontSize: 12,
    color: '#6b7280',
  } as React.CSSProperties,

  form: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 14,
  } as React.CSSProperties,

  label: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 5,
    fontSize: 13,
    color: '#374151',
    fontWeight: 500,
  } as React.CSSProperties,

  input: {
    padding: '8px 10px',
    border: '1px solid #d1d5db',
    borderRadius: 6,
    fontSize: 14,
    color: '#111827',
    background: '#ffffff',
    outline: 'none',
  } as React.CSSProperties,

  errorBox: {
    padding: '8px 10px',
    background: '#fef2f2',
    border: '1px solid #fca5a5',
    borderRadius: 6,
    fontSize: 12,
    color: '#b91c1c',
  } as React.CSSProperties,

  btn: {
    padding: '9px 16px',
    background: '#111827',
    color: '#ffffff',
    border: 'none',
    borderRadius: 6,
    fontSize: 14,
    fontWeight: 500,
    cursor: 'pointer',
    marginTop: 4,
  } as React.CSSProperties,

  btnDisabled: {
    padding: '9px 16px',
    background: '#9ca3af',
    color: '#ffffff',
    border: 'none',
    borderRadius: 6,
    fontSize: 14,
    fontWeight: 500,
    cursor: 'not-allowed',
    marginTop: 4,
  } as React.CSSProperties,

  footer: {
    fontSize: 11,
    color: '#9ca3af',
    textAlign: 'center' as const,
    borderTop: '1px solid #f3f4f6',
    paddingTop: 12,
  } as React.CSSProperties,
}
