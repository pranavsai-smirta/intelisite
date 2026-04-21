import { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'

export default function LoginScreen() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!username.trim() || !password) {
      setError('Please enter your username and password.')
      return
    }
    setSubmitting(true)
    setError('')
    const ok = await login(username.trim(), password)
    if (!ok) {
      setError('Incorrect username or password.')
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{
        background: 'linear-gradient(135deg, #1A1A2E 0%, #2D1B0E 100%)',
      }}
    >
      <div
        className="w-full max-w-md bg-white p-8"
        style={{
          borderRadius: '11px',
          border: '1px solid rgba(254,99,37,0.2)',
          boxShadow: '0 24px 64px rgba(0,0,0,0.28), 0 0 0 1px rgba(254,99,37,0.06)',
          animation: 'aiViewFadeIn 0.25s ease-out',
        }}
      >
        {/* Logo + branding */}
        <div className="flex flex-col items-center mb-7">
          <img
            src={`${import.meta.env.BASE_URL}smirta-logo.png`}
            alt="Smirta"
            style={{ height: 52, objectFit: 'contain', marginBottom: 14 }}
          />
          <div
            className="text-xs font-semibold uppercase tracking-widest mb-1"
            style={{ color: '#FE6325' }}
          >
            Smirta iNtellisite
          </div>
          <h1 className="text-xl font-bold text-[#1A1A2E]">Sign in to continue</h1>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          <div className="mb-4">
            <label
              htmlFor="login-username"
              className="block text-xs font-semibold uppercase tracking-wide text-[#64748B] mb-1.5"
            >
              Username
            </label>
            <input
              id="login-username"
              type="text"
              value={username}
              onChange={e => { setUsername(e.target.value); if (error) setError('') }}
              placeholder="admin"
              autoFocus
              autoComplete="username"
              spellCheck={false}
              className="w-full px-4 py-3 rounded-lg text-[#1A1A2E] text-sm outline-none transition-colors"
              style={{
                background: '#F5F0EB',
                border: error ? '1px solid rgba(220,38,38,0.6)' : '1px solid rgba(0,0,0,0.08)',
              }}
            />
          </div>

          <div className="mb-2">
            <label
              htmlFor="login-password"
              className="block text-xs font-semibold uppercase tracking-wide text-[#64748B] mb-1.5"
            >
              Password
            </label>
            <input
              id="login-password"
              type="password"
              value={password}
              onChange={e => { setPassword(e.target.value); if (error) setError('') }}
              placeholder="••••••••"
              autoComplete="current-password"
              className="w-full px-4 py-3 rounded-lg text-[#1A1A2E] text-sm outline-none transition-colors"
              style={{
                background: '#F5F0EB',
                border: error ? '1px solid rgba(220,38,38,0.6)' : '1px solid rgba(0,0,0,0.08)',
              }}
            />
          </div>

          {error && (
            <p className="mt-2 text-xs text-red-400" role="alert">{error}</p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="mt-5 w-full py-3 rounded-full font-semibold text-sm text-white transition-all disabled:opacity-60"
            style={{
              background: '#FE6325',
              boxShadow: '0 4px 16px rgba(254,99,37,0.25)',
            }}
          >
            {submitting ? 'Signing in\u2026' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
