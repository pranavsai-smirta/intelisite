import { useState, useRef, useEffect, useMemo, useDeferredValue } from 'react'
import {
  BarChart, Bar,
  LineChart, Line,
  AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts'
import { useAi } from '../contexts/AiContext'
import { streamChat, buildSystemPrompt } from '../lib/anthropic'
import ApiKeyModal from './ApiKeyModal'
import { useRecentQuestions } from '../lib/useRecentQuestions'
import { copyAsEmail } from '../lib/shareAsEmail'

const PINNED_CHIPS = [
  'What is the single biggest thing to fix?',
  'Why is the infusion room overbooked on certain days?',
  'What improved the most this period?',
  'Summarize this period\'s performance into a shareable team report.',
]

// ---------------------------------------------------------------------------
// Content parser — splits AI response into text and chart segments
// Strips incomplete ```recharts blocks during streaming so raw JSON never flashes
// ---------------------------------------------------------------------------

function parseContent(content, isStreaming = false) {
  const text = isStreaming ? content.replace(/```recharts[\s\S]*$/, '') : content
  const segments = []
  const re = /```recharts\n?([\s\S]*?)```/g
  let last = 0, m

  while ((m = re.exec(text)) !== null) {
    const before = text.slice(last, m.index).trim()
    if (before) segments.push({ type: 'text', content: before })
    try {
      segments.push({ type: 'chart', spec: JSON.parse(m[1].trim()) })
    } catch {
      segments.push({ type: 'text', content: m[0] })
    }
    last = re.lastIndex
  }
  const tail = text.slice(last).trim()
  if (tail) segments.push({ type: 'text', content: tail })
  return segments
}

// ---------------------------------------------------------------------------
// Markdown renderer — bold, headers, bullets, numbered lists, tables, code blocks
// ---------------------------------------------------------------------------

function isTableRow(line)   { return /^\s*\|/.test(line) }
function isSeparator(line)  { return /^\s*\|[\s|:=-]+\|\s*$/.test(line) }

function parseTableLines(lines) {
  const parseRow = line =>
    line.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim())
  const [header, , ...dataLines] = lines
  return {
    headers: parseRow(header),
    rows: dataLines.filter(l => !isSeparator(l) && isTableRow(l)).map(parseRow),
  }
}

function TableBlock({ lines }) {
  const { headers, rows } = parseTableLines(lines)
  return (
    <div
      className="overflow-x-auto my-3 rounded-xl"
      style={{ border: '1px solid rgba(0,0,0,0.08)' }}
    >
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th
                key={i}
                className="px-3 py-2.5 text-left font-semibold uppercase tracking-wide whitespace-nowrap"
                style={{
                  color: '#FE6325',
                  background: 'rgba(254,99,37,0.08)',
                  borderBottom: '1px solid rgba(254,99,37,0.15)',
                }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr
              key={ri}
              className="transition-colors"
              style={{ background: ri % 2 === 1 ? 'rgba(0,0,0,0.015)' : 'transparent' }}
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(254,99,37,0.03)')}
              onMouseLeave={e => (e.currentTarget.style.background = ri % 2 === 1 ? 'rgba(0,0,0,0.015)' : 'transparent')}
            >
              {row.map((cell, ci) => (
                <td
                  key={ci}
                  className="px-3 py-2 text-[#1A1A2E]"
                  style={{ borderBottom: '1px solid rgba(0,0,0,0.04)' }}
                >
                  {renderInline(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function renderInline(text) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith('**') && p.endsWith('**')
      ? <strong key={i} className="font-semibold text-[#1A1A2E]">{p.slice(2, -2)}</strong>
      : p
  )
}

function renderMarkdown(text) {
  const lines = text.split('\n')
  const out = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Code block (non-recharts)
    if (line.startsWith('```')) {
      const codeLines = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i++])
      }
      out.push(
        <pre
          key={`code-${i}`}
          className="my-2 rounded-xl px-4 py-3 text-xs font-mono text-[#1A1A2E] overflow-x-auto"
          style={{ background: '#F1F5F9', border: '1px solid #E2E8F0' }}
        >
          {codeLines.join('\n')}
        </pre>
      )
      i++
      continue
    }

    // Markdown table
    if (isTableRow(line) && i + 1 < lines.length && isSeparator(lines[i + 1])) {
      const tableLines = []
      while (i < lines.length && (isTableRow(lines[i]) || isSeparator(lines[i]))) {
        tableLines.push(lines[i++])
      }
      if (tableLines.length >= 3) {
        out.push(<TableBlock key={`tbl-${i}`} lines={tableLines} />)
        continue
      }
    }

    // Headers
    if (line.startsWith('## ')) {
      out.push(
        <p key={i} className="text-xs font-semibold uppercase tracking-wider mt-4 mb-1.5" style={{ color: '#FE6325' }}>
          {line.slice(3)}
        </p>
      )
    } else if (line.startsWith('# ')) {
      out.push(
        <p key={i} className="text-sm font-bold text-[#1A1A2E] mt-3 mb-1">{line.slice(2)}</p>
      )
    // Bullet list
    } else if (/^[-*] /.test(line)) {
      out.push(
        <div key={i} className="flex gap-2 my-0.5 ml-1">
          <span className="flex-shrink-0 select-none" style={{ color: '#FE6325' }}>{'\u00b7'}</span>
          <span>{renderInline(line.slice(2))}</span>
        </div>
      )
    // Numbered list
    } else if (/^\d+\. /.test(line)) {
      const [num, ...rest] = line.split('. ')
      out.push(
        <div key={i} className="flex gap-2 my-0.5 ml-1">
          <span className="flex-shrink-0 w-4 text-right select-none" style={{ color: '#FE6325' }}>{num}.</span>
          <span>{renderInline(rest.join('. '))}</span>
        </div>
      )
    // Blank line
    } else if (line.trim() === '') {
      out.push(<div key={i} className="h-1.5" />)
    // Regular paragraph
    } else {
      out.push(<p key={i} className="my-0.5">{renderInline(line)}</p>)
    }
    i++
  }

  return out
}

