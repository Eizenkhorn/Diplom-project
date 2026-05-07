import { useEffect } from 'react'
import { useSessionStore } from './store/session'
import { useRegionsStore } from './store/regions'
import { getSession } from './api'
import { FileUpload, MapCanvas } from './components'

export default function App() {
  const { sessionId, setSession } = useSessionStore()
  const { loadRegions, reset: resetRegions } = useRegionsStore()

  // Restore session from localStorage on first mount
  useEffect(() => {
    const saved = localStorage.getItem('mprk_session_id')
    if (!saved || sessionId) return
    getSession(saved)
      .then((data) => {
        setSession(data.session_id, data.page_width, data.page_height, '', data.svg_url)
        return loadRegions(data.session_id)
      })
      .catch(() => {
        localStorage.removeItem('mprk_session_id')
        resetRegions()
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {sessionId ? <MapCanvas /> : <FileUpload />}
    </div>
  )
}
