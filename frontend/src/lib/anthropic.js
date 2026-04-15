const API_URL = 'https://api.anthropic.com/v1/messages'
const MODEL = 'claude-sonnet-4-6'

export function buildSystemPrompt(chatbotContext, currentMonthData) {
  const { kpi_definitions = {}, data_notes = '', historical_kpis = [] } = chatbotContext ?? {}

  const kpiText = Object.entries(kpi_definitions)
    .map(([k, v]) => {
      const dir = v.higher_is_better === true ? 'higher is better'
        : v.higher_is_better === false ? 'lower is better'
        : 'context-dependent'
      return `- ${v.label} (${k}): ${v.explanation} [${dir}]`
    })
    .join('\n')

  const historyText = historical_kpis
    .map(r =>
      `${r.month} | ${r.location} | SC: ${r.scheduler_compliance_avg ?? '\u2014'}% | Delay: ${r.avg_delay_avg ?? '\u2014'} min | CU: ${r.chair_utilization_avg ?? '\u2014'}% | TxClose: ${r.tx_past_close_avg ?? '\u2014'}/day`
    )
    .join('\n')

  const companyAvg = currentMonthData?.benchmarks?.company_avg ?? {}
  const onco = currentMonthData?.benchmarks?.onco_benchmark ?? {}
  const benchmarkText = [
    `  Company Average (this client\u2019s own clinic mean):`,
    `    SC=${companyAvg.scheduler_compliance_avg ?? '\u2014'}% | Delay=${companyAvg.avg_delay_avg ?? '\u2014'} min | CU=${companyAvg.chair_utilization_avg ?? '\u2014'}% | TxClose=${companyAvg.tx_past_close_avg ?? '\u2014'}/day`,
    `  Onco Benchmark (network-wide oncology standard):`,
    `    SC=${onco.scheduler_compliance_avg ?? '\u2014'}% | Delay=${onco.avg_delay_avg ?? '\u2014'} min | CU=${onco.chair_utilization_avg ?? '\u2014'}% | TxClose=${onco.tx_past_close_avg ?? '\u2014'}/day`,
  ].join('\n')

  const ioptRows = (currentMonthData?.ioptimize ?? [])
    .map(r => {
      const parts = [`  ${r.location}`]
      if (r.scheduler_compliance_avg != null) parts.push(`SC=${r.scheduler_compliance_avg}%`)
      if (r.avg_delay_avg != null) parts.push(`Delay=${r.avg_delay_avg}min`)
      if (r.chair_utilization_avg != null) parts.push(`CU=${r.chair_utilization_avg}%`)
      if (r.tx_past_close_avg != null) parts.push(`TxClose=${r.tx_past_close_avg}/day`)
      if (r.composite_score != null) parts.push(`Score=${r.composite_score}`)
      if (Array.isArray(r.outlier_flags) && r.outlier_flags.length > 0) {
        parts.push(`OUTLIER: ${r.outlier_flags.join(', ')}`)
      }
      return parts.join(' | ')
    })
    .join('\n')

  const iassignRows = (currentMonthData?.iassign ?? [])
    .map(r => {
      const parts = [`  ${r.location}`]
      if (r.iassign_utilization_avg != null) parts.push(`iAssign=${r.iassign_utilization_avg}%`)
      if (r.patients_per_nurse_avg != null) parts.push(`Pts/Nurse=${r.patients_per_nurse_avg}`)
      if (r.chairs_per_nurse_avg != null) parts.push(`Chairs/Nurse=${r.chairs_per_nurse_avg}`)
      if (r.nurse_utilization_avg != null) parts.push(`NurseUtil=${r.nurse_utilization_avg}%`)
      if (Array.isArray(r.outlier_flags) && r.outlier_flags.length > 0) {
        parts.push(`OUTLIER: ${r.outlier_flags.join(', ')}`)
      }
      return parts.join(' | ')
    })
    .join('\n')

  const momRows = (currentMonthData?.ioptimize ?? [])
    .filter(r => r.mom_deltas && Object.keys(r.mom_deltas).length > 0 && r.location !== 'Company Avg' && r.location !== 'Onco')
    .map(r => {
      const deltas = Object.entries(r.mom_deltas)
        .map(([k, v]) => `${k}: ${v > 0 ? '+' : ''}${v}`)
        .join(', ')
      return `  ${r.location}: ${deltas}`
    })
    .join('\n')

  const vsCompanyRows = (currentMonthData?.ioptimize ?? [])
    .filter(r => r.vs_company && Object.keys(r.vs_company).length > 0 && r.location !== 'Company Avg')
    .map(r => {
      const flags = Object.entries(r.vs_company).map(([k, v]) => `${k}: ${v}`).join(', ')
      return `  ${r.location}: ${flags}`
    })
    .join('\n')

  return [
    'You are the Lead Healthcare Operations Analyst for the OncoSmart C-suite dashboard.',
    'Your purpose: precise, visually compelling, immediately actionable intelligence.',
    '',
    '## 1. PERSONA & RESPONSE STYLE',
    '',
    'For data questions \u2014 drop all pleasantries. Lead with the finding, not an introduction.',
    '',
    'STRICTLY FORBIDDEN in every response:',
    '- Greetings of any kind: "Hi", "Hello", "Sure", "Great question", "Certainly", "Of course"',
    '- Meta-commentary: "I\'ll analyze this", "Looking at the data", "As your analyst", "Based on the information provided"',
    '- Closings: "I hope this helps", "Let me know if you have questions", "Feel free to ask"',
    '- Emojis or decorative symbols',
    '- Padding transitions: "That said", "With that in mind", "It\'s worth noting that"',
    '',
    'For small talk: one brief professional sentence, then redirect to data.',
    'Format with Markdown: **bold** key numbers, bullet lists for multi-item findings, ## headers for sections.',
    'Lead every response with the single highest-priority finding. Caveats go at the END.',
    '',
    '## 2. ANALYTICAL STANDARDS',
    '',
    '- Every claim requires a specific number from the dataset. No generalities.',
    '- Anchor every comparison with both values: "BCC MO (**97.9%**) vs. Company Avg (**66.8%**)" \u2014 not "above average".',
    '- State magnitudes: "rose **4.2 min** from 6.1 to 10.3" \u2014 not "increased significantly".',
    '- Correlation \u2260 causation. Use "associated with", "coincided with" \u2014 NEVER "caused", "drove", "resulted in", "led to".',
    '  ONE exception: Scheduler Compliance and Avg Delay have an established operational link.',
    '- For "why" questions: list 2\u20133 data-supported hypotheses; close with what on-the-ground investigation would confirm.',
    '- NULL or missing data: say so explicitly. Never impute or interpolate.',
    '- A MoM change is meaningful only if |delta| > ~0.5 standard deviations or > 3 absolute units.',
    '',
    '## 3. BENCHMARK DEFINITIONS \u2014 use precisely',
    '',
    '- **Company Average**: Mean of THIS client\u2019s own clinic locations only. Not a network or industry figure.',
    '- **Onco Benchmark**: Network-wide oncology standard across all clients. The aspirational target.',
    '- **Composite Score (0\u2013100)**: 50 = network average. 65+ = strong. <40 = needs attention.',
    '  Weights: SC 25%, Delay 20%, Chair Util 20%, iAssign 15%, Tx Past Close 10%, Nurse Util 10%.',
    '  Includes a volatility penalty \u2014 inconsistent clinics score lower.',
    '',
    '## 4. METRIC-SPECIFIC RULES',
    '',
    '- Chair Utilization >100%: overbooking, not a data error. Trending toward 100% = improving capacity management.',
    '- Scheduler Compliance: frequently NULL. Absence \u2260 poor performance.',
    '- Tx Past Close/Day: lower is better. Zero is ideal. High values drive staff overtime.',
    '- Patients/Nurse: context-dependent. Too high = understaffing. Too low = inefficiency.',
    '',
    '## 5. DATA VISUALIZATION \u2014 CRITICAL',
    '',
    'Whenever a comparison, trend, or multi-location breakdown would aid understanding, you MUST output a chart.',
    'Use charts for: any 3+ data point comparison, multi-location analysis, 6-month trends, benchmark vs. actuals.',
    'Do NOT use charts for: single-value answers, yes/no questions, simple factual lookups.',
    '',
    'Output charts as a Markdown code block with the language tag `recharts`. Place a brief explanatory sentence BEFORE the block.',
    '',
    'Bar chart example (location comparisons):',
    '```recharts',
    '{"type":"BarChart","title":"Chair Utilization by Location","data":[{"name":"BCC MO","value":97.89},{"name":"MTH MO","value":45.2},{"name":"Company Avg","value":66.82},{"name":"Onco","value":68.0}],"xAxisKey":"name","series":[{"dataKey":"value","color":"#0D9488","name":"Chair Util %"}]}',
    '```',
    '',
    'Line chart example (6-month trend):',
    '```recharts',
    '{"type":"LineChart","title":"Avg Delay \u2014 6mo Trend","data":[{"name":"2025-09","value":11.2},{"name":"2025-10","value":10.8},{"name":"2025-11","value":9.4},{"name":"2026-01","value":9.43}],"xAxisKey":"name","series":[{"dataKey":"value","color":"#0D9488","name":"Avg Delay (min)"}]}',
    '```',
    '',
    'Multi-series example (two metrics side by side):',
    '```recharts',
    '{"type":"BarChart","title":"Delay vs. Chair Util by Location","data":[{"name":"BCC MO","delay":9.43,"cu":97.89},{"name":"MTH MO","delay":12.1,"cu":45.2}],"xAxisKey":"name","series":[{"dataKey":"delay","color":"#DC2626","name":"Avg Delay (min)"},{"dataKey":"cu","color":"#0D9488","name":"Chair Util %"}]}',
    '```',
    '',
    'Schema rules:',
    '- type: "BarChart" | "LineChart" | "AreaChart"',
    '- data: array of objects; each must have the xAxisKey field plus all series dataKey fields',
    '- series: one entry per metric; colors: #0D9488 (teal), #6366F1 (indigo), #DC2626 (red), #F59E0B (amber)',
    '- Output valid JSON only \u2014 no trailing commas, no comments, no newlines inside the block',
    '- One chart per topic; use multiple series in one chart for related metrics',
    '',
    '## KPI DEFINITIONS',
    kpiText || '(no definitions provided)',
    '',
    '## DATA NOTES',
    data_notes || '(none)',
    '',
    '## BENCHMARKS FOR THIS REPORTING PERIOD',
    benchmarkText || '(no benchmark data)',
    '',
    '## CURRENT MONTH \u2014 iOptimize KPIs',
    ioptRows || '(no iOptimize data)',
    '',
    '## CURRENT MONTH \u2014 iAssign KPIs',
    iassignRows || '(no iAssign data)',
    '',
    '## MONTH-OVER-MONTH DELTAS (iOptimize)',
    momRows || '(no prior month data)',
    '',
    '## vs COMPANY AVERAGE FLAGS',
    vsCompanyRows || '(none)',
    '',
    '## HISTORICAL KPIs (last 6 months)',
    historyText || '(no historical data)',
  ].join('\n')
}

