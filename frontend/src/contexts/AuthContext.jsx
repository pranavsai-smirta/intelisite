import { createContext, useContext, useState } from 'react'

const DEMO_USERNAME = 'admin'
const DEMO_PASSWORD_SHA256 = '6d397af35f036e147a3cbc718c1d09ef997ba5d4509991e9872b10a6cadb300c'

const CTO_USERNAME = 'smirta'
const CTO_PASSWORD_SHA256 = '30146b9bf4fb1f9710d56cbb44fa2c48857f994fd75e5af5dd470d92b3cd1caf'

const STORAGE_KEY = 'smirta_auth_v1'

async function sha256hex(str) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(str))
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('')
}

async function checkCredentials(username, password) {
  const hash = await sha256hex(password)
  if (username === CTO_USERNAME && hash === CTO_PASSWORD_SHA256) return 'cto'
  if (username === DEMO_USERNAME && hash === DEMO_PASSWORD_SHA256) return 'demo'
  return null
}

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [role, setRole] = useState(() => {
    const v = localStorage.getItem(STORAGE_KEY)
    return v === 'demo' || v === 'cto' ? v : null
  })

  async function login(username, password) {
    const matched = await checkCredentials(username, password)
    if (!matched) return null
    localStorage.setItem(STORAGE_KEY, matched)
    setRole(matched)
    return matched
  }

  async function elevateToCto(username, password) {
    const matched = await checkCredentials(username, password)
    if (matched !== 'cto') return false
    localStorage.setItem(STORAGE_KEY, 'cto')
    setRole('cto')
    return true
  }

  function logout() {
    localStorage.removeItem(STORAGE_KEY)
    setRole(null)
  }

  return (
    <AuthContext.Provider value={{ role, authed: role !== null, login, elevateToCto, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
