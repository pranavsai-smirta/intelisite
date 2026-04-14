import { useState } from 'react'

function CollapsibleSection({ title, items, accentColor }) {
  const [open, setOpen] = useState(true)
  if (!items || items.length === 0) return null
  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-slate-50 hover:bg-slate-100 transition-colors"
      >
        <span className={`text-sm font-semibold ${accentColor}`}>{title}</span>
        <span className="text-slate-400 text-sm">{open ? '\u2303' : '\u2304'}</span>
      </button>
      {open && (
        <ul className="divide-y divide-slate-100">
          {items.map((item, i) => (
            <li key={i} className="px-4 py-3 text-sm text-slate-700 leading-relaxed">
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function InsightPanel({ insights }) {
  if (!insights) return null
  const { executive_summary, highlights, concerns, recommendations } = insights

  return (
    <div className="space-y-3">
      {executive_summary && (
        <div className="rounded-lg bg-slate-900 text-slate-100 px-5 py-4 text-sm leading-relaxed"
          style={{ boxShadow: '0 0 0 1px rgba(255,255,255,0.06), 0 4px 16px rgba(13,148,136,0.10)' }}
        >
          {executive_summary}
        </div>
      )}
      <CollapsibleSection title="Highlights" items={highlights} accentColor="text-teal-700" />
      <CollapsibleSection title="Concerns" items={concerns} accentColor="text-red-700" />
      <CollapsibleSection title="Recommendations" items={recommendations} accentColor="text-amber-700" />
    </div>
  )
}
