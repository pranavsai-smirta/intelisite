import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useManifest } from '../hooks/useManifest'
import { useAi } from '../contexts/AiContext'
import NavBar from '../components/NavBar'
import ScoreBadge from '../components/ScoreBadge'
import AiView from '../components/AiView'

const TREND_ICON = { up: '\u2191', down: '\u2193', flat: '\u2192' }
const TREND_COLOR = { up: 'text-green-500', down: 'text-red-500', flat: 'text-slate-400' }

function scoreAccentColor(score) {
  if (score === null || score === undefined) return 'rgba(100,116,139,0.35)'
  if (score >= 75) return '#22C55E'
  if (score >= 60) return '#FE6325'
  return '#DC2626'
}

function ClinicCard({ client, onClick }) {
  const trend = client.mom_trend ?? 'flat'
  const accent = scoreAccentColor(client.composite_score)
  const score = client.composite_score ?? 0
  return (
    <button
      onClick={onClick}
      className="text-left bg-white p-5 w-full group"
      style={{
        borderRadius: '11px',
        boxShadow: '0 4px 20px rgba(0,0,0,0.06)',
        borderTop: `3px solid ${accent}`,
        transitionProperty: 'box-shadow, transform',
        transitionDuration: '200ms',
        transitionTimingFunction: 'ease',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.boxShadow = '0 16px 48px rgba(254,99,37,0.14), 0 4px 16px rgba(0,0,0,0.06)'
        e.currentTarget.style.transform = 'translateY(-3px)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.boxShadow = '0 4px 20px rgba(0,0,0,0.06)'
        e.currentTarget.style.transform = 'translateY(0)'
      }}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="font-bold text-[#1A1A2E] text-base group-hover:text-[#FE6325] transition-colors">
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
      {/* Score progress bar */}
      <div style={{ marginTop: '12px', height: '3px', borderRadius: '99px', background: 'rgba(0,0,0,0.07)', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${score}%`, background: accent, borderRadius: '99px' }} />
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
    <div className="min-h-screen" style={{ background: '#F5F0EB' }}>
      <NavBar />
      <div className="flex items-center justify-center h-64 text-slate-400">{'Loading\u2026'}</div>
    </div>
  )

  if (error) return (
    <div className="min-h-screen" style={{ background: '#F5F0EB' }}>
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

  if (aiOpen) {
    return (
      <div className="h-screen flex flex-col" style={{ background: '#F5F0EB' }}>
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

  const heroStats = [
    { label: 'Avg Composite Score', value: network_summary.avg_composite_score ?? '\u2014' },
    { label: 'Top Performer',       value: network_summary.top_performer ?? '\u2014' },
    { label: 'Most Improved',       value: network_summary.most_improved ?? '\u2014' },
    { label: 'Clinics Below 65',    value: belowThreshold },
  ]

  return (
    <div className="min-h-screen" style={{ background: '#F5F0EB' }}>

      {/* ── Background layers ── */}
      <div style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        backgroundImage: `url(${import.meta.env.BASE_URL}dashboard-bg.png)`,
        backgroundPosition: 'center center',
        backgroundSize: 'cover',
        opacity: 0.04,
        pointerEvents: 'none',
        zIndex: 0,
      }} />
      <div style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        backgroundImage: 'radial-gradient(circle, rgba(254,99,37,0.22) 1px, transparent 1px)',
        backgroundSize: '22px 22px',
        pointerEvents: 'none',
        zIndex: 0,
      }} />
      {/* Warm ambient glow below the hero, in card area */}
      <div style={{
        position: 'fixed',
        top: '260px', left: '50%',
        transform: 'translateX(-50%)',
        width: '140vw',
        height: '560px',
        background: 'radial-gradient(ellipse 60% 55% at 50% 0%, rgba(254,99,37,0.10) 0%, transparent 100%)',
        pointerEvents: 'none',
        zIndex: 0,
      }} />

      <div style={{ position: 'relative', zIndex: 1 }}>
        <NavBar />

        {/* ── HERO ── */}
        <div style={{
          background: 'linear-gradient(135deg, #FFFFFF 0%, #FFF7EF 52%, #FFFFFF 100%)',
          padding: '28px 24px 44px',
          position: 'relative',
          overflow: 'hidden',
          boxShadow: '0 8px 40px rgba(254,99,37,0.10)',
        }}>
          {/* Orange glow — top-right dominant */}
          <div style={{
            position: 'absolute', top: -180, right: '8%',
            width: 580, height: 580,
            background: 'radial-gradient(circle, rgba(254,99,37,0.26) 0%, transparent 62%)',
            pointerEvents: 'none',
          }} />
          {/* Orange glow — bottom-left accent */}
          <div style={{
            position: 'absolute', bottom: -90, left: '6%',
            width: 340, height: 340,
            background: 'radial-gradient(circle, rgba(254,99,37,0.10) 0%, transparent 65%)',
            pointerEvents: 'none',
          }} />
          {/* Decorative SVG — network hub-and-spoke */}
          <svg
            viewBox="0 0 300 240"
            style={{ position: 'absolute', right: '3%', top: '8%', width: 300, height: 240, opacity: 0.16, pointerEvents: 'none' }}
            aria-hidden="true"
          >
            <circle cx="150" cy="120" r="110" stroke="#FE6325" strokeWidth="0.7" fill="none" strokeDasharray="3 5" />
            <circle cx="150" cy="120" r="65"  stroke="#FE6325" strokeWidth="0.7" fill="none" strokeDasharray="2 4" />
            <circle cx="150" cy="120" r="7" fill="#FE6325" opacity="0.9" />
            <line x1="150" y1="120" x2="42"  y2="18"  stroke="#FE6325" strokeWidth="1" />
            <line x1="150" y1="120" x2="262" y2="28"  stroke="#FE6325" strokeWidth="1" />
            <line x1="150" y1="120" x2="287" y2="148" stroke="#FE6325" strokeWidth="1" />
            <line x1="150" y1="120" x2="208" y2="223" stroke="#FE6325" strokeWidth="1" />
            <line x1="150" y1="120" x2="58"  y2="218" stroke="#FE6325" strokeWidth="1" />
            <line x1="150" y1="120" x2="13"  y2="158" stroke="#FE6325" strokeWidth="1" />
            <circle cx="42"  cy="18"  r="4.5" fill="#FE6325" />
            <circle cx="262" cy="28"  r="4.5" fill="#FE6325" />
            <circle cx="287" cy="148" r="4.5" fill="#FE6325" />
            <circle cx="208" cy="223" r="4.5" fill="#FE6325" />
            <circle cx="58"  cy="218" r="4.5" fill="#FE6325" />
            <circle cx="13"  cy="158" r="4.5" fill="#FE6325" />
            <circle cx="150" cy="55"  r="2.5" fill="#FE6325" opacity="0.55" />
            <circle cx="214" cy="88"  r="2.5" fill="#FE6325" opacity="0.55" />
            <circle cx="208" cy="165" r="2.5" fill="#FE6325" opacity="0.55" />
            <circle cx="87"  cy="170" r="2.5" fill="#FE6325" opacity="0.55" />
            <circle cx="88"  cy="87"  r="2.5" fill="#FE6325" opacity="0.55" />
          </svg>

          <div className="max-w-7xl mx-auto" style={{ position: 'relative', zIndex: 1 }}>
            <div style={{ fontSize: '10px', fontWeight: 700, color: '#FE6325', textTransform: 'uppercase', letterSpacing: '0.14em', marginBottom: '6px' }}>
              OncoSmart Network
            </div>
            <h1 style={{ fontSize: '30px', fontWeight: 800, color: '#1A1A2E', margin: '0 0 4px', letterSpacing: '-0.02em', lineHeight: 1.1 }}>
              CTO Dashboard
            </h1>
            <div style={{ fontSize: '13px', color: '#64748B' }}>Report period: {latest_month}</div>

            {/* Hero KPI cards — orange top accent, larger value */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5">
              {heroStats.map(({ label, value }) => (
                <div key={label} style={{
                  background: '#FFFFFF',
                  borderRadius: '11px',
                  padding: '16px 20px',
                  boxShadow: '0 4px 20px rgba(0,0,0,0.06)',
                  borderTop: '2px solid #FE6325',
                }}>
                  <div style={{ fontSize: '10px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.09em', marginBottom: '8px' }}>
                    {label}
                  </div>
                  <div style={{ fontSize: '28px', fontWeight: 700, color: '#1A1A2E', lineHeight: 1.1 }}>
                    {value}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Hairline orange rule — hero bottom edge */}
          <div style={{
            position: 'absolute', bottom: 0, left: 0, right: 0, height: '1px',
            background: 'linear-gradient(90deg, transparent 0%, rgba(254,99,37,0.35) 50%, transparent 100%)',
          }} />
        </div>

        {/* Controls */}
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 font-medium">Sort:</span>
            <button
              onClick={() => setSortDir(d => d === 'desc' ? 'asc' : 'desc')}
              className="text-xs px-3 py-1.5 rounded-lg bg-white text-slate-700 transition-colors"
              style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.06)' }}
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
                className="text-xs px-3 py-1.5 rounded-lg transition-colors"
                style={
                  trendFilter === f
                    ? { background: '#FE6325', color: 'white', boxShadow: '0 2px 8px rgba(254,99,37,0.25)' }
                    : { background: 'white', color: '#475569', boxShadow: '0 2px 8px rgba(0,0,0,0.06)' }
                }
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
    </div>
  )
}
