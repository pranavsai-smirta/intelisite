const API_URL = 'https://api.anthropic.com/v1/messages'
const MODEL = 'claude-sonnet-4-6'

export function buildSystemPrompt(chatbotContext, currentMonthData) {
  const {
    client_name = 'this practice',
    service_type_delays = [],
    kpi_definitions = {},
    data_notes = '',
    business_rules = {},
    glossary = {},
    data_limitations = {},
    precise_kpis = {},
    duration_deviation_analysis = {},
    historical_kpis = [],
    raw_data_context = {},
  } = chatbotContext ?? {}
  const rawMonthly = Array.isArray(raw_data_context.monthly_summaries)
    ? raw_data_context.monthly_summaries : []
  const rawWeekly = Array.isArray(raw_data_context.weekly_summaries)
    ? raw_data_context.weekly_summaries : []

  // Rich KPI spec: label + direction + explanation + formula + filters + edge cases + data_gap
  const kpiText = Object.entries(kpi_definitions)
    .map(([k, v]) => {
      const dir = v.higher_is_better === true ? 'higher is better'
        : v.higher_is_better === false ? 'lower is better'
        : 'context-dependent'
      const lines = [`### ${v.label} (${k}) [${dir}]`, v.explanation]
      if (v.formula) lines.push(`Formula: ${v.formula}`)
      if (Array.isArray(v.filters) && v.filters.length) {
        lines.push(`Filters: ${v.filters.join(' | ')}`)
      }
      if (Array.isArray(v.edge_cases) && v.edge_cases.length) {
        lines.push('Edge cases:')
        v.edge_cases.forEach(e => lines.push(`  - ${e}`))
      }
      if (v.data_gap) lines.push(`DATA GAP: ${v.data_gap}`)
      return lines.join('\n')
    })
    .join('\n\n')

  // Global business rules
  const businessRulesText = Object.entries(business_rules)
    .map(([k, v]) => `- **${k.replace(/_/g, ' ')}**: ${v}`)
    .join('\n')

  // Glossary
  const glossaryText = Object.entries(glossary)
    .map(([k, v]) => `- **${k}**: ${v}`)
    .join('\n')

  // Data limitations
  const dataLimitationsText = Object.entries(data_limitations)
    .map(([k, v]) => {
      const lines = [`### ${k.replace(/_/g, ' ')}`]
      if (v.issue) lines.push(`Issue: ${v.issue}`)
      if (v.effect) lines.push(`Effect on chatbot answers: ${v.effect}`)
      if (v.remediation) lines.push(`Remediation: ${v.remediation}`)
      return lines.join('\n')
    })
    .join('\n\n')

  // Precise recomputed KPIs (per-month rows)
  const preciseMonthly = Array.isArray(precise_kpis.per_month) ? precise_kpis.per_month : []
  const preciseText = preciseMonthly.length
    ? preciseMonthly.map(r => {
        const parts = [`  ${r.location} | ${r.period}`]
        if (r.avg_delay_mins != null) parts.push(`Delay=${r.avg_delay_mins}min`)
        if (r.tx_past_close_per_day != null) parts.push(`TxClose=${r.tx_past_close_per_day}/day`)
        if (r.mins_past_close_per_pt != null) parts.push(`MinsPastClose=${r.mins_past_close_per_pt}min/pt`)
        if (r.chair_utilization_pct != null) parts.push(`CU=${r.chair_utilization_pct}%`)
        if (r.long_duration_treatment_pct != null) parts.push(`LongDur=${r.long_duration_treatment_pct}%`)
        if (r.duration_deviation_over_count != null) {
          parts.push(`DurDev: +${r.duration_deviation_over_count}over/-${r.duration_deviation_under_count}under of ${r.duration_matched_pairs_count}`)
        }
        return parts.join(' | ')
      }).join('\n')
    : '(no precise KPIs computed)'

  const clinicConstantsText = precise_kpis.clinic_constants
    ? Object.entries(precise_kpis.clinic_constants)
        .map(([loc, c]) =>
          `  ${loc}: ${c.num_chairs_derived} chairs (derived), ` +
          `${c.operating_minutes_per_day}min/day op, ` +
          `long-dur threshold=${c.long_duration_threshold_minutes}min (90th pctile)`
        ).join('\n')
    : '(no clinic constants available)'

  // Duration deviation analysis (actual vs scheduled treatment duration)
  const devAna = duration_deviation_analysis || {}
  const devOverall = devAna.overall || {}
  const devPerClinic = Array.isArray(devAna.per_clinic) ? devAna.per_clinic : []
  const devPerBucket = Array.isArray(devAna.per_duration_bucket) ? devAna.per_duration_bucket : []
  const devPerMonth  = Array.isArray(devAna.per_month) ? devAna.per_month : []

  const devOverallText = devOverall.over_10pct_count != null
    ? ('Overall: ' + devOverall.over_10pct_count + ' over >10% (' + devOverall.over_10pct_pct + '%) | '
       + devOverall.under_10pct_count + ' under <-10% (' + devOverall.under_10pct_pct + '%) | '
       + devOverall.within_10pct_count + ' within +-10% (' + devOverall.within_10pct_pct + '%) | '
       + 'avg deviation=' + devOverall.avg_deviation_pct + '% | '
       + 'total matched pairs=' + devAna.total_matched_pairs)
    : '(no deviation data)'

  const devClinicText = devPerClinic.length
    ? devPerClinic.map(c =>
        '  ' + c.location + ': over=' + c.over_pct + '% (' + c.over_count + ') | '
        + 'under=' + c.under_pct + '% (' + c.under_count + ') | '
        + 'within=' + c.within_pct + '% | avg_dev=' + c.avg_deviation_pct + '%'
      ).join('\n')
    : '(no per-clinic data)'

  const devBucketText = devPerBucket.length
    ? devPerBucket.map(b =>
        '  Scheduled ' + b.scheduled_duration_bucket + ': over=' + b.over_pct + '% | under=' + b.under_pct + '% | avg_dev=' + b.avg_deviation_pct + '%'
      ).join('\n')
    : '(no bucket data)'

  const devMonthText = devPerMonth.length
    ? devPerMonth.map(m =>
        '  ' + m.month + ': over=' + m.over_pct + '% | under=' + m.under_pct + '% | avg_dev=' + m.avg_deviation_pct + '%'
      ).join('\n')
    : '(no monthly trend)'

  // Per-service-type delay table: Lab, MD, Injection, Treatment, Outside Infusion
  const svcDelayText = Array.isArray(service_type_delays) && service_type_delays.length
    ? service_type_delays.map(r =>
        '  ' + r.location + ' | ' + r.month + ' | ' + r.service_type +
        ': avg ' + (r.avg_delay_mins_per_visit != null ? r.avg_delay_mins_per_visit : 'N/A') +
        ' min/visit (' + r.total_visits + ' visits)'
      ).join('\n')
    : '(no per-service-type delay data available)'

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

  const rawMonthlyText = rawMonthly
    .map(r => `  ${r.location} | ${r.period} | ${r.category}: ${r.summary}`)
    .join('\n')

  const rawWeeklyText = rawWeekly
    .map(r => `  ${r.location} | week of ${r.period} | ${r.category}: ${r.summary}`)
    .join('\n')

  return [
    '## DATA SCOPE RESTRICTION — READ FIRST',
    'You have been given data for ONE client only: ' + client_name + '.',
    'You MUST NOT reference, speculate about, or discuss data from any other organization,',
    'client code, clinic network, or healthcare system. This includes HOGONC, NCS, PCI,',
    'TNO, CHCWM, MBPCC, PCC, VCI, CCBD, NMCC, LOA, and any other names not present in',
    'the data below. If asked about another organization, respond:',
    '"I only have access to ' + client_name + ' data. I cannot provide information about other organizations."',
    'Every answer you give must be grounded EXCLUSIVELY in the data provided in this system prompt.',
    '',
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
    '## 4b. STAFFING PREDICTION METHODOLOGY',
    '',
    'When asked how many nurses are needed for a future day/shift, use these client-defined operational thresholds:',
    '  - Avg patients/nurse/day: **7\u20139** (optimal range; use 8 as midpoint if no census given)',
    '  - Avg chairs/RN: **3\u20134** (optimal range; use 3.5 as midpoint)',
    '  - Nurse utilization: **\u226550%** (minimum; below this = overstaffed)',
    '',
    'Prediction steps (always show your work):',
    '1. Identify the clinic\u2019s historical avg patients/day from iAssign data (patients_per_nurse \u00d7 nurse count is a proxy).',
    '2. Divide expected patient census by target patients/nurse (8) to get base nurse count. Round UP.',
    '3. Cross-check: chairs at that clinic \u00f7 target chairs/RN (3.5). Both methods should agree within 1 nurse.',
    '4. Verify result keeps nurse utilization \u226550%. If historical utilization was below 50%, flag overstaffing risk.',
    '5. If the user gives a specific patient census, use that. Otherwise use the historical avg as a proxy and state the assumption.',
    '',
    'Always: state the assumption used, round up to whole nurses, give a range (low/high estimate using 7 and 9 as bounds).',
    'NEVER refuse a staffing question because a census is missing \u2014 estimate from historical data and label it a projection.',
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
    '## FORMAL KPI SPECIFICATIONS',
    'Each KPI below includes its exact formula, required filters, edge cases, and any data gaps.',
    'When a user asks HOW something is calculated, cite the formula. When a DATA GAP is present,',
    'state it explicitly and do not fabricate a precise value.',
    '',
    kpiText || '(no KPI definitions available)',
    '',
    '## GLOBAL BUSINESS RULES',
    'Apply these rules to EVERY computation and answer unless the user explicitly overrides one.',
    '',
    businessRulesText || '(none)',
    '',
    '## GLOSSARY -- KEY TERMS',
    'Quote these definitions verbatim when a user asks what a term means.',
    '',
    glossaryText || '(none)',
    '',
    '## DATA LIMITATIONS & CAVEATS',
    'When a user asks about any of the following KPIs or data issues, you MUST surface the',
    'relevant limitation rather than answering as if the data were clean.',
    '',
    dataLimitationsText || '(none)',
    '',
    '## PRECISE RECOMPUTED KPIs (Bhaskar 2024-10 formulas)',
    precise_kpis.source || '',
    'KPIs computed: ' + (Array.isArray(precise_kpis.kpis_computed) ? precise_kpis.kpis_computed.join(', ') : 'none'),
    'Prefer these values over legacy KPI data when answering questions about Treatment delays,',
    'chair utilization, and treatments-past-close. Always cite "precise computation" as the source.',
    '',
    '### Clinic constants',
    clinicConstantsText,
    '',
    '### Per-month precise values (KPIs 2, 3, 4, 5 + duration)',
    preciseText,
    '',
    '## TREATMENT DURATION DEVIATION ANALYSIS (actual vs scheduled)',
    'Source: ' + (devAna.source || 'chr_raw_schedule_list JOIN chr_raw_visit_list'),
    'Join key: ' + (devAna.join_key || '(patient_id, date, service_type=Treatment)'),
    'CRITICAL INSIGHT: Most treatments finish EARLY vs scheduled. Short infusions (61-120min) most often',
    'run OVER schedule. Long infusions (271min+) most often finish early by large margins.',
    'When a user asks about duration deviation, quote these numbers directly. Do NOT summarize vaguely.',
    '',
    devOverallText,
    '',
    '### Per-clinic breakdown',
    devClinicText,
    '',
    '### By scheduled duration bucket (the key pattern for clinical insight)',
    devBucketText,
    '',
    '### Monthly trend (all clinics combined)',
    devMonthText,
    '',
    '## PER-SERVICE-TYPE DELAYS (Lab, MD, Injection, Treatment, Outside Infusion)',
    'This table contains avg delay per visit for EVERY service type — not just Treatment.',
    'Use this when users ask about Lab delay, MD delay, Injection delay, etc.',
    'Source: chr_raw_service_totals (per-day CSV data, all 6 months).',
    '',
    svcDelayText,
    '',
    '## DATA NOTES (legacy pipeline)',
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
    '',
    '## RAW DAILY-DATA NARRATIVES \u2014 monthly rollups (per location)',
    'These come from per-day operational CSVs (scheduler productivity, nurse utilization, time-block distribution, etc.). Use them to explain WHY metrics moved \u2014 frontloaded scheduling, MD/Tx coordination gaps, peak overtime days.',
    rawMonthlyText || '(no raw monthly summaries available)',
    '',
    '## RAW DAILY-DATA NARRATIVES \u2014 weekly rollups (per location)',
    'Quote these only when the user asks about a specific week or recent operational variance.',
    rawWeeklyText || '(no raw weekly summaries available)',
  ].join('\n')
}

