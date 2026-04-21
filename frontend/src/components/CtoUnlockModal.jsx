import { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'

export default function CtoUnlockModal({ onClose }) {
  const { elevateToCto } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!username.trim() || !password) {
      setError('Please enter both username and password.')
      return
    }
    setSubmitting(true)
    setError('')
    const ok = await elevateToCto(username.trim(), password)
    if (!ok) {
      setError('Incorrect CTO credentials.')
      setSubmitting(false)
      return
    }
    onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{
        background: 'rgba(2, 6, 23, 0.78)',
        backdropFilter: 'blur(6px)',
        WebkitBackdropFilter: 'blur(6px)',
        animation: 'aiViewFadeIn 0.2s ease-out',
      }}
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md bg-white p-8"
        style={{
          borderRadius: '11px',
          border: '1px solid rgba(254,99,37,0.2)',
          boxShadow: '0 24px 64px rgba(0,0,0,0.28), 0 0 0 1px rgba(254,99,37,0.06)',
        }}
        onClick={e => e.stopPropagation()}
      >
        <div className="flex flex-col items-center mb-6">
          <img
            src={`${import.meta.env.BASE_URL}smirta-logo.png`}
            alt="Smirta"
            style={{ height: 44, objectFit: 'contain', marginBottom: 12 }}
          />
          <div
            className="text-xs font-semibold uppercase tracking-widest mb-1"
            style={{ color: '#FE6325' }}
          >
            CTO Access
          </div>
          <h2 className="text-xl font-bold text-[#1A1A2E]">Unlock full dashboard</h2>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          <div className="mb-4">
            <label
              htmlFor="cto-username"
              className="block text-xs font-semibold uppercase tracking-wide text-[#64748B] mb-1.5"
            >
              Username
            </label>
            <input
              id="cto-username"
              type="text"
              value={username}
              onChange={e => { setUsername(e.target.value); if (error) setError('') }}
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
              htmlFor="cto-password"
              className="block text-xs font-semibold uppercase tracking-wide text-[#64748B] mb-1.5"
            >
              Password
            </label>
            <input
              id="cto-password"
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

          <div className="mt-5 flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-3 rounded-full font-semibold text-sm text-[#64748B] transition-colors"
              style={{ background: '#F5F0EB' }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="flex-1 py-3 rounded-full font-semibold text-sm text-white transition-all disabled:opacity-60"
              style={{
                background: '#FE6325',
                boxShadow: '0 4px 16px rgba(254,99,37,0.25)',
              }}
            >
              {submitting ? 'Unlocking\u2026' : 'Unlock'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
