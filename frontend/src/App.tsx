import { useRef, useCallback, useState } from 'react'
import { useAppStore } from './store'
import { parseFile } from './api'
import { DiagramCanvas, AnnotationPanel } from './components'

export default function App() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const doc = useAppStore((s) => s.doc)
  const setDoc = useAppStore((s) => s.setDoc)

  const handleFile = useCallback(
    async (file: File) => {
      setLoading(true)
      setError(null)
      try {
        const parsed = await parseFile(file)
        setDoc(parsed)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    },
    [setDoc],
  )

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (file) handleFile(file)
      e.target.value = ''
    },
    [handleFile],
  )

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      const file = e.dataTransfer.files[0]
      if (file) handleFile(file)
    },
    [handleFile],
  )

  return (
    <div
      style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}
      onDrop={handleDrop}
      onDragOver={(e) => e.preventDefault()}
    >
      {/* Toolbar */}
      <div
        style={{
          height: 48,
          background: '#0f172a',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '0 16px',
          flexShrink: 0,
          borderBottom: '1px solid #1e293b',
        }}
      >
        <span style={{ fontSize: 15, fontWeight: 700, color: '#f8fafc', letterSpacing: 0.5 }}>
          МПРК
        </span>
        <span style={{ color: '#334155', fontSize: 13 }}>|</span>
        {doc ? (
          <span style={{ fontSize: 12, color: '#64748b' }}>
            {doc.shapes.length} объектов · {Math.round(doc.page_width)}×{Math.round(doc.page_height)}{' '}
            px
          </span>
        ) : (
          <span style={{ fontSize: 12, color: '#334155' }}>
            Модуль преобразования режимных карт
          </span>
        )}

        <div style={{ flex: 1 }} />

        {error && <span style={{ fontSize: 12, color: '#f87171', maxWidth: 300 }}>{error}</span>}

        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={loading}
          style={{
            padding: '5px 14px',
            background: loading ? '#334155' : '#3b82f6',
            color: loading ? '#94a3b8' : '#fff',
            border: 'none',
            borderRadius: 6,
            cursor: loading ? 'wait' : 'pointer',
            fontSize: 13,
            fontWeight: 500,
            fontFamily: 'inherit',
          }}
        >
          {loading ? 'Загрузка...' : 'Открыть .vsdx'}
        </button>

        <input
          ref={fileInputRef}
          type="file"
          accept=".vsdx,.vsd"
          style={{ display: 'none' }}
          onChange={handleInputChange}
        />
      </div>

      {/* Main area: canvas + sidebar */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <DiagramCanvas />
        <AnnotationPanel />
      </div>
    </div>
  )
}
