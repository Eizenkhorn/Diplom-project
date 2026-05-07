import { useRef, useEffect, useState, useCallback, Fragment } from 'react'
import { Stage, Layer, Rect, Text, Image as KonvaImage, Transformer } from 'react-konva'
import type Konva from 'konva'
import { useSessionStore } from '../store/session'
import { useRegionsStore } from '../store/regions'
import { ANNOTATION_TYPES } from '../types'
import type { RegionType } from '../types'

type DrawState = { startX: number; startY: number; curX: number; curY: number }
type TypePickerState = {
  rect: { x: number; y: number; w: number; h: number }
  screenX: number
  screenY: number
}

export default function MapCanvas() {
  const { pageWidth, pageHeight, svgUrl, fileName } = useSessionStore()
  const {
    regions, selectedId, mode, drawType,
    setMode, setDrawType, selectRegion, createRegion, updateRegion, deleteRegion,
  } = useRegionsStore()

  const containerRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<Konva.Stage>(null)
  const transformerRef = useRef<Konva.Transformer>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [scale, setScale] = useState(1)
  const [pos, setPos] = useState({ x: 0, y: 0 })
  const [bgImage, setBgImage] = useState<HTMLImageElement | null>(null)
  const [drawState, setDrawState] = useState<DrawState | null>(null)
  const [typePicker, setTypePicker] = useState<TypePickerState | null>(null)

  // Load SVG/PNG background
  useEffect(() => {
    if (!svgUrl) { setBgImage(null); return }
    const img = new window.Image()
    img.src = svgUrl
    img.onload = () => setBgImage(img)
    img.onerror = () => setBgImage(null)
  }, [svgUrl])

  // Measure canvas container
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      setSize({ w: entry.contentRect.width, h: entry.contentRect.height })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const fitToScreen = useCallback(() => {
    if (!pageWidth || !pageHeight || !size.w || !size.h) return
    const s = Math.min(size.w / pageWidth, size.h / pageHeight) * 0.95
    setScale(s)
    setPos({ x: (size.w - pageWidth * s) / 2, y: (size.h - pageHeight * s) / 2 })
  }, [pageWidth, pageHeight, size])

  const fittedKey = useRef('')
  useEffect(() => {
    const key = `${pageWidth}x${pageHeight}x${size.w}x${size.h}`
    if (!pageWidth || !pageHeight || !size.w || fittedKey.current === key) return
    fittedKey.current = key
    fitToScreen()
  }, [pageWidth, pageHeight, size, fitToScreen])

  // Attach Transformer to selected region in select mode
  useEffect(() => {
    const tr = transformerRef.current
    if (!tr) return
    if (mode !== 'select' || !selectedId) {
      tr.nodes([])
      return
    }
    const node = stageRef.current?.findOne(`#r-${selectedId}`) as Konva.Node | undefined
    if (node) {
      tr.nodes([node])
      tr.getLayer()?.batchDraw()
    } else {
      tr.nodes([])
    }
  }, [selectedId, mode, regions])

  // Delete key handler in select mode
  useEffect(() => {
    if (mode !== 'select') return
    const onKey = (e: KeyboardEvent) => {
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedId) {
        deleteRegion(selectedId)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mode, selectedId, deleteRegion])

  // Cancel draw/picker when switching away from draw mode
  useEffect(() => {
    if (mode !== 'draw') {
      setDrawState(null)
      setTypePicker(null)
    }
  }, [mode])

  // ── stage event handlers ───────────────────────────────────────────────────

  const handleWheel = useCallback((e: Konva.KonvaEventObject<WheelEvent>) => {
    e.evt.preventDefault()
    const stage = stageRef.current
    if (!stage) return
    const factor = e.evt.deltaY < 0 ? 1.1 : 1 / 1.1
    const oldScale = stage.scaleX()
    const newScale = Math.min(20, Math.max(0.05, oldScale * factor))
    const pointer = stage.getPointerPosition()!
    const newX = pointer.x - (pointer.x - stage.x()) * (newScale / oldScale)
    const newY = pointer.y - (pointer.y - stage.y()) * (newScale / oldScale)
    setScale(newScale)
    setPos({ x: newX, y: newY })
  }, [])

  const handleDragEnd = useCallback((e: Konva.KonvaEventObject<DragEvent>) => {
    setPos({ x: e.target.x(), y: e.target.y() })
  }, [])

  const handleMouseDown = useCallback((e: Konva.KonvaEventObject<MouseEvent>) => {
    if (mode !== 'draw') return
    // Only start drawing on the stage background, not on existing regions
    if (e.target !== stageRef.current) return
    const stage = stageRef.current!
    const p = stage.getRelativePointerPosition()!
    setDrawState({ startX: p.x, startY: p.y, curX: p.x, curY: p.y })
    setTypePicker(null)
  }, [mode])

  const handleMouseMove = useCallback((e: Konva.KonvaEventObject<MouseEvent>) => {
    if (mode !== 'draw' || !drawState) return
    const stage = stageRef.current!
    const p = stage.getRelativePointerPosition()!
    setDrawState((s) => s ? { ...s, curX: p.x, curY: p.y } : null)
  }, [mode, drawState])

  const handleMouseUp = useCallback((e: Konva.KonvaEventObject<MouseEvent>) => {
    if (mode !== 'draw' || !drawState) return
    const w = Math.abs(drawState.curX - drawState.startX)
    const h = Math.abs(drawState.curY - drawState.startY)
    if (w > 8 && h > 8) {
      const x = Math.min(drawState.startX, drawState.curX)
      const y = Math.min(drawState.startY, drawState.curY)
      // Screen position for the type picker: bottom-left of the drawn rect
      const screenX = x * scale + pos.x
      const screenY = (y + h) * scale + pos.y
      setTypePicker({ rect: { x, y, w, h }, screenX, screenY })
    }
    setDrawState(null)
  }, [mode, drawState, scale, pos])

  const handleStageClick = useCallback((e: Konva.KonvaEventObject<MouseEvent>) => {
    if (mode !== 'select') return
    if (e.target === stageRef.current) {
      selectRegion(null)
    }
  }, [mode, selectRegion])

  // ── region event handlers ─────────────────────────────────────────────────

  const handleRegionDragEnd = useCallback(
    (id: string, e: Konva.KonvaEventObject<DragEvent>) => {
      updateRegion(id, { x: e.target.x(), y: e.target.y() })
    },
    [updateRegion],
  )

  const handleTransformEnd = useCallback(
    (id: string, e: Konva.KonvaEventObject<Event>) => {
      const node = e.target as Konva.Rect
      const sx = node.scaleX()
      const sy = node.scaleY()
      const newW = Math.max(Math.abs(node.width() * sx), 1)
      const newH = Math.max(Math.abs(node.height() * sy), 1)
      // Bake scale into dimensions, reset transform
      node.scaleX(1)
      node.scaleY(1)
      node.width(newW)
      node.height(newH)
      updateRegion(id, { x: node.x(), y: node.y(), width: newW, height: newH })
    },
    [updateRegion],
  )

  // ── type picker ────────────────────────────────────────────────────────────

  const handlePickType = useCallback(
    async (type: RegionType) => {
      if (!typePicker) return
      setTypePicker(null)
      await createRegion({
        type,
        x: typePicker.rect.x,
        y: typePicker.rect.y,
        width: typePicker.rect.w,
        height: typePicker.rect.h,
      })
    },
    [typePicker, createRegion],
  )

  // ── sidebar region deletion ───────────────────────────────────────────────

  const handleDeleteRegion = useCallback(
    (id: string) => deleteRegion(id),
    [deleteRegion],
  )

  // ── mode button helper ────────────────────────────────────────────────────

  const modeBtn = (m: 'pan' | 'draw' | 'select', label: string) => (
    <button
      onClick={() => setMode(m)}
      style={{
        padding: '4px 12px',
        background: mode === m ? '#3b82f6' : '#1e293b',
        color: mode === m ? '#fff' : '#94a3b8',
        border: `1px solid ${mode === m ? '#3b82f6' : '#334155'}`,
        borderRadius: 6,
        cursor: 'pointer',
        fontSize: 12,
        fontFamily: 'inherit',
        fontWeight: mode === m ? 600 : 400,
      }}
    >
      {label}
    </button>
  )

  // ── region counts summary ─────────────────────────────────────────────────

  const regionCountsByType = ANNOTATION_TYPES.map((t) => ({
    ...t,
    count: regions.filter((r) => r.type === t.type).length,
  })).filter((t) => t.count > 0)

  // ── canvas cursor ─────────────────────────────────────────────────────────

  const cursor =
    mode === 'draw' ? (drawState ? 'crosshair' : 'crosshair') : mode === 'pan' ? 'grab' : 'default'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* ── Top bar ── */}
      <div
        style={{
          height: 44,
          background: '#0f172a',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '0 14px',
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: '#f8fafc', marginRight: 4 }}>МПРК</span>
        <span style={{ color: '#334155', fontSize: 13 }}>|</span>
        <span style={{ fontSize: 12, color: '#94a3b8', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {fileName ?? ''}
        </span>

        <div style={{ flex: 1 }} />

        {/* Region counts */}
        {regionCountsByType.map((t) => (
          <span
            key={t.type}
            style={{ fontSize: 11, color: t.color, display: 'flex', alignItems: 'center', gap: 4 }}
          >
            <span style={{ width: 8, height: 8, borderRadius: 2, background: t.color, display: 'inline-block' }} />
            {t.count}
          </span>
        ))}

        <div style={{ width: 1, height: 20, background: '#334155', margin: '0 4px' }} />

        {/* Mode buttons */}
        {modeBtn('pan', 'Pan')}
        {modeBtn('draw', 'Draw')}
        {modeBtn('select', 'Select')}

        {/* Draw type selector (visible in draw mode) */}
        {mode === 'draw' && (
          <select
            value={drawType}
            onChange={(e) => setDrawType(e.target.value as RegionType)}
            style={{
              padding: '3px 6px',
              background: '#1e293b',
              color: '#e2e8f0',
              border: '1px solid #334155',
              borderRadius: 6,
              fontSize: 11,
              fontFamily: 'inherit',
              cursor: 'pointer',
            }}
          >
            {ANNOTATION_TYPES.map((t) => (
              <option key={t.type} value={t.type}>{t.label}</option>
            ))}
          </select>
        )}

        <div style={{ width: 1, height: 20, background: '#334155', margin: '0 4px' }} />

        <button
          onClick={fitToScreen}
          style={{
            padding: '4px 12px',
            background: '#1e293b',
            color: '#94a3b8',
            border: '1px solid #334155',
            borderRadius: 6,
            cursor: 'pointer',
            fontSize: 12,
            fontFamily: 'inherit',
          }}
        >
          Fit
        </button>
      </div>

      {/* ── Main area ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* ── Canvas ── */}
        <div
          ref={containerRef}
          style={{ flex: 1, position: 'relative', overflow: 'hidden', background: '#e2e8f0', cursor }}
        >
          <Stage
            ref={stageRef}
            width={size.w || 1}
            height={size.h || 1}
            x={pos.x}
            y={pos.y}
            scaleX={scale}
            scaleY={scale}
            draggable={mode === 'pan'}
            onWheel={handleWheel}
            onDragEnd={handleDragEnd}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onClick={handleStageClick}
          >
            {/* Background layer */}
            <Layer listening={false}>
              <Rect x={0} y={0} width={pageWidth} height={pageHeight} fill="white" shadowEnabled={false} />
              {bgImage && (
                <KonvaImage image={bgImage} x={0} y={0} width={pageWidth} height={pageHeight} />
              )}
            </Layer>

            {/* Regions layer */}
            <Layer>
              {regions.map((region) => {
                const typeInfo = ANNOTATION_TYPES.find((t) => t.type === region.type)
                const color = typeInfo?.color ?? '#6b7280'
                const isSelected = mode === 'select' && region.id === selectedId
                return (
                  <Fragment key={region.id}>
                    <Rect
                      id={`r-${region.id}`}
                      x={region.x}
                      y={region.y}
                      width={region.width}
                      height={region.height}
                      fill={color + '3f'}
                      stroke={isSelected ? '#fff' : color}
                      strokeWidth={isSelected ? 2.5 : 2}
                      strokeScaleEnabled={false}
                      listening={mode === 'select'}
                      draggable={mode === 'select'}
                      onClick={(e) => {
                        e.cancelBubble = true
                        selectRegion(region.id)
                      }}
                      onDragEnd={(e) => handleRegionDragEnd(region.id, e)}
                      onTransformEnd={(e) => handleTransformEnd(region.id, e)}
                    />
                    <Text
                      x={region.x + 4 / scale}
                      y={region.y + 4 / scale}
                      text={typeInfo?.label ?? region.type}
                      fontSize={11 / scale}
                      fill={color}
                      listening={false}
                      perfectDrawEnabled={false}
                    />
                  </Fragment>
                )
              })}

              {/* Draw preview */}
              {drawState && (
                <Rect
                  x={Math.min(drawState.startX, drawState.curX)}
                  y={Math.min(drawState.startY, drawState.curY)}
                  width={Math.abs(drawState.curX - drawState.startX)}
                  height={Math.abs(drawState.curY - drawState.startY)}
                  fill="rgba(59,130,246,0.12)"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  strokeScaleEnabled={false}
                  dash={[6 / scale, 4 / scale]}
                  listening={false}
                />
              )}

              <Transformer
                ref={transformerRef}
                rotateEnabled={false}
                borderStroke="#3b82f6"
                anchorStroke="#3b82f6"
                anchorFill="#fff"
                anchorSize={8}
              />
            </Layer>
          </Stage>

          {/* Type picker overlay */}
          {typePicker && (
            <div
              style={{
                position: 'absolute',
                left: Math.min(typePicker.screenX, size.w - 210),
                top: Math.min(typePicker.screenY + 6, size.h - 240),
                zIndex: 50,
                background: '#fff',
                border: '1px solid #e2e8f0',
                borderRadius: 10,
                padding: '8px 8px',
                boxShadow: '0 8px 24px rgba(0,0,0,0.14)',
                minWidth: 200,
              }}
            >
              <div style={{ fontSize: 11, color: '#64748b', marginBottom: 6, padding: '0 4px' }}>
                Тип региона:
              </div>
              {ANNOTATION_TYPES.map((t) => (
                <button
                  key={t.type}
                  onClick={() => handlePickType(t.type)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    width: '100%',
                    padding: '6px 8px',
                    border: 'none',
                    borderRadius: 6,
                    background: drawType === t.type ? t.color + '18' : 'transparent',
                    color: '#1e293b',
                    cursor: 'pointer',
                    fontSize: 12,
                    fontFamily: 'inherit',
                    textAlign: 'left',
                  }}
                >
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 2,
                      background: t.color,
                      flexShrink: 0,
                    }}
                  />
                  {t.label}
                </button>
              ))}
              <button
                onClick={() => setTypePicker(null)}
                style={{
                  marginTop: 4,
                  width: '100%',
                  padding: '5px 8px',
                  border: 'none',
                  borderRadius: 6,
                  background: 'transparent',
                  color: '#94a3b8',
                  cursor: 'pointer',
                  fontSize: 11,
                  fontFamily: 'inherit',
                }}
              >
                Отмена
              </button>
            </div>
          )}
        </div>

        {/* ── Sidebar ── */}
        <aside
          style={{
            width: 230,
            background: '#fff',
            borderLeft: '1px solid #e2e8f0',
            display: 'flex',
            flexDirection: 'column',
            flexShrink: 0,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              padding: '10px 14px',
              borderBottom: '1px solid #e2e8f0',
              fontSize: 12,
              fontWeight: 600,
              color: '#1e293b',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <span>Регионы</span>
            <span style={{ fontSize: 11, fontWeight: 400, color: '#94a3b8' }}>
              {regions.length > 0 ? `${regions.length} шт.` : 'нет'}
            </span>
          </div>

          <div style={{ flex: 1, overflowY: 'auto' }}>
            {regions.length === 0 ? (
              <div style={{ padding: '24px 14px', fontSize: 12, color: '#94a3b8', textAlign: 'center' }}>
                Переключитесь в Draw и нарисуйте регион
              </div>
            ) : (
              regions.map((region) => {
                const typeInfo = ANNOTATION_TYPES.find((t) => t.type === region.type)
                const color = typeInfo?.color ?? '#6b7280'
                const isSelected = region.id === selectedId
                return (
                  <div
                    key={region.id}
                    onClick={() => {
                      if (mode !== 'select') setMode('select')
                      selectRegion(region.id)
                    }}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 8,
                      padding: '8px 14px',
                      borderBottom: '1px solid #f1f5f9',
                      background: isSelected ? color + '12' : 'transparent',
                      cursor: 'pointer',
                    }}
                  >
                    <span
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: 2,
                        background: color,
                        flexShrink: 0,
                        marginTop: 2,
                      }}
                    />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 12, color: '#1e293b', fontWeight: isSelected ? 600 : 400 }}>
                        {typeInfo?.label ?? region.type}
                      </div>
                      <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 1 }}>
                        {Math.round(region.x)},{Math.round(region.y)} &nbsp;
                        {Math.round(region.width)}×{Math.round(region.height)}
                      </div>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDeleteRegion(region.id) }}
                      title="Удалить"
                      style={{
                        padding: '2px 5px',
                        background: 'transparent',
                        border: '1px solid #e2e8f0',
                        borderRadius: 4,
                        color: '#94a3b8',
                        cursor: 'pointer',
                        fontSize: 11,
                        flexShrink: 0,
                      }}
                    >
                      ×
                    </button>
                  </div>
                )
              })
            )}
          </div>

          {/* Export button */}
          {regions.length > 0 && (
            <div style={{ padding: '10px 14px', borderTop: '1px solid #e2e8f0' }}>
              <a
                href={`/api/sessions/${useSessionStore.getState().sessionId}/export`}
                target="_blank"
                rel="noreferrer"
                style={{
                  display: 'block',
                  padding: '8px',
                  background: '#3b82f6',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  cursor: 'pointer',
                  fontSize: 12,
                  fontWeight: 500,
                  fontFamily: 'inherit',
                  textAlign: 'center',
                  textDecoration: 'none',
                }}
              >
                Экспорт JSON
              </a>
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}

