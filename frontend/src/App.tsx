import { useEffect } from 'react'
import { useSessionStore } from './store/session'
import { useMarkupStore } from './store/markup'
import { getSession } from './api'
import { FileUpload, MapCanvas } from './components'

export default function App() {
  const { sessionId, setSession } = useSessionStore()
  const { loadMarkup, reset: resetMarkup } = useMarkupStore()

  // Restore session from localStorage on first mount
  useEffect(() => {
    const saved = localStorage.getItem('mprk_session_id')
    if (!saved || sessionId) return
    getSession(saved)
      .then((data) => {
        setSession(data.session_id, data.page_width, data.page_height, '', data.svg_url)
        return loadMarkup(data.session_id)
      })
      .catch(() => {
        localStorage.removeItem('mprk_session_id')
        resetMarkup()
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {sessionId ? <MapCanvas /> : <FileUpload />}
    </div>
  )
}
