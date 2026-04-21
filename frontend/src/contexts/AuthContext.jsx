import { createContext, useContext, useState } from 'react'

const USERNAME = 'admin'
const PASSWORD_SHA256 = '6d397af35f036e147a3cbc718c1d09ef997ba5d4509991e9872b10a6cadb300c'
const STORAGE_KEY = 'smirta_auth_v1'

async function sha256hex(str) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(str))
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('')
}

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [authed, setAuthed] = useState(() => !!localStorage.getItem(STORAGE_KEY))

  async function login(username, password) {
    const hash = await sha256hex(password)
    if (username === USERNAME && hash === PASSWORD_SHA256) {
      localStorage.setItem(STORAGE_KEY, '1')
      setAuthed(true)
      return true
    }
    return false
  }

  function logout() {
    localStorage.removeItem(STORAGE_KEY)
    setAuthed(false)
  }

  return (
    <AuthContext.Provider value={{ authed, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
