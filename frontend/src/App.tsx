import { useSessionStore } from './store/session'
import { FileUpload, MapCanvas } from './components'

export default function App() {
  const sessionId = useSessionStore((s) => s.sessionId)

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {sessionId ? <MapCanvas /> : <FileUpload />}
    </div>
  )
}
