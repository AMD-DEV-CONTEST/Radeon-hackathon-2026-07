import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import toast from 'react-hot-toast'
import { BookOpen, Mail, Lock, Eye, EyeOff, LogIn } from 'lucide-react'

function getErrorMessage(err) {
  if (err?.response?.data?.error) return err.response.data.error
  if (err?.code === 'ERR_NETWORK' || err?.message?.includes('Network Error')) {
    return 'Unable to reach the backend API. Check VITE_API_URL and try again.'
  }
  return 'Login failed. Please try again.'
}

export default function Login() {
  const [form, setForm] = useState({ email: '', password: '' })
  const [showPwd, setShowPwd] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { login } = useAuth()
  const navigate = useNavigate()

  const updateField = (field, value) => {
    setForm(p => ({ ...p, [field]: value }))
    setError('')
  }

  const handle = async (e) => {
    e.preventDefault()
    setError('')

    const email = form.email.trim()
    const password = form.password

    if (!email) {
      setError('Email is required')
      return
    }
    if (!password) {
      setError('Password is required')
      return
    }

    setLoading(true)
    try {
      await login(email, password)
      toast.success('Welcome back!')
      navigate('/dashboard')
    } catch (err) {
      const message = getErrorMessage(err)
      setError(message)
      toast.error(message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-layout">
      <div className="auth-content">
        <div className="auth-card">
          <h1 className="auth-title">StudyTrack</h1>
          <p className="auth-tagline">AI-powered learning. Career-ready outcomes.</p>

          <div className="card" style={{ marginTop: '1.5rem' }}>
            <h2 style={{ fontSize: '1.25rem', marginBottom: '0.25rem' }}>Welcome Back</h2>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '1.25rem' }}>Sign in to continue your learning journey</p>

            {error && <div className="alert alert-error" style={{ marginBottom: '1rem' }}>{error}</div>}

            <form onSubmit={handle} className="auth-form">
              <div className="form-group">
                <label className="form-label">Email</label>
                <div className="input-wrapper">
                  <Mail size={16} className="input-icon" />
                  <input
                    type="email"
                    className="form-input"
                    placeholder="you@example.com"
                    value={form.email}
                    onChange={e => updateField('email', e.target.value)}
                    required
                    id="login-email"
                    autoComplete="email"
                  />
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">Password</label>
                <div className="input-wrapper">
                  <Lock size={16} className="input-icon" />
                  <input
                    type={showPwd ? 'text' : 'password'}
                    className="form-input"
                    placeholder="Enter your password"
                    value={form.password}
                    onChange={e => updateField('password', e.target.value)}
                    required
                    id="login-password"
                    autoComplete="current-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPwd(p => !p)}
                    className="pwd-toggle"
                  >
                    {showPwd ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <button type="submit" id="login-submit" className="btn btn-primary btn-lg" style={{ marginTop: '0.5rem' }} disabled={loading}>
                {loading ? <><span className="spinner" /> Signing in...</> : <><LogIn size={18} /> Sign In</>}
              </button>
            </form>

            <div className="divider" />
            <p style={{ textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
              Don't have an account?{' '}
              <Link to="/register" style={{ color: 'var(--primary)', textDecoration: 'none', fontWeight: 600 }}>
                Create one free
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}