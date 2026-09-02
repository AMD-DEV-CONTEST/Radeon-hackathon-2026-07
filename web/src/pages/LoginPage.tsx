import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ErrorBanner } from '../components/feedback'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<Error | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const from = (location.state as { from?: { pathname: string } } | null)?.from
    ?.pathname

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(username, password)
      navigate(from && from !== '/login' ? from : '/', { replace: true })
    } catch (err) {
      setError(err as Error)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-card">
      <h1>登录</h1>
      <form onSubmit={handleSubmit}>
        <label htmlFor="username">用户名</label>
        <input
          id="username"
          value={username}
          autoComplete="username"
          onChange={(e) => setUsername(e.target.value)}
          required
        />
        <label htmlFor="password">密码</label>
        <input
          id="password"
          type="password"
          value={password}
          autoComplete="current-password"
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <div style={{ marginTop: 16 }}>
          <button type="submit" className="primary" disabled={submitting}>
            {submitting ? '正在登录…' : '登录'}
          </button>
        </div>
      </form>
      <ErrorBanner error={error} />
    </div>
  )
}
