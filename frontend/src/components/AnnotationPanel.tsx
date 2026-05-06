import { useCallback } from 'react'
import type { CSSProperties } from 'react'
import { useAppStore } from '../store'
import type { AnnotationType } from '../types'

const TYPES: { type: AnnotationType; label: string; color: string }[] = [
  { type: 'station', label: 'Станция', color: '#10b981' },
  { type: 'profile_segment', label: 'Профиль пути', color: '#f59e0b' },
  { type: 'speed_limit', label: 'Огр. скорости', color: '#ef4444' },
  { type: 'coordinate_ruler', label: 'Координатная линейка', color: '#8b5cf6' },
]

const btn: CSSProperties = {
  width: '100%',
  padding: '6px 10px',
  border: '1px solid #e5e7eb',
  borderRadius: 6,
  background: '#fff',
  cursor: 'pointer',
  fontSize: 12,
  fontFamily: 'inherit',
  textAlign: 'left',
}

export default function AnnotationPanel() {
  const doc = useAppStore((s) => s.doc)
  const selectedId = useAppStore((s) => s.selectedShapeId)
  const annotations = useAppStore((s) => s.annotations)
  const annotate = useAppStore((s) => s.annotate)
  const removeAnnotation = useAppStore((s) => s.removeAnnotation)
  const selectShape = useAppStore((s) => s.selectShape)

  const handleExport = useCallback(() => {
    if (!doc) return
    const annotatedShapes = doc.shapes
      .filter((s) => annotations[s.id])
      .map((s) => ({ ...s, annotation_type: annotations[s.id] }))
    const payload = JSON.stringify(
      { page_width: doc.page_width, page_height: doc.page_height, annotated_shapes: annotatedShapes },
      null,
      2,
    )
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([payload], { type: 'application/json' }))
    a.download = 'annotations.json'
    a.click()
    URL.revokeObjectURL(a.href)
  }, [doc, annotations])

  const annotationCount = Object.keys(annotations).length
  const selectedShape = doc?.shapes.find((s) => s.id === selectedId)

  return (
    <aside
      style={{
        width: 260,
        background: '#fff',
        borderLeft: '1px solid #e5e7eb',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        flexShrink: 0,
      }}
    >
      {/* Header */}
      <div style={{ padding: '12px 14px', borderBottom: '1px solid #e5e7eb' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#1e293b', marginBottom: 2 }}>
          Разметка
        </div>
        <div style={{ fontSize: 11, color: '#94a3b8' }}>
          {annotationCount > 0
            ? `${annotationCount} объектов размечено`
            : 'Кликните на объект на холсте'}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px' }}>
        {selectedShape ? (
          <>
            {/* Shape info */}
            <div
              style={{
                fontSize: 11,
                color: '#64748b',
                background: '#f8fafc',
                border: '1px solid #e5e7eb',
                borderRadius: 6,
                padding: '8px 10px',
                marginBottom: 12,
                lineHeight: 1.7,
              }}
            >
              <div>
                <b>ID:</b> {selectedShape.id}
              </div>
              <div>
                <b>Тип:</b> {selectedShape.shape_type}
              </div>
              {selectedShape.text && (
                <div style={{ wordBreak: 'break-word' }}>
                  <b>Текст:</b> {selectedShape.text}
                </div>
              )}
              <div>
                <b>Размер:</b> {Math.round(selectedShape.width)}×{Math.round(selectedShape.height)}{' '}
                px
              </div>
            </div>

            {/* Annotation type buttons */}
            <div style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 8 }}>
              Назначить тип:
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {TYPES.map(({ type, label, color }) => {
                const isActive = annotations[selectedId!] === type
                return (
                  <button
                    key={type}
                    onClick={() =>
                      isActive ? removeAnnotation(selectedId!) : annotate(selectedId!, type)
                    }
                    style={{
                      ...btn,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      border: `1px solid ${isActive ? color : '#e5e7eb'}`,
                      background: isActive ? color + '18' : '#fff',
                      color: isActive ? color : '#374151',
                      fontWeight: isActive ? 600 : 400,
                    }}
                  >
                    <span
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: 2,
                        background: color,
                        flexShrink: 0,
                      }}
                    />
                    {label}
                    {isActive && (
                      <span style={{ marginLeft: 'auto', fontSize: 11 }}>✓</span>
                    )}
                  </button>
                )
              })}
            </div>

            <div style={{ display: 'flex', gap: 5, marginTop: 10 }}>
              {annotations[selectedId!] && (
                <button
                  onClick={() => removeAnnotation(selectedId!)}
                  style={{
                    ...btn,
                    flex: 1,
                    color: '#ef4444',
                    border: '1px solid #fca5a5',
                    textAlign: 'center',
                  }}
                >
                  Снять
                </button>
              )}
              <button
                onClick={() => selectShape(null)}
                style={{ ...btn, flex: 1, color: '#64748b', textAlign: 'center' }}
              >
                Отменить
              </button>
            </div>
          </>
        ) : (
          annotationCount > 0 && (
            <>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 8 }}>
                Размечено:
              </div>
              {TYPES.map(({ type, label, color }) => {
                const count = Object.values(annotations).filter((t) => t === type).length
                if (count === 0) return null
                return (
                  <div
                    key={type}
                    style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12, color: '#374151', marginBottom: 5 }}
                  >
                    <span
                      style={{ width: 10, height: 10, borderRadius: 2, background: color, flexShrink: 0 }}
                    />
                    {label}: <b>{count}</b>
                  </div>
                )
              })}
            </>
          )
        )}
      </div>

      {/* Export */}
      {annotationCount > 0 && (
        <div style={{ padding: '10px 14px', borderTop: '1px solid #e5e7eb' }}>
          <button
            onClick={handleExport}
            style={{
              width: '100%',
              padding: '8px',
              background: '#3b82f6',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              cursor: 'pointer',
              fontSize: 13,
              fontWeight: 500,
              fontFamily: 'inherit',
            }}
          >
            Экспорт JSON
          </button>
        </div>
      )}
    </aside>
  )
}
