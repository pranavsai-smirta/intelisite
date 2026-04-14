export default function ScoreBadge({ score, size = 'md' }) {
  const color =
    score === null || score === undefined
      ? 'bg-slate-600 text-slate-300'
      : score >= 75
      ? 'bg-teal-500 text-white'
      : score >= 60
      ? 'bg-amber-500 text-white'
      : 'bg-red-600 text-white'

  const sizeClass = size === 'lg'
    ? 'text-4xl font-bold w-24 h-24 rounded-2xl'
    : size === 'sm'
    ? 'text-xs font-semibold w-10 h-10 rounded-lg'
    : 'text-lg font-bold w-14 h-14 rounded-xl'

  return (
    <div
      className={`${color} ${sizeClass} flex items-center justify-center shadow-sm`}
      title="Composite Score (0\u2013100)"
    >
      {score !== null && score !== undefined ? Math.round(score) : '\u2014'}
    </div>
  )
}
