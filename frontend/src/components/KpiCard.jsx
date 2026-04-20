export default function KpiCard({ label, value, unit, delta, higherIsBetter, subtitle, showTrendLink, heroAccent }) {
  const hasDelta = delta !== null && delta !== undefined
  const deltaPositive = hasDelta && delta > 0
  const deltaGood = higherIsBetter === null
    ? null
    : higherIsBetter ? deltaPositive : !deltaPositive

  const deltaColor = deltaGood === null
    ? 'text-slate-400'
    : deltaGood
    ? 'text-green-500'
    : 'text-red-400'

  const deltaArrow = hasDelta
    ? deltaPositive
      ? '\u2191'
      : '\u2193'
    : null

  return (
    <div
      className="relative overflow-hidden p-5 flex flex-col gap-2"
      style={{
        background: '#FFFFFF',
        borderRadius: '11px',
        boxShadow: '0 4px 20px rgba(0,0,0,0.06)',
        ...(heroAccent && { borderTop: '2px solid #FE6325' }),
      }}
    >
      <div className="text-xs font-semibold text-[#64748B] uppercase tracking-wider">{label}</div>
      <div className="flex items-end gap-2">
        <span className="text-3xl font-bold text-[#1A1A2E]">
          {value !== null && value !== undefined ? value : '\u2014'}
        </span>
        {unit && <span className="text-[#64748B] text-sm mb-1">{unit}</span>}
      </div>
      {hasDelta && (
        <div className={`text-sm font-medium ${deltaColor} flex items-center gap-1`}>
          <span>{deltaArrow}</span>
          <span>{Math.abs(delta).toFixed(1)} MoM</span>
        </div>
      )}
      {subtitle && <div className="text-xs text-[#94A3B8] mt-1">{subtitle}</div>}
      {showTrendLink && (
        <button
          onClick={() => document.getElementById('trend-charts')?.scrollIntoView({ behavior: 'smooth' })}
          className="text-xs mt-1 text-left transition-colors"
          style={{ color: '#FE6325' }}
        >
          View Trend {'\u2197'}
        </button>
      )}
    </div>
  )
}
