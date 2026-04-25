import { useState } from 'react'

const ORANGE = '#FE6325'

// Split a prose string into up to 3 meaningful sentences for bullet display
function proseToBullets(text, max = 3) {
  if (!text) return []
  // Split on sentence boundaries, filter blanks, cap at max
  return text
    .split(/(?<=[.!?])\s+/)
    .map(s => s.trim())
    .filter(Boolean)
    .slice(0, max)
}

function BulletList({ items }) {
  return (
    <ul className="space-y-2.5">
      {items.map((item, i) => (
        <li key={i} className="flex gap-3 items-start">
          <span
            className="flex-shrink-0 mt-1.5 w-1.5 h-1.5 rounded-full"
            style={{ background: ORANGE }}
          />
          <span className="text-base text-[#1A1A2E] leading-relaxed">{item}</span>
        </li>
      ))}
    </ul>
  )
}

function CollapsibleSection({ title, items, accentColor, icon }) {
  const [open, setOpen] = useState(false)
  if (!items || items.length === 0) return null

  // If only 1 item, split the prose into up to 3 sentences for richer bullets
  const bullets = items.length === 1
    ? proseToBullets(items[0], 3)
    : items.slice(0, 3)

  return (
    <div
      className="overflow-hidden transition-all"
      style={{
        borderRadius: '11px',
        border: open ? '1px solid rgba(254,99,37,0.18)' : '1px solid rgba(0,0,0,0.07)',
        background: '#FFFFFF',
        boxShadow: open ? '0 4px 24px rgba(254,99,37,0.08)' : '0 2px 10px rgba(0,0,0,0.04)',
      }}
    >
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-3.5 transition-colors"
        style={{ background: open ? 'rgba(254,99,37,0.04)' : '#FAFAF8' }}
        onMouseEnter={e => (e.currentTarget.style.background = 'rgba(254,99,37,0.06)')}
        onMouseLeave={e => (e.currentTarget.style.background = open ? 'rgba(254,99,37,0.04)' : '#FAFAF8')}
      >
        <div className="flex items-center gap-2.5">
          <span className="text-base">{icon}</span>
          <span className={`text-lg font-semibold tracking-wide ${accentColor}`}>{title}</span>
          <span
            className="text-xs font-medium px-1.5 py-0.5 rounded-full"
            style={{ background: 'rgba(254,99,37,0.1)', color: ORANGE }}
          >
            {bullets.length}
          </span>
        </div>
        <span
          className="text-xs font-medium transition-transform duration-200"
          style={{
            color: ORANGE,
            display: 'inline-block',
            transform: open ? 'rotate(180deg)' : 'rotate(0deg)',
          }}
        >
          ▾
        </span>
      </button>

      {open && (
        <div className="px-5 pb-4 pt-3 border-t" style={{ borderColor: 'rgba(254,99,37,0.1)' }}>
          <BulletList items={bullets} />
        </div>
      )}
    </div>
  )
}

export default function InsightPanel({ insights }) {
  if (!insights) return null
  const { executive_summary, highlights, concerns, recommendations } = insights
  const summaryBullets = proseToBullets(executive_summary, 3)

  return (
    <div className="space-y-3">
      {/* Executive Summary — always visible, 3 bullets */}
      {summaryBullets.length > 0 && (
        <div
          className="rounded-xl bg-white px-5 py-4"
          style={{
            borderLeft: `3px solid ${ORANGE}`,
            boxShadow: '0 4px 20px rgba(0,0,0,0.06)',
            border: '1px solid rgba(0,0,0,0.07)',
            borderLeftColor: ORANGE,
            borderLeftWidth: '3px',
          }}
        >
          <p
            className="text-base font-semibold uppercase tracking-widest mb-3"
            style={{ color: ORANGE }}
          >
            Executive Summary
          </p>
          <BulletList items={summaryBullets} />
        </div>
      )}

      {/* Collapsible sections — closed by default */}
      <CollapsibleSection
        title="Highlights"
        items={highlights}
        accentColor="text-emerald-700"
        icon="✦"
      />
      <CollapsibleSection
        title="Concerns"
        items={concerns}
        accentColor="text-red-600"
        icon="!"
      />
      <CollapsibleSection
        title="Recommendations"
        items={recommendations}
        accentColor="text-amber-700"
        icon="→"
      />
    </div>
  )
}
