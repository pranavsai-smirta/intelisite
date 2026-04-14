import { HashRouter, Routes, Route } from 'react-router-dom'
import { AiProvider } from './contexts/AiContext'
import CTOMasterView from './pages/CTOMasterView'
import ClinicView from './pages/ClinicView'

export default function App() {
  return (
    <AiProvider>
      <HashRouter>
        <Routes>
          <Route path="/" element={<CTOMasterView />} />
          <Route path="/clinic/:clientCode" element={<ClinicView />} />
        </Routes>
      </HashRouter>
    </AiProvider>
  )
}