// BYOK: reads the key from localStorage and calls Anthropic directly.
// Set it once in the browser devtools console before using the chatbot:
//   localStorage.setItem('anthropic_api_key', 'sk-ant-...')
// The key never leaves the browser and is never committed to git.
export async function* streamChat(messages, systemPrompt) {
  const apiKey = localStorage.getItem('anthropic_api_key')
  if (!apiKey) {
    throw new Error('No API key found. Set localStorage.anthropic_api_key to your Anthropic key.')
  }

  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), 30000)

  let resp
  try {
    resp = await fetch(API_URL, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'anthropic-dangerous-direct-browser-access': 'true',
      },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: 1500,
        stream: true,
        system: systemPrompt,
        messages,
      }),
      signal: controller.signal,
    })
  } catch (err) {
    clearTimeout(timeoutId)
    if (err.name === 'AbortError') throw new Error('Request timed out — Anthropic did not respond.')
    throw err
  }

  if (!resp.ok) {
    clearTimeout(timeoutId)
    const text = await resp.text()
    throw new Error(`Anthropic API error ${resp.status}: ${text}`)
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
          throw new Error(event.message || 'Anthropic returned a stream error.')
        }
        if (event.type === 'content_block_delta' && event.delta?.type === 'text_delta') {
          yield event.delta.text
        }
      }
    }
  } catch (err) {
    reader.cancel()
    if (err.name === 'AbortError') throw new Error('Request timed out — Anthropic did not respond.')
    throw err
  } finally {
    clearTimeout(timeoutId)
  }
}
