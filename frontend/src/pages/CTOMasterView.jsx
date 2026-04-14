import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useManifest } from '../hooks/useManifest'
import { useAi } from '../contexts/AiContext'
import NavBar from '../components/NavBar'
import ScoreBadge from '../components/ScoreBadge'
import KpiCard from '../components/KpiCard'
import AiView from '../components/AiView'

const TREND_ICON = { up: '\u2191', down: '\u2193', flat: '\u2192' }
const TREND_COLOR = { up: 'text-teal-600', down: 'text-red-500', flat: 'text-slate-400' }

function ClinicCard({ client, onClick }) {
  const trend = client.mom_trend ?? 'flat'
  return (
    <button
      onClick={onClick}
      className="text-left rounded-2xl border border-slate-200 bg-white p-5 hover:border-teal-400 hover:shadow-md transition-all group"
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="font-bold text-slate-900 text-base group-hover:text-teal-700 transition-colors">
            {client.display_name}
          </div>
          <div className="text-xs text-slate-400 mt-0.5">
            {client.location_count} location{client.location_count !== 1 ? 's' : ''} {'\u00b7'} {client.latest_month}
          </div>
        </div>
        <ScoreBadge score={client.composite_score} size="sm" />
      </div>
      <div className={`text-sm font-medium flex items-center gap-1 ${TREND_COLOR[trend]}`}>
        <span>{TREND_ICON[trend]}</span>
        <span className="capitalize">{trend === 'flat' ? 'Stable' : trend === 'up' ? 'Improving' : 'Declining'} MoM</span>
      </div>
    </button>
  )
}

export default function CTOMasterView() {
  const { data: manifest, loading, error } = useManifest()
  const navigate = useNavigate()
  const [sortDir, setSortDir] = useState('desc')
  const [trendFilter, setTrendFilter] = useState('all')
  const { aiOpen } = useAi()

  if (loading) return (
    <div className="min-h-screen bg-slate-50">
      <NavBar />
      <div className="flex items-center justify-center h-64 text-slate-400">{'Loading\u2026'}</div>
    </div>
  )

  if (error) return (
    <div className="min-h-screen bg-slate-50">
      <NavBar />
      <div className="flex items-center justify-center h-64 text-red-500">Failed to load: {error}</div>
    </div>
  )

  const { clients = [], network_summary = {}, latest_month } = manifest

  const improving = clients.filter(c => c.mom_trend === 'up').length
  const belowThreshold = clients.filter(c => c.composite_score !== null && c.composite_score < 65).length

  let filtered = trendFilter === 'all' ? clients : clients.filter(c => c.mom_trend === trendFilter)
  filtered = [...filtered].sort((a, b) => {
    const sa = a.composite_score ?? 0
    const sb = b.composite_score ?? 0
    return sortDir === 'desc' ? sb - sa : sa - sb
  })

  // Build a network-level chatbot context from manifest data so AI has meaningful data
  const networkChatbotContext = {
    kpi_definitions: {
      composite_score: {
        label: 'Composite Score',
        explanation: 'Weighted aggregate performance score (0-100) combining Scheduler Compliance, Avg Delay, Chair Utilization, and Tx Past Close metrics.',
      },
    },
    data_notes: [
      `Network of ${clients.length} clinics. Report period: ${latest_month}.`,
      `Network average composite score: ${network_summary.avg_composite_score ?? '\u2014'}.`,
      `Top performer: ${network_summary.top_performer ?? '\u2014'}.`,
      `Most improved: ${network_summary.most_improved ?? '\u2014'}.`,
      `${belowThreshold} clinic${belowThreshold !== 1 ? 's' : ''} below the 65-point threshold.`,
      `${improving} clinic${improving !== 1 ? 's' : ''} improving month-over-month.`,
    ].join(' '),
    historical_kpis: [],
  }

  const networkMonthData = {
    ioptimize: [...clients]
      .sort((a, b) => (b.composite_score ?? 0) - (a.composite_score ?? 0))
      .map(c => ({
        location: c.display_name,
        composite_score: c.composite_score,
        scheduler_compliance_avg: null,
        avg_delay_avg: null,
        chair_utilization_avg: null,
      })),
  }

  // AI view replaces all content below the NavBar
  if (aiOpen) {
    return (
      <div className="h-screen flex flex-col bg-slate-900">
        <NavBar />
        <AiView
          chatbotContext={networkChatbotContext}
          currentMonthData={networkMonthData}
          clinicName={null}
          activeMonth={latest_month}
        />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <NavBar />

      {/* Hero header */}
      <div className="bg-slate-900 px-6 py-8" style={{ boxShadow: '0 4px 24px rgba(13,148,136,0.1)' }}>
        <div className="max-w-7xl mx-auto">
          <div className="text-xs font-semibold text-teal-400 uppercase tracking-widest mb-1">OncoSmart Network</div>
          <h1 className="text-2xl font-bold text-white mb-1">CTO Dashboard</h1>
          <div className="text-slate-400 text-sm">Report period: {latest_month}</div>

          {/* Network summary cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6">
            <KpiCard label="Avg Composite Score" value={network_summary.avg_composite_score} unit="" higherIsBetter={true} />
            <KpiCard label="Top Performer" value={network_summary.top_performer} unit="" higherIsBetter={null} />
            <KpiCard label="Most Improved" value={network_summary.most_improved ?? '\u2014'} unit="" higherIsBetter={null} />
            <KpiCard label="Clinics Below 65" value={belowThreshold} unit="" higherIsBetter={false} />
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 font-medium">Sort:</span>
          <button
            onClick={() => setSortDir(d => d === 'desc' ? 'asc' : 'desc')}
            className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-slate-700 hover:border-teal-400 transition-colors"
          >
            Score {sortDir === 'desc' ? '\u2193' : '\u2191'}
          </button>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 font-medium">Filter:</span>
          {['all','up','down'].map(f => (
            <button
              key={f}
              onClick={() => setTrendFilter(f)}
              className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                trendFilter === f
                  ? 'bg-teal-600 text-white border-teal-600'
                  : 'bg-white text-slate-700 border-slate-200 hover:border-teal-400'
              }`}
            >
              {f === 'all' ? 'All' : f === 'up' ? '\u2191 Improving' : '\u2193 Declining'}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-slate-400">{filtered.length} clinics</span>
      </div>

      {/* Clinic grid */}
      <div className="max-w-7xl mx-auto px-6 pb-12">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filtered.map(client => (
            <ClinicCard
              key={client.code}
              client={client}
              onClick={() => navigate(`/clinic/${client.code}`)}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
