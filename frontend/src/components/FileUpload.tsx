import { useRef, useState, useCallback } from 'react'
import { createSession } from '../api'
import { useSessionStore } from '../store/session'

export default function FileUpload() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const { setSession, loadShapes } = useSessionStore()

  const handleFile = useCallback(
    async (file: File) => {
      setUploading(true)
      setLocalError(null)
      try {
        const meta = await createSession(file)
        setSession(meta.session_id, meta.page_width, meta.page_height, meta.shape_count, file.name, meta.svg_url)
        loadShapes(meta.session_id, meta.shape_count)
      } catch (e) {
        setLocalError(e instanceof Error ? e.message : String(e))
      } finally {
        setUploading(false)
      }
    },
    [setSession, loadShapes],
  )

  const handleChange = useCallback(
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
      onDrop={handleDrop}
      onDragOver={(e) => e.preventDefault()}
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 16,
        background: '#f8fafc',
      }}
    >
      <div
        style={{
          padding: '48px 64px',
          border: '2px dashed #cbd5e1',
          borderRadius: 12,
          textAlign: 'center',
          background: '#fff',
        }}
      >
        <div style={{ fontSize: 14, color: '#64748b', marginBottom: 20 }}>
          Перетащите файл .vsdx или .vsd сюда, или:
        </div>
        <button
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          style={{
            padding: '10px 24px',
            background: uploading ? '#94a3b8' : '#3b82f6',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            cursor: uploading ? 'wait' : 'pointer',
            fontSize: 14,
            fontWeight: 500,
            fontFamily: 'inherit',
          }}
        >
          {uploading ? 'Загрузка…' : 'Выбрать файл'}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".vsdx,.vsd"
          style={{ display: 'none' }}
          onChange={handleChange}
        />
        {localError && (
          <div style={{ marginTop: 14, fontSize: 12, color: '#ef4444', maxWidth: 360 }}>
            {localError}
          </div>
        )}
      </div>
    </div>
  )
}