// ---------------------------------------------------------------------------
// Custom chart tooltip
// ---------------------------------------------------------------------------

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div
      className="rounded-xl px-3 py-2.5 min-w-[120px]"
      style={{
        background: 'rgba(255,255,255,0.97)',
        border: '1px solid rgba(0,0,0,0.08)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.12)',
        backdropFilter: 'blur(12px)',
      }}
    >
      <p className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: '#FE6325' }}>{label}</p>
      {payload.map((entry, i) => (
        <div key={i} className="flex items-center gap-2 py-0.5">
          <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: entry.color }} />
          <span className="text-xs text-[#64748B] flex-1">{entry.name}</span>
          <span className="text-xs font-semibold text-[#1A1A2E] pl-2">{entry.value}</span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Chart block
// ---------------------------------------------------------------------------

const TICK = { fill: '#64748B', fontSize: 11 }
const GRID = '#E2E8F0'

function ChartBlock({ spec }) {
  const { type = 'BarChart', title, data, xAxisKey = 'name', series = [] } = spec
  if (!Array.isArray(data) || !data.length || !series.length) return null

  const isBar  = type === 'BarChart'
  const isArea = type === 'AreaChart'

  const sharedProps = {
    data,
    margin: { top: 6, right: 12, left: -18, bottom: 4 },
  }
  const axes = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={isBar ? false : true} />
      <XAxis dataKey={xAxisKey} tick={TICK} axisLine={false} tickLine={false} />
      <YAxis tick={TICK} axisLine={false} tickLine={false} width={40} />
      <Tooltip content={<ChartTooltip />} cursor={{ fill: 'rgba(254,99,37,0.04)' }} />
      {series.length > 1 && (
        <Legend
          iconType="circle"
          iconSize={7}
          wrapperStyle={{ fontSize: '11px', color: '#64748B', paddingTop: '10px' }}
        />
      )}
    </>
  )

  return (
    <div
      className="rounded-xl p-4 my-2"
      style={{ background: '#FFFFFF', border: '1px solid rgba(0,0,0,0.06)' }}
    >
      {title && (
        <p className="text-xs font-semibold text-[#64748B] uppercase tracking-wider mb-3">{title}</p>
      )}
      <ResponsiveContainer width="100%" height={224}>
        {isBar ? (
          <BarChart {...sharedProps}>
            {axes}
            {series.map(s => (
              <Bar key={s.dataKey} dataKey={s.dataKey} name={s.name} fill={s.color}
                radius={[4, 4, 0, 0]} maxBarSize={52} />
            ))}
          </BarChart>
        ) : isArea ? (
          <AreaChart {...sharedProps}>
            <defs>
              {series.map(s => (
                <linearGradient key={s.dataKey} id={`g-${s.dataKey}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={s.color} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={s.color} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            {axes}
            {series.map(s => (
              <Area key={s.dataKey} type="monotone" dataKey={s.dataKey} name={s.name}
                stroke={s.color} strokeWidth={2} fill={`url(#g-${s.dataKey})`} />
            ))}
          </AreaChart>
        ) : (
          /* LineChart */
          <LineChart {...sharedProps}>
            {axes}
            {series.map(s => (
              <Line key={s.dataKey} type="monotone" dataKey={s.dataKey} name={s.name}
                stroke={s.color} strokeWidth={2}
                dot={{ fill: s.color, r: 3, strokeWidth: 0 }}
                activeDot={{ r: 5, strokeWidth: 0 }} />
            ))}
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Typing indicator
// ---------------------------------------------------------------------------

function TypingIndicator() {
  return (
    <div className="flex justify-start mb-4">
      <div
        className="flex items-center gap-1.5 px-4 py-3 rounded-2xl rounded-tl-sm"
        style={{ background: '#FFFFFF', border: '1px solid rgba(0,0,0,0.06)' }}
      >
        {[0, 1, 2].map(i => (
          <span key={i} className="w-1.5 h-1.5 rounded-full animate-bounce"
            style={{ background: '#FE6325', animationDelay: `${i * 0.15}s` }} />
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Message — useDeferredValue defers heavy parsing so the UI stays responsive
// ---------------------------------------------------------------------------

function Message({ role, content, isStreaming, onCopyEmail }) {
  const [copied, setCopied] = useState(false)
  const isUser = role === 'user'

  // Defer expensive markdown/chart parsing — React can skip intermediate
  // renders during rapid streaming and jump to the latest value instead
  const deferred = useDeferredValue(content)
  const segments = useMemo(
    () => parseContent(deferred, isStreaming),
    [deferred, isStreaming]
  )

  if (isUser) {
    return (
      <div className="flex justify-end mb-5">
        <div
          className="max-w-[72%] text-sm leading-relaxed rounded-2xl rounded-tr-sm px-4 py-3 text-white"
          style={{ background: 'linear-gradient(135deg, #FE6325, #E85520)' }}
        >
          {content}
        </div>
      </div>
    )
  }

  const hasContent = !!content?.trim()

  async function handleCopy() {
    if (!onCopyEmail) return
    await onCopyEmail(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2500)
  }

  return (
    <div className="flex justify-start mb-5">
      <div className="flex flex-col gap-1" style={{ maxWidth: '90%', minWidth: '55%' }}>
        {segments.map((seg, i) =>
          seg.type === 'chart' ? (
            <ChartBlock key={i} spec={seg.spec} />
          ) : (
            <div
              key={i}
              className="text-sm leading-relaxed rounded-2xl rounded-tl-sm px-4 py-3 text-[#1A1A2E]"
              style={{ background: '#FFFFFF', border: '1px solid rgba(0,0,0,0.06)' }}
            >
              {renderMarkdown(seg.content)}
            </div>
          )
        )}
        {isStreaming && hasContent && (
          <div
            className="flex items-center gap-1.5 px-4 py-2.5 rounded-2xl rounded-tl-sm self-start"
            style={{ background: '#FFFFFF', border: '1px solid rgba(0,0,0,0.06)' }}
          >
            {[0, 1, 2].map(i => (
              <span key={i} className="w-1.5 h-1.5 rounded-full animate-bounce"
                style={{ background: '#FE6325', animationDelay: `${i * 0.15}s` }} />
            ))}
          </div>
        )}
        {hasContent && !isStreaming && (
          <div className="flex items-center gap-2 text-xs px-1 mt-0.5"
            style={{ color: 'rgba(100,116,139,0.6)' }}>
            <span>Clinic performance data</span>
            <span style={{ color: 'rgba(100,116,139,0.3)' }}>{'\u00b7'}</span>
            <span>Claude Sonnet</span>
            <span style={{ color: 'rgba(100,116,139,0.3)' }}>{'\u00b7'}</span>
            <span>Validate with clinical team</span>
            {onCopyEmail && (
              <>
                <span style={{ color: 'rgba(100,116,139,0.3)' }}>{'\u00b7'}</span>
                <button
                  onClick={handleCopy}
                  className="transition-colors hover:opacity-80"
                  style={{ color: copied ? '#22C55E' : 'rgba(100,116,139,0.7)' }}
                  title="Copy as email"
                >
                  {copied ? '\u2713 Copied' : '\u2709 Copy as Email'}
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// AiView
// ---------------------------------------------------------------------------

export default function AiView({ chatbotContext, currentMonthData, clinicName, activeMonth }) {
  const { closeAi } = useAi()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState(null)
  const [hasApiKey, setHasApiKey] = useState(() => {
    try {
      return !!localStorage.getItem('anthropic_api_key')
    } catch {
      return false
    }
  })
  const { recent: recentQuestions, logQuestion } = useRecentQuestions()

  // Scroll the overflow container directly — avoids scrollIntoView jank
  const scrollContainerRef = useRef(null)
  const inputRef = useRef(null)

  function autoScroll() {
    const el = scrollContainerRef.current
    if (!el) return
    // Only scroll if user is within 200px of the bottom (don't hijack manual scroll)
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 200) {
      el.scrollTop = el.scrollHeight
    }
  }

  // Scroll when a new message bubble appears (not on every content update)
  const msgCount = messages.length
  useEffect(() => { autoScroll() }, [msgCount])

  useEffect(() => { inputRef.current?.focus() }, [])

  async function handleSend(overrideText) {
    const text = (overrideText ?? input).trim()
    if (!text || streaming) return
    setInput('')
    setError(null)
    logQuestion(text)

    const userMsg = { role: 'user', content: text }
    const nextMessages = [...messages, userMsg]
    setMessages(nextMessages)
    setStreaming(true)

    const assistantIdx = nextMessages.length
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])

    // RAF-throttled accumulator — batches stream chunks to ~60fps
    // so React renders at most once per animation frame instead of
    // once per streamed byte/token
    let accumulated = ''
    let rafId = null

    function flushToState() {
      rafId = null
      const snapshot = accumulated
      setMessages(prev => {
        const updated = [...prev]
        updated[assistantIdx] = { role: 'assistant', content: snapshot }
        return updated
      })
      // Scroll after the DOM has painted the new content
      requestAnimationFrame(autoScroll)
    }

    try {
      const apiMessages = nextMessages.map(m => ({ role: m.role, content: m.content }))
      const systemPrompt = buildSystemPrompt(chatbotContext, currentMonthData)

      for await (const chunk of streamChat(apiMessages, systemPrompt)) {
        accumulated += chunk
        // Schedule a single flush for this animation frame; ignore further
        // chunks until the frame fires — they'll be included in `accumulated`
        if (rafId === null) {
          rafId = requestAnimationFrame(flushToState)
        }
      }

      // Cancel any pending RAF and do a final synchronous flush so the
      // completed message is committed exactly as received
      if (rafId !== null) {
        cancelAnimationFrame(rafId)
        rafId = null
      }
      if (!accumulated.trim()) {
        throw new Error('The server returned an empty response. Please try again.')
      }
      setMessages(prev => {
        const updated = [...prev]
        updated[assistantIdx] = { role: 'assistant', content: accumulated }
        return updated
      })
      requestAnimationFrame(autoScroll)

    } catch (err) {
      if (rafId !== null) cancelAnimationFrame(rafId)
      setError(err.message)
      setMessages(prev => prev.filter((_, i) => i !== assistantIdx))
    } finally {
      setStreaming(false)
    }
  }

  function handleChatKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  async function handleCopyEmail(content) {
    await copyAsEmail(content, clinicName, activeMonth)
  }

  const showTyping = streaming && messages.length > 0 && messages[messages.length - 1]?.content === ''
  const contextLabel = clinicName
    ? `${clinicName}${activeMonth ? ` \u00b7 ${activeMonth}` : ''}`
    : 'Network Overview'

  return (
    <>
      {!hasApiKey && <ApiKeyModal onSubmit={() => setHasApiKey(true)} />}
    <div className="flex-1 flex flex-col min-h-0" style={{ animation: 'aiViewFadeIn 0.2s ease-out' }}>

      {/* Hero header */}
      <div
        className="flex-shrink-0 bg-white px-6 py-4"
        style={{ boxShadow: '0 1px 3px rgba(0,0,0,0.05)', borderBottom: '1px solid rgba(0,0,0,0.06)' }}
      >
        <div className="max-w-7xl mx-auto">
          <button onClick={closeAi}
            className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-[#FE6325] transition-colors mb-2">
            {'\u2190'} Back
          </button>
          <div className="text-xs font-semibold uppercase tracking-widest mb-2" style={{ color: '#FE6325' }}>AI Intelligence</div>
          <h1 className="text-2xl font-bold text-[#1A1A2E] mb-1.5">What do you want to know?</h1>
          <p className="text-sm text-[#64748B]">{contextLabel}</p>
        </div>
      </div>

      {/* Messages — ref on the scrollable container, not a sentinel div */}
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto relative"
        style={{ background: '#F5F0EB' }}
      >
        {/* ai-hero ghost watermark behind messages */}
        <div
          style={{
            position: 'absolute',
            top: 0, left: 0, right: 0, bottom: 0,
            backgroundImage: `url(${import.meta.env.BASE_URL}ai-hero.png)`,
            backgroundPosition: 'center center',
            backgroundSize: 'contain',
            backgroundRepeat: 'no-repeat',
            opacity: 0.05,
            pointerEvents: 'none',
            zIndex: 0,
          }}
        />
        <div className="max-w-7xl mx-auto px-6 py-4" style={{ position: 'relative', zIndex: 1 }}>

          {messages.length === 0 && (
            <div className="text-center py-12">
              <img
                src={`${import.meta.env.BASE_URL}ai-hero.png`}
                alt=""
                style={{ maxWidth: 320, width: '100%', opacity: 0.6, margin: '0 auto 24px' }}
              />
              <div
                className="inline-flex w-12 h-12 rounded-full items-center justify-center mb-4"
                style={{ background: 'rgba(254,99,37,0.08)', border: '1px solid rgba(254,99,37,0.15)' }}
              >
                <span style={{ fontSize: '20px' }}>{'\u2726'}</span>
              </div>
              <p className="text-sm text-[#64748B]">Select a question below or type your own.</p>
            </div>
          )}

          {messages.map((m, i) => {
            if (m.role === 'assistant' && m.content === '' && streaming) return null
            return (
              <Message
                key={i}
                role={m.role}
                content={m.content}
                isStreaming={streaming && i === messages.length - 1 && m.role === 'assistant'}
                onCopyEmail={m.role === 'assistant' ? handleCopyEmail : undefined}
              />
            )
          })}

          {showTyping && <TypingIndicator />}
        </div>
      </div>

      {/* FAQ chips — 3 pinned + up to 3 from recent history; always visible */}
      {(
        <div className="flex-shrink-0" style={{ background: '#F5F0EB', borderTop: '1px solid rgba(0,0,0,0.05)' }}>
          <div className="max-w-7xl mx-auto px-6 py-3">
            <p className="text-xs text-[#64748B] font-medium uppercase tracking-wider mb-3">Suggested questions</p>
            <div className="flex flex-wrap gap-2">
              {PINNED_CHIPS.map(q => <FaqChip key={q} label={q} onClick={() => handleSend(q)} />)}
              {recentQuestions
                .filter(q => !PINNED_CHIPS.includes(q))
                .slice(0, 3)
                .map(q => (
                  <FaqChip
                    key={q}
                    label={q}
                    onClick={() => handleSend(q)}
                    isRecent
                  />
                ))}
            </div>
          </div>
        </div>
      )}

      {/* Input bar */}
      <div className="flex-shrink-0 px-6 py-4"
        style={{ background: '#FFFFFF', borderTop: '1px solid rgba(0,0,0,0.06)' }}>
        <div className="max-w-7xl mx-auto">
          <div className="flex gap-3 items-end">
            <textarea ref={inputRef} value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleChatKeyDown}
              rows={1} disabled={streaming}
              placeholder="Ask about performance data, trends, or benchmarks\u2026"
              className="flex-1 text-[#1A1A2E] text-sm rounded-xl px-4 py-3 resize-none outline-none transition-colors placeholder-[#94A3B8]"
              style={{ background: '#F5F0EB', border: '1px solid rgba(0,0,0,0.08)' }}
              onFocus={e => (e.currentTarget.style.border = '1px solid rgba(254,99,37,0.5)')}
              onBlur={e => (e.currentTarget.style.border = '1px solid rgba(0,0,0,0.08)')} />
            <button onClick={() => handleSend()} disabled={!input.trim() || streaming}
              className="text-sm px-5 py-3 rounded-xl font-medium transition-all flex-shrink-0"
              style={{
                background: !input.trim() || streaming ? 'rgba(0,0,0,0.04)' : '#FE6325',
                color: !input.trim() || streaming ? 'rgba(0,0,0,0.2)' : 'white',
              }}>
              {streaming ? '\u22ef' : '\u2191'}
            </button>
          </div>
          {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
        </div>
      </div>
    </div>
    </>
  )
}

function FaqChip({ label, onClick, isRecent }) {
  const [hovered, setHovered] = useState(false)
  return (
    <button onClick={onClick}
      onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
      className="text-xs rounded-full px-3 py-2 transition-all text-left"
      style={{
        background: hovered ? 'rgba(254,99,37,0.06)' : isRecent ? 'rgba(254,99,37,0.03)' : '#FFFFFF',
        border: hovered ? '1px solid rgba(254,99,37,0.25)' : isRecent ? '1px solid rgba(254,99,37,0.12)' : '1px solid rgba(0,0,0,0.08)',
        color: hovered ? '#FE6325' : '#64748B',
      }}>
      {isRecent && <span style={{ color: 'rgba(254,99,37,0.5)', marginRight: '4px' }}>↩</span>}
      {label}
    </button>
  )
}
