import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from 'recharts'

const KPI_CONFIG = {
  scheduler_compliance_avg: { label: 'Scheduler Compliance', unit: '%', color: '#FE6325', higherIsBetter: true },
  avg_delay_avg:            { label: 'Avg Delay',             unit: 'min', color: '#DC2626', higherIsBetter: false },
  chair_utilization_avg:    { label: 'Chair Utilization',     unit: '%', color: '#6366F1', higherIsBetter: true },
  composite_score:          { label: 'Composite Score',       unit: '', color: '#FE6325', higherIsBetter: true },
}

function formatMonth(m) {
  if (!m) return ''
  const [year, mon] = m.split('-')
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  return `${months[parseInt(mon, 10) - 1]} ${year.slice(2)}`
}

export default function TrendChart({ historicalKpis, compositeByMonth, kpiKey = 'scheduler_compliance_avg' }) {
  const cfg = KPI_CONFIG[kpiKey] ?? { label: kpiKey, unit: '', color: '#FE6325', higherIsBetter: true }

  const monthMap = {}

  if (kpiKey === 'composite_score') {
    Object.entries(compositeByMonth ?? {}).forEach(([month, score]) => {
      monthMap[month] = { month, value: score }
    })
  } else {
    ;(historicalKpis ?? []).forEach(row => {
      const existing = monthMap[row.month]
      const v = row[kpiKey]
      if (v === null || v === undefined) return
      if (!existing) {
        monthMap[row.month] = { month: row.month, _sum: v, _count: 1 }
      } else {
        existing._sum += v
        existing._count += 1
      }
    })
    Object.values(monthMap).forEach(d => {
      d.value = d._count ? Math.round((d._sum / d._count) * 10) / 10 : null
    })
  }

  const data = Object.values(monthMap)
    .sort((a, b) => a.month.localeCompare(b.month))
    .map(d => ({ ...d, label: formatMonth(d.month) }))

  if (data.length === 0) return null

  return (
    <div>
      <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
        {cfg.label} Trend{cfg.unit ? ` (${cfg.unit})` : ''}
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <AreaChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id={`grad-${kpiKey}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={cfg.color} stopOpacity={0.2} />
              <stop offset="95%" stopColor={cfg.color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
          <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#64748B' }} />
          <YAxis tick={{ fontSize: 11, fill: '#64748B' }} />
          <Tooltip
            contentStyle={{ fontSize: 12, border: '1px solid #E2E8F0', borderRadius: 8 }}
            formatter={v => [`${v}${cfg.unit}`, cfg.label]}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={cfg.color}
            strokeWidth={2}
            fill={`url(#grad-${kpiKey})`}
            dot={{ r: 3, fill: cfg.color }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
