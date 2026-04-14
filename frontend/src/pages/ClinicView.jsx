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
    <div className="min-h-screen bg-slate-50">
      <NavBar />
      <div className="flex items-center justify-center h-64 text-slate-400">Loading {clientCode}{'\u2026'}</div>
    </div>
  )

  if (error) return (
    <div className="min-h-screen bg-slate-50">
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
  const onco = benchmarks.onco_benchmark ?? {}

  const compositeByMonth = {}
  availableMonths.forEach(m => {
    const s = months[m]?.composite_score
    if (s !== null && s !== undefined) compositeByMonth[m] = s
  })

  // AI view replaces all content below the NavBar
  if (aiOpen) {
    return (
      <div className="h-screen flex flex-col bg-slate-900">
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
    <div className="min-h-screen bg-slate-50">
      <NavBar />

      {/* Hero header */}
      <div className="bg-slate-900 px-6 py-8" style={{ boxShadow: '0 4px 24px rgba(13,148,136,0.1)' }}>
        <div className="max-w-7xl mx-auto">
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-teal-400 transition-colors mb-4"
          >
            {'\u2190'} Back to CTO Dashboard
          </Link>
          <div className="text-xs font-semibold text-teal-400 uppercase tracking-widest mb-1">Clinic Detail</div>
          <div className="flex items-start gap-5 flex-wrap">
            <div className="flex-1 min-w-0">
              <h1 className="text-2xl font-bold text-white mb-1">{clientCode}</h1>
              <div className="text-slate-400 text-sm">
                {ioptimize.length} location{ioptimize.length !== 1 ? 's' : ''} {'\u00b7'} Report period: {activeMonth}
              </div>
            </div>
            <ScoreBadge score={composite_score} size="lg" />
          </div>

          {/* Month selector */}
          {availableMonths.length > 1 && (
            <div className="mt-5 flex items-center gap-2 flex-wrap">
              <span className="text-xs text-slate-400 font-medium">Month:</span>
              {availableMonths.map(m => (
                <button
                  key={m}
                  onClick={() => setSelectedMonth(m)}
                  className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                    m === activeMonth
                      ? 'bg-teal-600 text-white border-teal-600'
                      : 'bg-slate-800 text-slate-300 border-slate-700 hover:border-teal-500'
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          )}

          {/* KPI hero cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6">
            <KpiCard
              label="Scheduler Compliance"
              value={ioptimize[0]?.scheduler_compliance_avg ?? null}
              unit="%"
              delta={ioptimize[0]?.mom_deltas?.scheduler_compliance ?? null}
              higherIsBetter={true}
              subtitle={`Company: ${companyAvg.scheduler_compliance_avg ?? '\u2014'}% \u00b7 Onco: ${onco.scheduler_compliance_avg ?? '\u2014'}%`}
            />
            <KpiCard
              label="Avg Delay"
              value={ioptimize[0]?.avg_delay_avg ?? null}
              unit="min"
              delta={ioptimize[0]?.mom_deltas?.avg_delay_mins ?? null}
              higherIsBetter={false}
              subtitle={`Company: ${companyAvg.avg_delay_avg ?? '\u2014'} min`}
            />
            <KpiCard
              label="Chair Utilization"
              value={ioptimize[0]?.chair_utilization_avg ?? null}
              unit="%"
              delta={ioptimize[0]?.mom_deltas?.avg_chair_utilization ?? null}
              higherIsBetter={true}
              subtitle={`Company: ${companyAvg.chair_utilization_avg ?? '\u2014'}%`}
            />
            <KpiCard
              label="Tx Past Close/Day"
              value={ioptimize[0]?.tx_past_close_avg ?? null}
              unit="/day"
              delta={ioptimize[0]?.mom_deltas?.avg_treatments_per_day ?? null}
              higherIsBetter={false}
              subtitle={`Company: ${companyAvg.tx_past_close_avg ?? '\u2014'}`}
            />
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="max-w-7xl mx-auto px-6 py-8 space-y-10">

        {/* AI Insights */}
        {ai_insights && (
          <section>
            <h2 className="text-base font-semibold text-slate-800 mb-3">AI Insights</h2>
            <InsightPanel insights={ai_insights} />
          </section>
        )}

        {/* KPI Tables */}
        <section>
          <h2 className="text-base font-semibold text-slate-800 mb-3">KPI Detail</h2>
          <KpiTable ioptimize={ioptimize} iassign={iassign} />
        </section>

        {/* Trend Charts */}
        <section>
          <h2 className="text-base font-semibold text-slate-800 mb-4">6-Month Trends</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <TrendChart historicalKpis={historical} compositeByMonth={compositeByMonth} kpiKey="scheduler_compliance_avg" />
            </div>
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <TrendChart historicalKpis={historical} compositeByMonth={compositeByMonth} kpiKey="avg_delay_avg" />
            </div>
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <TrendChart historicalKpis={historical} compositeByMonth={compositeByMonth} kpiKey="chair_utilization_avg" />
            </div>
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <TrendChart historicalKpis={historical} compositeByMonth={compositeByMonth} kpiKey="composite_score" />
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
