import { useState, useEffect } from 'react'

const cache = {}

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
        cache[clientCode] = json
        setData(json)
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [clientCode])

  return { data, loading, error }
}
