export default function KpiCard({ label, value, unit, delta, higherIsBetter, subtitle }) {
  const hasDelta = delta !== null && delta !== undefined
  const deltaPositive = hasDelta && delta > 0
  const deltaGood = higherIsBetter === null
    ? null
    : higherIsBetter ? deltaPositive : !deltaPositive

  const deltaColor = deltaGood === null
    ? 'text-slate-400'
    : deltaGood
    ? 'text-teal-400'
    : 'text-red-400'

  const deltaArrow = hasDelta
    ? deltaPositive
      ? '\u2191'
      : '\u2193'
    : null

  return (
    <div
      className="relative rounded-2xl overflow-hidden p-5 flex flex-col gap-2"
      style={{
        background: '#0F172A',
        boxShadow: '0 0 0 1px rgba(255,255,255,0.06), 0 4px 24px rgba(13,148,136,0.12)',
      }}
    >
      <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{label}</div>
      <div className="flex items-end gap-2">
        <span className="text-3xl font-bold text-white">
          {value !== null && value !== undefined ? value : '\u2014'}
        </span>
        {unit && <span className="text-slate-400 text-sm mb-1">{unit}</span>}
      </div>
      {hasDelta && (
        <div className={`text-sm font-medium ${deltaColor} flex items-center gap-1`}>
          <span>{deltaArrow}</span>
          <span>{Math.abs(delta).toFixed(1)} MoM</span>
        </div>
      )}
      {subtitle && <div className="text-xs text-slate-500 mt-1">{subtitle}</div>}
    </div>
  )
}
