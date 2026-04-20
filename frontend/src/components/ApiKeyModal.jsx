import { useState } from 'react'

export default function ApiKeyModal({ onSubmit }) {
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  function handleSubmit(e) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed) {
      setError('Please enter your Anthropic API key.')
      return
    }
    if (!trimmed.startsWith('sk-ant-')) {
      setError('That does not look like an Anthropic key — it should start with "sk-ant-".')
      return
    }
    setSubmitting(true)
    try {
      localStorage.setItem('anthropic_api_key', trimmed)
    } catch {
      setSubmitting(false)
      setError('Your browser blocked localStorage. Disable private mode and try again.')
      return
    }
    onSubmit()
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
      aria-labelledby="apikey-modal-title"
    >
      <div
        className="w-full max-w-md bg-white p-8"
        style={{
          borderRadius: '11px',
          border: '1px solid rgba(254,99,37,0.2)',
          boxShadow: '0 24px 64px rgba(0,0,0,0.18), 0 0 0 1px rgba(254,99,37,0.06)',
        }}
      >
        <div className="mb-6">
          <div className="text-xs font-semibold uppercase tracking-widest mb-2" style={{ color: '#FE6325' }}>
            AI Intelligence
          </div>
          <h2 id="apikey-modal-title" className="text-xl font-bold text-[#1A1A2E] mb-2">
            Connect AI Analyst
          </h2>
          <p className="text-sm text-[#64748B] leading-relaxed">
            Enter your Anthropic API key to enable the AI analyst. Your key is stored
            only in this browser&apos;s local storage and is sent directly to Anthropic —
            it never touches our servers.
          </p>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          <label
            htmlFor="apikey-input"
            className="block text-xs font-semibold uppercase tracking-wide text-[#64748B] mb-2"
          >
            Anthropic API Key
          </label>
          <input
            id="apikey-input"
            type="password"
            value={value}
            onChange={e => {
              setValue(e.target.value)
              if (error) setError('')
            }}
            placeholder="sk-ant-..."
            autoFocus
            autoComplete="off"
            spellCheck={false}
            className="w-full px-4 py-3 rounded-lg text-[#1A1A2E] text-sm font-mono outline-none transition-colors"
            style={{
              background: '#F5F0EB',
              border: error
                ? '1px solid rgba(220, 38, 38, 0.6)'
                : '1px solid rgba(0,0,0,0.08)',
            }}
          />

          {error && (
            <p className="mt-2 text-xs text-red-400" role="alert">
              {error}
            </p>
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
            {submitting ? 'Connecting\u2026' : 'Connect AI Analyst'}
          </button>
        </form>

        <p className="mt-5 text-xs text-slate-500 text-center">
          Need a key?{' '}
          <a
            href="https://console.anthropic.com/settings/keys"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:underline underline-offset-2"
            style={{ color: '#FE6325' }}
          >
            console.anthropic.com
          </a>
        </p>
      </div>
    </div>
  )
}
