import { Link, useLocation } from 'react-router-dom'
import { useAi } from '../contexts/AiContext'

export default function NavBar() {
  const location = useLocation()
  const isHome = location.pathname === '/'
  const { aiOpen, openAi, closeAi } = useAi()

  return (
    <nav
      className="px-6 py-3 flex items-center gap-4 flex-shrink-0"
      style={{ background: 'linear-gradient(135deg, #FE6325, #E85520)' }}
    >
      <Link to="/" className="flex items-center gap-4" onClick={() => aiOpen && closeAi()}>
        <img src={`${import.meta.env.BASE_URL}smirta-logo.png`} alt="Smirta" style={{ height: 52, objectFit: 'contain' }} />
        <span className="text-white font-semibold" style={{ fontSize: '22px', letterSpacing: '-0.01em' }}>iNtellisite</span>
      </Link>

      <div className="ml-auto flex items-center gap-3">
        {!isHome && !aiOpen && (
          <Link
            to="/"
            className="text-white/80 hover:text-white text-sm transition-colors"
          >
            {'\u2190'} All Clinics
          </Link>
        )}

        <button
          onClick={aiOpen ? closeAi : openAi}
          className="flex items-center gap-2 text-sm font-medium px-4 py-1.5 rounded-full transition-all"
          style={
            aiOpen
              ? {
                  background: 'white',
                  color: '#FE6325',
                  border: '1px solid white',
                }
              : {
                  background: 'white',
                  color: '#FE6325',
                  border: '1px solid transparent',
                  boxShadow: '0 1px 8px rgba(0,0,0,0.12)',
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
