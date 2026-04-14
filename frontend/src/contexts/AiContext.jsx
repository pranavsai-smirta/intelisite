import { createContext, useContext, useState } from 'react'

const AiContext = createContext(null)

export function AiProvider({ children }) {
  const [aiOpen, setAiOpen] = useState(false)
  return (
    <AiContext.Provider value={{ aiOpen, openAi: () => setAiOpen(true), closeAi: () => setAiOpen(false) }}>
      {children}
    </AiContext.Provider>
  )
}

export function useAi() {
  return useContext(AiContext)
}
