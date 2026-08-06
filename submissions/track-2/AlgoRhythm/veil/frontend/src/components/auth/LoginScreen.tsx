import { useState, type FormEvent } from 'react'
import { motion } from 'framer-motion'
import { useApp } from '@/context/AppContext'
import { api } from '@/lib/api'
import type { Role } from '@/types'
import { cn } from '@/lib/utils'

const ROLES: { value: Role; label: string; description: string }[] = [
  { value: 'auditor',  label: 'Auditor',  description: 'Full findings, attack feed, and evidence' },
  { value: 'redactor', label: 'Redactor', description: 'Approve and apply redactions' },
  { value: 'viewer',   label: 'Viewer',   description: 'Read-only risk summary' },
]

export function LoginScreen() {
  const { login } = useApp()
  const [role, setRole] = useState<Role>('auditor')
  const [passphrase, setPassphrase] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!passphrase.trim()) { setError('Enter the passphrase printed in the server console.'); return }
    setLoading(true)
    setError('')
    try {
      const res = await api.login(role, passphrase)
      login(res.token, res.role, res.expires_at)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Authentication failed'
      setError(msg.includes('401') || msg.includes('Invalid')
        ? 'Invalid passphrase — check the server console output.'
        : 'Network error — is the VEIL server running?')
      setPassphrase('')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-white flex">
      {/* Left: information panel */}
      <div className="hidden lg:flex w-96 bg-gray-900 flex-col justify-between p-10 flex-shrink-0">
        <div>
          <span className="text-xl font-bold tracking-tight text-white">VEIL</span>
          <p className="mt-1 text-sm text-gray-400">Adversarial Privacy Audit System</p>
        </div>

        <div className="space-y-8">
          <FeatureRow
            label="Five adversarial personas"
            detail="Layout Forensicist · Data Broker · Insider · Journalist · Stylometrist"
          />
          <FeatureRow
            label="Local inference only"
            detail="All LLM inference runs on-device via vLLM on AMD Radeon GPU. Zero egress."
          />
          <FeatureRow
            label="Evidence-tiered findings"
            detail="Mechanical · Correlational · Stylistic — each tier carries its own evidence burden."
          />
          <FeatureRow
            label="Immutable audit chain"
            detail="HMAC-chained append-only log. Every session and every edit is recorded."
          />
        </div>

        <div>
          <p className="text-2xs text-gray-600 font-mono">
            v0.1.0 · Track 2 Submission
          </p>
        </div>
      </div>

      {/* Right: login form */}
      <div className="flex-1 flex items-center justify-center p-8">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25 }}
          className="w-full max-w-sm"
        >
          {/* Mobile brand */}
          <div className="lg:hidden mb-8">
            <span className="text-2xl font-bold tracking-tight text-gray-900">VEIL</span>
            <p className="text-sm text-gray-400 mt-1">Adversarial Privacy Audit System</p>
          </div>

          <form onSubmit={handleSubmit} noValidate>
            <h1 className="text-lg font-semibold text-gray-900 mb-6">Sign in</h1>

            {/* Role selection */}
            <fieldset className="mb-5">
              <legend className="text-xs font-medium text-gray-700 mb-2">Role</legend>
              <div className="space-y-2">
                {ROLES.map(r => (
                  <label
                    key={r.value}
                    className={cn(
                      'flex items-start gap-3 p-3 rounded-md border cursor-pointer transition-colors',
                      role === r.value
                        ? 'border-gray-900 bg-gray-50'
                        : 'border-gray-200 hover:border-gray-300',
                    )}
                  >
                    <input
                      type="radio"
                      name="role"
                      value={r.value}
                      checked={role === r.value}
                      onChange={() => setRole(r.value)}
                      className="mt-0.5 accent-gray-900"
                    />
                    <div>
                      <div className="text-sm font-medium text-gray-900">{r.label}</div>
                      <div className="text-xs text-gray-500">{r.description}</div>
                    </div>
                  </label>
                ))}
              </div>
            </fieldset>

            {/* Passphrase */}
            <div className="mb-5">
              <label htmlFor="passphrase" className="block text-xs font-medium text-gray-700 mb-1.5">
                Passphrase
              </label>
              <input
                id="passphrase"
                type="password"
                value={passphrase}
                onChange={e => setPassphrase(e.target.value)}
                placeholder="Printed in the server console at startup"
                autoComplete="current-password"
                className={cn(
                  'w-full px-3 py-2 text-sm border rounded-md font-mono',
                  'placeholder:text-gray-400 placeholder:font-sans',
                  'outline-none transition-colors',
                  error
                    ? 'border-red-300 focus:border-red-400 focus:ring-2 focus:ring-red-100'
                    : 'border-gray-300 focus:border-gray-500 focus:ring-2 focus:ring-gray-100',
                )}
              />
              {error && (
                <p className="mt-1.5 text-xs text-red-600">{error}</p>
              )}
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={loading}
              className={cn(
                'w-full py-2.5 px-4 rounded-md text-sm font-semibold transition-colors',
                'bg-gray-900 text-white hover:bg-gray-800',
                'disabled:opacity-50 disabled:cursor-not-allowed',
                'focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-gray-900',
              )}
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <Spinner /> Authenticating…
                </span>
              ) : 'Sign in'}
            </button>
          </form>

          <p className="mt-6 text-2xs text-gray-400 text-center">
            Sessions expire after 2 hours. Passphrase is unique per server restart.
          </p>
        </motion.div>
      </div>
    </div>
  )
}

function FeatureRow({ label, detail }: { label: string; detail: string }) {
  return (
    <div>
      <div className="text-sm font-medium text-white mb-0.5">{label}</div>
      <div className="text-xs text-gray-400 leading-relaxed">{detail}</div>
    </div>
  )
}

function Spinner() {
  return (
    <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}