// streamChat — routes through the FastAPI backend RAG endpoint.
// The backend queries PostgreSQL (KPIs + ML analytics), builds the system prompt
// server-side, calls Anthropic, and forwards the SSE stream.
// No API key required on the client; credentials stay server-side.
export async function* streamChat(messages, clientCode, activeMonth) {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), 30000)

  let resp
  try {
    resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        messages,
        client_code: clientCode,
        run_month: activeMonth || null,
      }),
      signal: controller.signal,
    })
  } catch (err) {
    clearTimeout(timeoutId)
    if (err.name === 'AbortError') throw new Error('Request timed out — the server did not respond.')
    throw err
  }

  if (!resp.ok) {
    clearTimeout(timeoutId)
    yield '**System Update:** The OncoSmart AI engine is currently being migrated to our new AWS production infrastructure. Full capabilities will be restored shortly.'
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop()
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const raw = line.slice(6).trim()
        if (raw === '[DONE]') return
        let event
        try {
          event = JSON.parse(raw)
        } catch {
          continue
        }
        if (event.type === 'error') {
          throw new Error(event.message || 'The server encountered an error.')
        }
        if (event.type === 'content_block_delta' && event.delta?.type === 'text_delta') {
          yield event.delta.text
        }
      }
    }
  } catch (err) {
    reader.cancel()
    if (err.name === 'AbortError') throw new Error('Request timed out — the server did not respond.')
    throw err
  } finally {
    clearTimeout(timeoutId)
  }
}
