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
        className="w-full max-w-md rounded-2xl bg-slate-900 p-8"
        style={{
          border: '1px solid rgba(13,148,136,0.3)',
          boxShadow: '0 24px 64px rgba(0,0,0,0.6), 0 0 0 1px rgba(13,148,136,0.08)',
        }}
      >
        <div className="mb-6">
          <div className="text-xs font-semibold uppercase tracking-widest text-teal-400 mb-2">
            AI Intelligence
          </div>
          <h2 id="apikey-modal-title" className="text-xl font-bold text-white mb-2">
            Connect AI Analyst
          </h2>
          <p className="text-sm text-slate-400 leading-relaxed">
            Enter your Anthropic API key to enable the AI analyst. Your key is stored
            only in this browser&apos;s local storage and is sent directly to Anthropic —
            it never touches our servers.
          </p>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          <label
            htmlFor="apikey-input"
            className="block text-xs font-semibold uppercase tracking-wide text-slate-300 mb-2"
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
            className="w-full px-4 py-3 rounded-lg text-white text-sm font-mono outline-none transition-colors"
            style={{
              background: 'rgba(15, 23, 42, 0.9)',
              border: error
                ? '1px solid rgba(220, 38, 38, 0.6)'
                : '1px solid rgba(148, 163, 184, 0.2)',
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
            className="mt-5 w-full py-3 rounded-lg font-semibold text-sm text-white transition-all disabled:opacity-60"
            style={{
              background: 'linear-gradient(135deg, #0D9488 0%, #0F766E 100%)',
              boxShadow: '0 4px 16px rgba(13,148,136,0.25)',
            }}
          >
            {submitting ? 'Connecting…' : 'Connect AI Analyst'}
          </button>
        </form>

        <p className="mt-5 text-xs text-slate-500 text-center">
          Need a key?{' '}
          <a
            href="https://console.anthropic.com/settings/keys"
            target="_blank"
            rel="noopener noreferrer"
            className="text-teal-400 hover:text-teal-300 underline-offset-2 hover:underline"
          >
            console.anthropic.com
          </a>
        </p>
      </div>
    </div>
  )
}
