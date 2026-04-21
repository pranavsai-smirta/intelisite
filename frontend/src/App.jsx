import { HashRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { AiProvider } from './contexts/AiContext'
import LoginScreen from './components/LoginScreen'
import CTOMasterView from './pages/CTOMasterView'
import ClinicView from './pages/ClinicView'

function AuthGate({ children }) {
  const { authed } = useAuth()
  return authed ? children : <LoginScreen />
}

export default function App() {
  return (
    <AuthProvider>
      <AuthGate>
        <AiProvider>
          <HashRouter>
            <Routes>
              <Route path="/" element={<CTOMasterView />} />
              <Route path="/clinic/:clientCode" element={<ClinicView />} />
            </Routes>
          </HashRouter>
        </AiProvider>
      </AuthGate>
    </AuthProvider>
  )
}
