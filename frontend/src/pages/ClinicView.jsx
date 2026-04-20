import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useClinicData } from '../hooks/useClinicData'
import { useAi } from '../contexts/AiContext'
import NavBar from '../components/NavBar'
import ScoreBadge from '../components/ScoreBadge'
import KpiCard from '../components/KpiCard'
import KpiTable from '../components/KpiTable'
import TrendChart from '../components/TrendChart'
import InsightPanel from '../components/InsightPanel'
import AiView from '../components/AiView'

export default function ClinicView() {
  const { clientCode } = useParams()
  const { data, loading, error } = useClinicData(clientCode)
  const [selectedMonth, setSelectedMonth] = useState(null)
  const { aiOpen } = useAi()

  if (loading) return (
    <div className="min-h-screen" style={{ background: '#F5F0EB' }}>
      <NavBar />
      <div className="flex items-center justify-center h-64 text-slate-400">Loading {clientCode}{'\u2026'}</div>
    </div>
  )

  if (error) return (
    <div className="min-h-screen" style={{ background: '#F5F0EB' }}>
      <NavBar />
      <div className="flex items-center justify-center h-64 text-red-500">
        No data found for {clientCode}. {error}
      </div>
    </div>
  )

  const { meta, months, chatbot_context } = data
  const availableMonths = meta.months_available ?? []
  const activeMonth = selectedMonth ?? availableMonths[availableMonths.length - 1]
  const monthData = months[activeMonth] ?? {}
  const { composite_score, ioptimize = [], iassign = [], benchmarks = {}, ai_insights } = monthData
  const historical = chatbot_context?.historical_kpis ?? []

  const companyAvg = benchmarks.company_avg ?? {}

  const compositeByMonth = {}
  availableMonths.forEach(m => {
    const s = months[m]?.composite_score
    if (s !== null && s !== undefined) compositeByMonth[m] = s
  })

  // L1: Filter out "Company Avg" row for correct location count
  const filteredLocations = ioptimize.filter(r => r.location !== 'Company Avg')

  if (aiOpen) {
    return (
      <div className="h-screen flex flex-col" style={{ background: '#F5F0EB' }}>
        <NavBar />
        <AiView
          chatbotContext={chatbot_context}
          currentMonthData={monthData}
          clinicName={clientCode}
          activeMonth={activeMonth}
        />
      </div>
    )
  }

  return (
    <div className="min-h-screen" style={{ background: '#F5F0EB' }}>

      {/* ── Background layers ── */}
      <div style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        backgroundImage: 'url(/dashboard-bg.png)',
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
      {/* Warm ambient glow below hero */}
      <div style={{
        position: 'fixed',
        top: '320px', left: '50%',
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
          padding: '20px 24px 40px',
          position: 'relative',
          overflow: 'hidden',
          boxShadow: '0 8px 40px rgba(254,99,37,0.10)',
        }}>
          {/* Orange glow — top-right */}
          <div style={{
            position: 'absolute', top: -150, right: '6%',
            width: 480, height: 480,
            background: 'radial-gradient(circle, rgba(254,99,37,0.22) 0%, transparent 62%)',
            pointerEvents: 'none',
          }} />
          {/* Orange glow — bottom-left */}
          <div style={{
            position: 'absolute', bottom: -70, left: '4%',
            width: 280, height: 280,
            background: 'radial-gradient(circle, rgba(254,99,37,0.09) 0%, transparent 65%)',
            pointerEvents: 'none',
          }} />
          {/* Decorative SVG — smaller network motif */}
          <svg
            viewBox="0 0 300 240"
            style={{ position: 'absolute', right: '2%', top: '5%', width: 240, height: 192, opacity: 0.13, pointerEvents: 'none' }}
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
          </svg>

          <div className="max-w-7xl mx-auto" style={{ position: 'relative', zIndex: 1 }}>
            <Link
              to="/"
              className="inline-flex items-center gap-1.5 text-sm transition-colors mb-2"
              style={{ color: '#94A3B8' }}
              onMouseEnter={e => (e.currentTarget.style.color = '#FE6325')}
              onMouseLeave={e => (e.currentTarget.style.color = '#94A3B8')}
            >
              {'\u2190'} Back to CTO Dashboard
            </Link>
            <div style={{ fontSize: '10px', fontWeight: 700, color: '#FE6325', textTransform: 'uppercase', letterSpacing: '0.14em', marginBottom: '6px' }}>
              Clinic Detail
            </div>
            <div className="flex items-start gap-5 flex-wrap">
              <div className="flex-1 min-w-0">
                <h1 style={{ fontSize: '26px', fontWeight: 800, color: '#1A1A2E', margin: '0 0 4px', letterSpacing: '-0.02em' }}>
                  {clientCode}
                </h1>
                <div style={{ fontSize: '13px', color: '#64748B' }}>
                  {filteredLocations.length} location{filteredLocations.length !== 1 ? 's' : ''} {'\u00b7'} Report period: {activeMonth}
                </div>
              </div>
              <ScoreBadge score={composite_score} size="lg" />
            </div>

            {/* Month selector */}
            {availableMonths.length > 1 && (
              <div className="mt-4 flex items-center gap-2 flex-wrap">
                <span className="text-xs text-slate-400 font-medium">Month:</span>
                {availableMonths.map(m => (
                  <button
                    key={m}
                    onClick={() => setSelectedMonth(m)}
                    className="text-xs px-3 py-1.5 rounded-lg transition-colors"
                    style={
                      m === activeMonth
                        ? { background: '#FE6325', color: 'white', boxShadow: '0 2px 8px rgba(254,99,37,0.25)' }
                        : { background: 'rgba(0,0,0,0.05)', color: '#64748B', border: '1px solid rgba(0,0,0,0.06)' }
                    }
                  >
                    {m}
                  </button>
                ))}
              </div>
            )}

            {/* KPI hero cards — L3 order, heroAccent for orange top bar */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
              <KpiCard
                label="Avg Delay"
                value={ioptimize[0]?.avg_delay_avg ?? null}
                unit="min"
                delta={ioptimize[0]?.mom_deltas?.avg_delay_mins ?? null}
                higherIsBetter={false}
                subtitle={`Global: ${companyAvg.avg_delay_avg ?? '\u2014'} min`}
                showTrendLink={true}
                heroAccent={true}
              />
              <KpiCard
                label="Chair Utilization"
                value={ioptimize[0]?.chair_utilization_avg ?? null}
                unit="%"
                delta={ioptimize[0]?.mom_deltas?.avg_chair_utilization ?? null}
                higherIsBetter={true}
                subtitle={`Global: ${companyAvg.chair_utilization_avg ?? '\u2014'}%`}
                showTrendLink={true}
                heroAccent={true}
              />
              <KpiCard
                label="Tx Past Close/Day"
                value={ioptimize[0]?.tx_past_close_avg ?? null}
                unit="/day"
                delta={ioptimize[0]?.mom_deltas?.avg_treatments_per_day ?? null}
                higherIsBetter={false}
                subtitle={`Global: ${companyAvg.tx_past_close_avg ?? '\u2014'}`}
                showTrendLink={true}
                heroAccent={true}
              />
              <KpiCard
                label="Patients per Nurse"
                value={iassign.filter(r => r.location !== 'Company Avg')[0]?.patients_per_nurse_avg ?? null}
                unit="/nurse"
                delta={iassign.filter(r => r.location !== 'Company Avg')[0]?.mom_deltas?.patients_per_nurse ?? null}
                higherIsBetter={false}
                subtitle={`Global: ${iassign.find(r => r.location === 'Company Avg')?.patients_per_nurse_avg ?? '\u2014'}`}
                showTrendLink={true}
                heroAccent={true}
              />
            </div>
          </div>

          {/* Hairline orange rule — hero bottom edge */}
          <div style={{
            position: 'absolute', bottom: 0, left: 0, right: 0, height: '1px',
            background: 'linear-gradient(90deg, transparent 0%, rgba(254,99,37,0.35) 50%, transparent 100%)',
          }} />
        </div>

        {/* Main content */}
        <div className="max-w-7xl mx-auto px-6 py-6 space-y-8">

          {/* AI Insights */}
          {ai_insights && (
            <section>
              <h2 className="text-base font-semibold text-[#1A1A2E] mb-3">AI Insights</h2>
              <InsightPanel insights={ai_insights} />
            </section>
          )}

          {/* KPI Tables */}
          <section>
            <h2 className="text-base font-semibold text-[#1A1A2E] mb-3">KPI Detail</h2>
            <KpiTable ioptimize={ioptimize} iassign={iassign} />
          </section>

          {/* Trend Charts — L7: id for scroll target */}
          <section id="trend-charts">
            <h2 className="text-base font-semibold text-[#1A1A2E] mb-4">6-Month Trends</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              <div className="bg-white p-4" style={{ borderRadius: '11px', boxShadow: '0 4px 20px rgba(0,0,0,0.06)' }}>
                <TrendChart historicalKpis={historical} compositeByMonth={compositeByMonth} kpiKey="scheduler_compliance_avg" />
              </div>
              <div className="bg-white p-4" style={{ borderRadius: '11px', boxShadow: '0 4px 20px rgba(0,0,0,0.06)' }}>
                <TrendChart historicalKpis={historical} compositeByMonth={compositeByMonth} kpiKey="avg_delay_avg" />
              </div>
              <div className="bg-white p-4" style={{ borderRadius: '11px', boxShadow: '0 4px 20px rgba(0,0,0,0.06)' }}>
                <TrendChart historicalKpis={historical} compositeByMonth={compositeByMonth} kpiKey="chair_utilization_avg" />
              </div>
              <div className="bg-white p-4" style={{ borderRadius: '11px', boxShadow: '0 4px 20px rgba(0,0,0,0.06)' }}>
                <TrendChart historicalKpis={historical} compositeByMonth={compositeByMonth} kpiKey="composite_score" />
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
