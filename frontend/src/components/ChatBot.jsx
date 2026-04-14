import { useState, useRef, useEffect } from 'react'
import { streamChat, buildSystemPrompt } from '../lib/anthropic'

const SUGGESTED_QUESTIONS = [
  'Analyze scheduler compliance',
  'Which location is underperforming?',
  'Summarize recent trends',
]

function TypingIndicator() {
  return (
    <div className="flex justify-start mb-3">
      <div
        className="flex items-center gap-1.5 px-4 py-3 rounded-2xl rounded-tl-sm"
        style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.08)' }}
      >
        {[0, 1, 2].map(i => (
          <span
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-bounce"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
    </div>
  )
}

function Message({ role, content }) {
  const isUser = role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      <div
        className={`max-w-[85%] text-sm leading-relaxed rounded-2xl px-4 py-2.5 ${
          isUser ? 'rounded-tr-sm text-white' : 'rounded-tl-sm text-slate-100'
        }`}
        style={
          isUser
            ? { background: 'linear-gradient(135deg, #0D9488, #0F766E)' }
            : { background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.08)' }
        }
      >
        {content}
      </div>
    </div>
  )
}

export default function ChatBot({ chatbotContext, currentMonthData }) {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState(null)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSend(overrideText) {
    const text = (overrideText ?? input).trim()
    if (!text || streaming) return
    setInput('')
    setError(null)

    const userMsg = { role: 'user', content: text }
    const nextMessages = [...messages, userMsg]
    setMessages(nextMessages)
    setStreaming(true)

    const assistantIdx = nextMessages.length
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])

    try {
      const systemPrompt = buildSystemPrompt(chatbotContext, currentMonthData)
      const apiMessages = nextMessages.map(m => ({ role: m.role, content: m.content }))
      let accumulated = ''
      for await (const chunk of streamChat(apiMessages, systemPrompt)) {
        accumulated += chunk
        setMessages(prev => {
          const updated = [...prev]
          updated[assistantIdx] = { role: 'assistant', content: accumulated }
          return updated
        })
      }
    } catch (err) {
      setError(err.message)
      setMessages(prev => {
        const updated = [...prev]
        updated[assistantIdx] = { role: 'assistant', content: '[Error: ' + err.message + ']' }
        return updated
      })
    } finally {
      setStreaming(false)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const showTyping = streaming && messages.length > 0 && messages[messages.length - 1]?.content === ''

  return (
    <>
      {/* Floating button */}
      <button
        onClick={() => setOpen(o => !o)}
        className="fixed bottom-6 right-6 w-14 h-14 rounded-full text-white flex items-center justify-center text-xl transition-all z-40"
        style={{
          background: 'linear-gradient(135deg, #0D9488, #0F766E)',
          boxShadow: open
            ? '0 0 0 3px rgba(13,148,136,0.4), 0 8px 24px rgba(0,0,0,0.4)'
            : '0 0 0 1px rgba(13,148,136,0.2), 0 4px 16px rgba(0,0,0,0.3)',
        }}
        aria-label="Open AI assistant"
      >
        {open ? '\u00d7' : '\u{1F4AC}'}
      </button>

      {/* Drawer */}
      {open && (
        <div
          className="fixed bottom-24 right-6 w-96 max-h-[70vh] flex flex-col rounded-2xl overflow-hidden z-40"
          style={{
            background: 'rgba(15, 23, 42, 0.85)',
            backdropFilter: 'blur(20px) saturate(180%)',
            WebkitBackdropFilter: 'blur(20px) saturate(180%)',
            border: '1px solid rgba(255,255,255,0.10)',
            boxShadow: '0 0 0 1px rgba(13,148,136,0.12), 0 8px 40px rgba(0,0,0,0.6)',
          }}
        >
          {/* Header */}
          <div
            className="px-4 py-3 flex items-center gap-2"
            style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}
          >
            <span
              className="w-2 h-2 rounded-full bg-teal-400 animate-pulse"
              style={{ boxShadow: '0 0 6px rgba(45,212,191,0.6)' }}
            />
            <span className="text-teal-400 text-sm font-semibold">OncoSmart AI</span>
            <span className="text-xs text-slate-500 ml-auto">Ask about clinic KPIs</span>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-3 min-h-0">
            {messages.length === 0 && (
              <div className="text-slate-500 text-xs text-center py-4">
                Ask me about scheduler compliance, delays, chair utilization, trends, or comparisons.
              </div>
            )}
            {messages.map((m, i) => {
              // Suppress empty assistant placeholder while streaming — TypingIndicator renders instead (see showTyping below)
              if (m.role === 'assistant' && m.content === '' && streaming) return null
              return <Message key={i} role={m.role} content={m.content} />
            })}
            {showTyping && <TypingIndicator />}
            <div ref={bottomRef} />
          </div>

          {/* FAQ pills -- only shown before first message */}
          {messages.length === 0 && (
            <div
              className="px-3 py-2 flex flex-wrap gap-2"
              style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}
            >
              {SUGGESTED_QUESTIONS.map(q => (
                <button
                  key={q}
                  onClick={() => handleSend(q)}
                  className="text-xs text-slate-300 rounded-full px-3 py-1.5 transition-colors"
                  style={{
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.10)',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.10)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.05)')}
                >
                  {q}
                </button>
              ))}
            </div>
          )}

          {/* Input */}
          <div
            className="px-3 py-3 flex gap-2"
            style={{ borderTop: '1px solid rgba(255,255,255,0.08)' }}
          >
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              placeholder={'Ask about this clinic\u2026'}
              className="flex-1 text-slate-100 text-sm rounded-xl px-3 py-2 resize-none outline-none placeholder-slate-500 transition-colors"
              style={{
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid rgba(255,255,255,0.10)',
              }}
              onFocus={e => (e.currentTarget.style.border = '1px solid rgba(13,148,136,0.5)')}
              onBlur={e => (e.currentTarget.style.border = '1px solid rgba(255,255,255,0.10)')}
            />
            <button
              onClick={() => handleSend()}
              disabled={!input.trim() || streaming}
              className="text-white text-sm px-4 rounded-xl font-medium transition-all"
              style={{
                background: !input.trim() || streaming
                  ? 'rgba(255,255,255,0.08)'
                  : 'linear-gradient(135deg, #0D9488, #0F766E)',
                color: !input.trim() || streaming ? 'rgba(255,255,255,0.3)' : 'white',
              }}
            >
              {streaming ? '\u22ef' : '\u2191'}
            </button>
          </div>
        </div>
      )}
    </>
  )
}
