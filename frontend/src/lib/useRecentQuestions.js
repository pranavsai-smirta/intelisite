import { useState, useCallback } from 'react'

const STORAGE_KEY = 'chatbot_recent_questions'
const MAX_HISTORY = 20

export function useRecentQuestions() {
  function _read() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    } catch {
      return []
    }
  }

  const [recent, setRecent] = useState(() => _read().slice(0, 3))

  const logQuestion = useCallback((q) => {
    if (!q?.trim()) return
    try {
      const prev = _read()
      const deduped = [q, ...prev.filter(x => x !== q)].slice(0, MAX_HISTORY)
      localStorage.setItem(STORAGE_KEY, JSON.stringify(deduped))
      setRecent(deduped.slice(0, 3))
    } catch {}
  }, [])

  return { recent, logQuestion }
}
