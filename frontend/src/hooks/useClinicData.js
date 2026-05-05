import { useState, useEffect } from 'react'

const cache = {}

// ─── TEMPORARY: Hide GAMCN locations from AON for INHAR meeting ───
// Remove this entire block + the applyHiddenLocations call below to restore.
const HIDDEN_LOCATIONS = {
  AON: ['GAMCN'],  // hide any location whose name starts with "GAMCN"
}

function applyHiddenLocations(clientCode, json) {
  const prefixes = HIDDEN_LOCATIONS[clientCode]
  if (!prefixes) return json

  const isHidden = (name) =>
    prefixes.some(p => (name || '').toUpperCase().startsWith(p))

  const filterRows = (rows) =>
    rows ? rows.filter(r => !isHidden(r.location)) : rows

  // Deep-clone so we never mutate the original
  const out = JSON.parse(JSON.stringify(json))

  // Filter every month's ioptimize, iassign, and ml_analytics
  for (const [, monthData] of Object.entries(out.months || {})) {
    monthData.ioptimize = filterRows(monthData.ioptimize)
    monthData.iassign = filterRows(monthData.iassign)

    // Scrub AI insight text — remove sentences mentioning hidden locations
    if (monthData.ai_insights) {
      const scrub = (text) => {
        if (!text) return text
        // 1. Strip hidden location names inline (e.g. "GAMCN CGCC Macon", "GAMCN Macon")
        let cleaned = text
        for (const p of prefixes) {
          // Remove the full location name (prefix + any trailing words until comma/period/semicolon)
          cleaned = cleaned.replace(new RegExp(p + `[A-Za-z\\s]*`, 'gi'), '')
        }
        // 2. Clean up leftover artefacts from removal
        cleaned = cleaned
          .replace(/,\s*,/g, ',')               // double commas
          .replace(/\bwhile\s*[.,]/gi, '')       // dangling "while ,"
          .replace(/\band\s*[.,]/gi, '')         // dangling "and ,"
          .replace(/\bboth\s+clinics\b/gi, 'the clinic')  // "Both clinics" → "the clinic"
          .replace(/\s{2,}/g, ' ')               // collapse whitespace
          .trim()
        // 3. Drop any now-empty sentences
        cleaned = cleaned
          .split(/(?<=[.!?])\s+/)
          .filter(s => s.trim().length > 10)     // drop stubs
          .join(' ')
          .trim()
        return cleaned || ''
      }
      monthData.ai_insights.executive_summary = scrub(monthData.ai_insights.executive_summary)
      monthData.ai_insights.highlights = (monthData.ai_insights.highlights || []).map(scrub).filter(Boolean)
      monthData.ai_insights.concerns = (monthData.ai_insights.concerns || []).map(scrub).filter(Boolean)
      monthData.ai_insights.recommendations = (monthData.ai_insights.recommendations || []).map(scrub).filter(Boolean)
    }

    // Remove hidden locations from ml_analytics
    if (monthData.ml_analytics?.locations) {
      for (const key of Object.keys(monthData.ml_analytics.locations)) {
        if (isHidden(key)) delete monthData.ml_analytics.locations[key]
      }
    }
  }

  // Filter chatbot_context historical KPIs
  if (out.chatbot_context?.historical_kpis) {
    out.chatbot_context.historical_kpis = out.chatbot_context.historical_kpis
      .filter(r => !isHidden(r.location))
  }

  return out
}
// ─── END TEMPORARY ───

export function useClinicData(clientCode) {
  const [data, setData] = useState(cache[clientCode] ?? null)
  const [loading, setLoading] = useState(!cache[clientCode])
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!clientCode) return
    if (cache[clientCode]) {
      setData(cache[clientCode])
      setLoading(false)
      return
    }
    setLoading(true)
    const url = `${import.meta.env.BASE_URL}data/${clientCode}.json`
    fetch(url)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(json => {
        // TEMPORARY: apply location hiding for INHAR meeting
        const filtered = applyHiddenLocations(clientCode, json)
        cache[clientCode] = filtered
        setData(filtered)
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [clientCode])

  return { data, loading, error }
}
