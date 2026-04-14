import { Link, useLocation } from 'react-router-dom'
import { useAi } from '../contexts/AiContext'

export default function NavBar() {
  const location = useLocation()
  const isHome = location.pathname === '/'
  const { aiOpen, openAi, closeAi } = useAi()

  return (
    <nav className="bg-slate-900 border-b border-slate-800 px-6 py-3 flex items-center gap-4 flex-shrink-0">
      <Link to="/" className="flex items-center gap-2" onClick={() => aiOpen && closeAi()}>
        <span className="text-teal-400 font-bold text-sm tracking-widest uppercase">OncoSmart</span>
        <span className="text-slate-400 text-sm font-medium">Network Dashboard</span>
      </Link>

      <div className="ml-auto flex items-center gap-3">
        {!isHome && !aiOpen && (
          <Link
            to="/"
            className="text-slate-400 hover:text-teal-400 text-sm transition-colors"
          >
            {'\u2190'} All Clinics
          </Link>
        )}

        <button
          onClick={aiOpen ? closeAi : openAi}
          className="flex items-center gap-2 text-sm font-medium px-4 py-1.5 rounded-lg transition-all"
          style={
            aiOpen
              ? {
                  background: 'rgba(13,148,136,0.15)',
                  color: '#2DD4BF',
                  border: '1px solid rgba(13,148,136,0.35)',
                }
              : {
                  background: 'linear-gradient(135deg, #0D9488, #0F766E)',
                  color: 'white',
                  border: '1px solid transparent',
                  boxShadow: '0 1px 8px rgba(13,148,136,0.3)',
                }
          }
          aria-label={aiOpen ? 'Close AI view' : 'Open AI assistant'}
        >
          <span style={{ fontSize: '11px', opacity: 0.9 }}>{'\u2726'}</span>
          <span>{aiOpen ? 'Close AI' : 'Ask AI'}</span>
        </button>
      </div>
    </nav>
  )
}
