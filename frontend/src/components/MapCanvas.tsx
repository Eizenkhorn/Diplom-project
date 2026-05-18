import { useRef, useEffect, useState, useCallback, Fragment } from 'react'
import { Stage, Layer, Rect, Line, Text, Circle, Transformer } from 'react-konva'
import type Konva from 'konva'
import { useSessionStore } from '../store/session'
import { useMarkupStore } from '../store/markup'
import type { MarkupMode } from '../store/markup'
import { BAND_TYPES, MARK_SUBTYPES } from '../types'
import type { BandType } from '../types'
import EditPanel from './EditPanel'
import { createSession } from '../api'

// ── local types ────────────────────────────────────────────────────────────────

interface StationPopup {
  docX: number
  screenX: number
  screenY: number
}

// ── mode hint text ─────────────────────────────────────────────────────────────

function modeHint(
  mode: MarkupMode,
  pendingCount: number,
  activeBandType: BandType | null,
  activeMarkSubtype: string | null,
): string {
  if (mode === 'pan') return ''
  if (mode === 'mark-work-area') {
    return pendingCount === 0
      ? 'Кликните начало рабочей области'
      : 'Кликните конец рабочей области'
  }
  if (mode === 'mark-band') {
    const label = BAND_TYPES.find((b) => b.type === activeBandType)?.label ?? ''
    return pendingCount === 0
      ? `Кликните верхнюю границу — ${label}`
      : `Кликните нижнюю границу — ${label}`
  }
  if (mode === 'mark-station') return 'Кликните позицию станции'
  if (mode === 'mark-mark') {
    const label = MARK_SUBTYPES.find((m) => m.subtype === activeMarkSubtype)?.label ?? ''
    return `Кликните позицию — ${label}`
  }
  return ''
}

// ── toolbar button ─────────────────────────────────────────────────────────────

function TBtn({
  active, color, title, short, onClick,
}: {
  active: boolean
  color?: string
  title: string
  short: string
  onClick: () => void
}) {
  const bg = active ? (color ?? '#3b82f6') : '#1e293b'
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        padding: '3px 8px',
        background: bg,
        color: active ? '#fff' : '#94a3b8',
        border: `1px solid ${active ? (color ?? '#3b82f6') : '#334155'}`,
        borderRadius: 5,
        cursor: 'pointer',
        fontSize: 11,
        fontFamily: 'inherit',
        fontWeight: active ? 600 : 400,
        whiteSpace: 'nowrap',
        flexShrink: 0,
      }}
    >
      {short}
    </button>
  )
}

// ── main component ─────────────────────────────────────────────────────────────

export default function MapCanvas() {
  const { pageWidth, pageHeight, svgUrl, fileName, sessionId, setSession } = useSessionStore()
  const {
    mode, activeBandType, activeMarkSubtype, pendingClicks,
    workArea, bands, stations, marks, selectedId,
    setMode, addPendingClick, cancel, setSelected,
    saveWorkArea, createBand, createStation, createMark,
    deleteBand, deleteStation, deleteMark,
    loadMarkup, reset: resetMarkup,
  } = useMarkupStore()

  // ── canvas state ─────────────────────────────────────────────────────────────
  const containerRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<Konva.Stage>(null)
  const imgRef = useRef<HTMLImageElement>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [scale, setScale] = useState(1)
  const [pos, setPos] = useState({ x: 0, y: 0 })
  const [mouseDocPos, setMouseDocPos] = useState<{ x: number; y: number } | null>(null)
  const [stationPopup, setStationPopup] = useState<StationPopup | null>(null)
  const [stationName, setStationName] = useState('')
  // local state for mark subtype selector in toolbar (persists across mode changes)
  const [markSubtypeSelect, setMarkSubtypeSelect] = useState(MARK_SUBTYPES[0].subtype)
  const [showEditPanel, setShowEditPanel] = useState(false)
  // ── file re-open ─────────────────────────────────────────────────────────────
  const newFileInputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const handleNewFile = useCallback(async (file: File) => {
    setUploading(true)
    setUploadError(null)
    try {
      const meta = await createSession(file)
      resetMarkup()
      setSession(meta.session_id, meta.page_width, meta.page_height, file.name, meta.svg_url)
      await loadMarkup(meta.session_id)
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : String(e))
    } finally {
      setUploading(false)
    }
  }, [setSession, loadMarkup, resetMarkup])

  // km hints for coordinate_ruler band — use refs so click handler always sees fresh values
  const kmHintStartRef = useRef('')
  const kmHintEndRef = useRef('')
  const [kmHintStart, setKmHintStart] = useState('')
  const [kmHintEnd, setKmHintEnd] = useState('')

  // ── resize observer ──────────────────────────────────────────────────────────
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      setSize({ w: entry.contentRect.width, h: entry.contentRect.height })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // ── SVG background transform sync ────────────────────────────────────────────
  const applyImgTransform = useCallback((x: number, y: number, s: number) => {
    const img = imgRef.current
    if (!img) return
    img.style.transform = `translate(${x}px, ${y}px) scale(${s})`
  }, [])

  useEffect(() => {
    applyImgTransform(pos.x, pos.y, scale)
  }, [pos.x, pos.y, scale, svgUrl, applyImgTransform])

  const navigateToDocX = useCallback((docX: number) => {
    const newX = size.w / 2 - docX * scale
    setPos((prev) => {
      applyImgTransform(newX, prev.y, scale)
      return { x: newX, y: prev.y }
    })
  }, [size.w, scale, applyImgTransform])

  // ── fit to screen ────────────────────────────────────────────────────────────
  const fitToScreen = useCallback(() => {
    if (!pageWidth || !pageHeight || !size.w || !size.h) return
    const s = Math.min(size.w / pageWidth, size.h / pageHeight) * 0.95
    const x = (size.w - pageWidth * s) / 2
    const y = (size.h - pageHeight * s) / 2
    setScale(s)
    setPos({ x, y })
    applyImgTransform(x, y, s)
  }, [pageWidth, pageHeight, size, applyImgTransform])

  const fittedKey = useRef('')
  useEffect(() => {
    const key = `${pageWidth}x${pageHeight}x${size.w}x${size.h}`
    if (!pageWidth || !pageHeight || !size.w || fittedKey.current === key) return
    fittedKey.current = key
    fitToScreen()
  }, [pageWidth, pageHeight, size, fitToScreen])

  // ── ESC cancels current mode ─────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        cancel()
        setStationPopup(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [cancel])

  // ── close station popup when mode changes away from mark-station ─────────────
  useEffect(() => {
    if (mode !== 'mark-station') setStationPopup(null)
  }, [mode])

  // ── stage event handlers ─────────────────────────────────────────────────────

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
    applyImgTransform(newX, newY, newScale)
  }, [applyImgTransform])

  const handleDragMove = useCallback((e: Konva.KonvaEventObject<DragEvent>) => {
    applyImgTransform(e.target.x(), e.target.y(), (e.target as Konva.Stage).scaleX())
  }, [applyImgTransform])

  const handleDragEnd = useCallback((e: Konva.KonvaEventObject<DragEvent>) => {
    const x = e.target.x()
    const y = e.target.y()
    setPos({ x, y })
    applyImgTransform(x, y, (e.target as Konva.Stage).scaleX())
  }, [applyImgTransform])

  const handleMouseMoveStage = useCallback((e: Konva.KonvaEventObject<MouseEvent>) => {
    const stage = stageRef.current
    if (!stage) return
    const p = stage.getRelativePointerPosition()
    if (p) setMouseDocPos(p)
  }, [])

  const handleMouseLeaveStage = useCallback(() => setMouseDocPos(null), [])

  const handleStageClick = useCallback((e: Konva.KonvaEventObject<MouseEvent>) => {
    const { mode, pendingClicks, activeBandType, activeMarkSubtype } =
      useMarkupStore.getState()
    if (mode === 'pan') return

    const stage = stageRef.current
    if (!stage) return
    const p = stage.getRelativePointerPosition()
    if (!p) return

    if (mode === 'mark-work-area') {
      if (pendingClicks.length === 0) {
        useMarkupStore.getState().addPendingClick(p)
      } else {
        const x1 = pendingClicks[0].x
        useMarkupStore.getState().saveWorkArea({
          x_start: Math.min(x1, p.x),
          x_end: Math.max(x1, p.x),
        })
      }
    } else if (mode === 'mark-band') {
      if (pendingClicks.length === 0) {
        useMarkupStore.getState().addPendingClick(p)
      } else {
        const y1 = pendingClicks[0].y
        const bandData: { type: BandType; y_top: number; y_bottom: number; km_hint_start?: number; km_hint_end?: number } = {
          type: activeBandType!,
          y_top: Math.min(y1, p.y),
          y_bottom: Math.max(y1, p.y),
        }
        if (activeBandType === 'coordinate_ruler') {
          const hs = parseInt(kmHintStartRef.current)
          const he = parseInt(kmHintEndRef.current)
          if (!isNaN(hs)) bandData.km_hint_start = hs
          if (!isNaN(he)) bandData.km_hint_end = he
        }
        useMarkupStore.getState().createBand(bandData)
      }
    } else if (mode === 'mark-station') {
      const screenPos = stage.getPointerPosition()!
      setStationPopup({ docX: p.x, screenX: screenPos.x, screenY: screenPos.y })
      setStationName('')
    } else if (mode === 'mark-mark') {
      useMarkupStore.getState().createMark({ x: p.x, y: p.y, subtype: activeMarkSubtype! })
    }
  }, [])

  // ── station popup confirm ────────────────────────────────────────────────────
  const confirmStation = useCallback(() => {
    if (!stationPopup || !stationName.trim()) return
    createStation({ x: stationPopup.docX, name: stationName.trim() })
    setStationPopup(null)
    setStationName('')
  }, [stationPopup, stationName, createStation])

  // ── cursor ───────────────────────────────────────────────────────────────────
  const cursor = mode === 'pan' ? 'grab' : 'crosshair'

  // ── ghost line geometry ───────────────────────────────────────────────────────
  const ghostX = mouseDocPos?.x ?? 0
  const ghostY = mouseDocPos?.y ?? 0
  const bandAreaX0 = workArea?.x_start ?? 0
  const bandAreaX1 = workArea?.x_end ?? pageWidth

  // active band color for ghost
  const activeBandColor = BAND_TYPES.find((b) => b.type === activeBandType)?.color ?? '#6b7280'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>

      {/* ── Top bar ── */}
      <div style={{
        height: 40,
        background: '#0f172a',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '0 14px',
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: '#f8fafc', marginRight: 4 }}>МПРК</span>
        <span style={{ color: '#334155', fontSize: 13 }}>|</span>
        <span style={{ fontSize: 12, color: '#94a3b8', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {fileName || ''}
        </span>
        <div style={{ flex: 1 }} />
        {uploadError && (
          <span style={{ fontSize: 11, color: '#f87171', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {uploadError}
          </span>
        )}
        <button
          onClick={fitToScreen}
          style={{ padding: '3px 10px', background: '#1e293b', color: '#94a3b8', border: '1px solid #334155', borderRadius: 5, cursor: 'pointer', fontSize: 11, fontFamily: 'inherit' }}
        >
          Fit
        </button>
        <button
          onClick={() => newFileInputRef.current?.click()}
          disabled={uploading}
          title="Открыть другую режимную карту"
          style={{
            padding: '3px 10px',
            background: uploading ? '#334155' : '#1e293b',
            color: uploading ? '#64748b' : '#94a3b8',
            border: '1px solid #334155',
            borderRadius: 5, cursor: uploading ? 'wait' : 'pointer',
            fontSize: 11, fontFamily: 'inherit',
          }}
        >
          {uploading ? 'Загрузка…' : 'Открыть файл'}
        </button>
        <input
          ref={newFileInputRef}
          type="file"
          accept=".vsdx,.vsd"
          style={{ display: 'none' }}
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) handleNewFile(file)
            e.target.value = ''
          }}
        />
      </div>

      {/* ── Markup toolbar ── */}
      <div style={{
        height: 40,
        background: '#1e293b',
        borderBottom: '1px solid #0f172a',
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        padding: '0 10px',
        flexShrink: 0,
        overflow: 'hidden',
      }}>
        {/* Pan */}
        <TBtn active={mode === 'pan'} title="Навигация (перемещение и зум)" short="Pan"
          onClick={() => setMode('pan')} />

        <div style={{ width: 1, height: 20, background: '#334155', flexShrink: 0 }} />

        {/* Work area */}
        <TBtn active={mode === 'mark-work-area'} color="#6b7280"
          title="Рабочая область: два клика по X — начало и конец"
          short="Раб. зона"
          onClick={() => setMode('mark-work-area')} />

        <div style={{ width: 1, height: 20, background: '#334155', flexShrink: 0 }} />

        {/* Band type buttons */}
        {BAND_TYPES.map((bt) => (
          <TBtn
            key={bt.type}
            active={mode === 'mark-band' && activeBandType === bt.type}
            color={bt.color}
            title={bt.label + ': два клика по Y — верх и низ полосы'}
            short={bandShort(bt.type)}
            onClick={() => setMode('mark-band', bt.type as BandType)}
          />
        ))}

        {/* KM hints for coordinate_ruler band */}
        {mode === 'mark-band' && activeBandType === 'coordinate_ruler' && (
          <>
            <div style={{ width: 1, height: 20, background: '#334155', flexShrink: 0 }} />
            <span style={{ fontSize: 10, color: '#94a3b8', flexShrink: 0 }}>от км:</span>
            <input
              type="number"
              value={kmHintStart}
              onChange={(e) => { setKmHintStart(e.target.value); kmHintStartRef.current = e.target.value }}
              placeholder="—"
              style={{
                width: 56, padding: '2px 4px', background: '#0f172a', color: '#e2e8f0',
                border: '1px solid #334155', borderRadius: 4, fontSize: 11,
                fontFamily: 'inherit', flexShrink: 0,
              }}
            />
            <span style={{ fontSize: 10, color: '#94a3b8', flexShrink: 0 }}>до км:</span>
            <input
              type="number"
              value={kmHintEnd}
              onChange={(e) => { setKmHintEnd(e.target.value); kmHintEndRef.current = e.target.value }}
              placeholder="—"
              style={{
                width: 56, padding: '2px 4px', background: '#0f172a', color: '#e2e8f0',
                border: '1px solid #334155', borderRadius: 4, fontSize: 11,
                fontFamily: 'inherit', flexShrink: 0,
              }}
            />
          </>
        )}

        <div style={{ width: 1, height: 20, background: '#334155', flexShrink: 0 }} />

        {/* Station */}
        <TBtn active={mode === 'mark-station'} color="#3b82f6"
          title="Станция: один клик — позиция, затем ввод имени"
          short="Станция"
          onClick={() => setMode('mark-station')} />

        <div style={{ width: 1, height: 20, background: '#334155', flexShrink: 0 }} />

        {/* Mark + subtype selector */}
        <TBtn
          active={mode === 'mark-mark'}
          color={MARK_SUBTYPES.find((m) => m.subtype === markSubtypeSelect)?.color}
          title="Метка: выберите подтип и кликните на карте"
          short="Метка"
          onClick={() => setMode('mark-mark', undefined, markSubtypeSelect)}
        />
        <select
          value={markSubtypeSelect}
          onChange={(e) => {
            setMarkSubtypeSelect(e.target.value)
            if (mode === 'mark-mark') setMode('mark-mark', undefined, e.target.value)
          }}
          style={{
            padding: '2px 4px', background: '#0f172a', color: '#e2e8f0',
            border: '1px solid #334155', borderRadius: 4, fontSize: 10,
            fontFamily: 'inherit', cursor: 'pointer', flexShrink: 0, maxWidth: 130,
          }}
        >
          {MARK_SUBTYPES.map((m) => (
            <option key={m.subtype} value={m.subtype}>{m.label}</option>
          ))}
        </select>

        {/* Spacer + mode hint */}
        <div style={{ flex: 1 }} />
        {mode !== 'pan' && (
          <span style={{
            fontSize: 11, color: '#94a3b8', whiteSpace: 'nowrap',
            overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 320,
          }}>
            {modeHint(mode, pendingClicks.length, activeBandType, activeMarkSubtype)}
          </span>
        )}
        <div style={{ flex: 1 }} />

        {/* Cancel */}
        {mode !== 'pan' && (
          <button
            onClick={() => { cancel(); setStationPopup(null) }}
            style={{
              padding: '3px 8px', background: 'transparent', color: '#f87171',
              border: '1px solid #ef4444', borderRadius: 5, cursor: 'pointer',
              fontSize: 11, fontFamily: 'inherit', flexShrink: 0,
            }}
          >
            ✕ Отмена
          </button>
        )}
      </div>

      {/* ── Combined extract + edit panel modal ── */}
      {showEditPanel && sessionId && (
        <EditPanel
          sessionId={sessionId}
          onClose={() => setShowEditPanel(false)}
          onNavigate={navigateToDocX}
        />
      )}

      {/* ── Main area ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* ── Canvas ── */}
        <div
          ref={containerRef}
          style={{ flex: 1, position: 'relative', overflow: 'hidden', background: '#e2e8f0', cursor }}
        >
          {/* SVG background */}
          {svgUrl && (
            <img
              ref={imgRef}
              src={svgUrl}
              width={pageWidth}
              height={pageHeight}
              style={{
                position: 'absolute', top: 0, left: 0,
                transformOrigin: '0 0', willChange: 'transform',
                userSelect: 'none', pointerEvents: 'none',
              }}
              alt=""
            />
          )}

          <Stage
            ref={stageRef}
            style={{ position: 'absolute', top: 0, left: 0 }}
            width={size.w || 1}
            height={size.h || 1}
            x={pos.x}
            y={pos.y}
            scaleX={scale}
            scaleY={scale}
            draggable={mode === 'pan'}
            onWheel={handleWheel}
            onDragMove={handleDragMove}
            onDragEnd={handleDragEnd}
            onMouseMove={handleMouseMoveStage}
            onMouseLeave={handleMouseLeaveStage}
            onClick={handleStageClick}
          >
            {/* ── Markup visualization layer ── */}
            <Layer listening={false}>
              {/* WorkArea boundary lines */}
              {workArea && (
                <>
                  <Line
                    points={[workArea.x_start, 0, workArea.x_start, pageHeight]}
                    stroke="#94a3b8" strokeWidth={1.5 / scale} dash={[8 / scale, 4 / scale]}
                    strokeScaleEnabled={false}
                  />
                  <Line
                    points={[workArea.x_end, 0, workArea.x_end, pageHeight]}
                    stroke="#94a3b8" strokeWidth={1.5 / scale} dash={[8 / scale, 4 / scale]}
                    strokeScaleEnabled={false}
                  />
                </>
              )}

              {/* Bands */}
              {bands.map((band) => {
                const info = BAND_TYPES.find((b) => b.type === band.type)
                const color = info?.color ?? '#6b7280'
                const x = workArea?.x_start ?? 0
                const w = workArea ? workArea.x_end - workArea.x_start : pageWidth
                const isSelected = band.id === selectedId
                return (
                  <Fragment key={band.id}>
                    <Rect
                      x={x} y={band.y_top} width={w} height={band.y_bottom - band.y_top}
                      fill={color + '28'}
                      stroke={color}
                      strokeWidth={isSelected ? 2.5 / scale : 1.5 / scale}
                      strokeScaleEnabled={false}
                    />
                    <Text
                      x={x + 5 / scale} y={band.y_top + 4 / scale}
                      text={info?.label ?? band.type}
                      fontSize={11 / scale} fill={color}
                      perfectDrawEnabled={false}
                    />
                  </Fragment>
                )
              })}

              {/* Stations */}
              {stations.map((st) => {
                const isSelected = st.id === selectedId
                return (
                  <Fragment key={st.id}>
                    <Line
                      points={[st.x, 0, st.x, pageHeight]}
                      stroke={isSelected ? '#60a5fa' : '#3b82f6'}
                      strokeWidth={isSelected ? 2 / scale : 1.5 / scale}
                      strokeScaleEnabled={false}
                      dash={[6 / scale, 3 / scale]}
                    />
                    <Text
                      x={st.x + 3 / scale} y={6 / scale}
                      text={st.name}
                      fontSize={10 / scale} fill="#3b82f6"
                      perfectDrawEnabled={false}
                    />
                  </Fragment>
                )
              })}

              {/* Marks */}
              {marks.map((mk) => {
                const info = MARK_SUBTYPES.find((m) => m.subtype === mk.subtype)
                const color = info?.color ?? '#6b7280'
                const isSelected = mk.id === selectedId
                return (
                  <Fragment key={mk.id}>
                    <Circle
                      x={mk.x} y={mk.y}
                      radius={isSelected ? 7 / scale : 5 / scale}
                      fill={color}
                      strokeScaleEnabled={false}
                    />
                    <Text
                      x={mk.x + 8 / scale} y={mk.y - 5 / scale}
                      text={info?.label ?? mk.subtype}
                      fontSize={9 / scale} fill={color}
                      perfectDrawEnabled={false}
                    />
                  </Fragment>
                )
              })}

              {/* First-click marker (2-click modes) */}
              {pendingClicks.length > 0 && mode === 'mark-work-area' && (
                <Line
                  points={[pendingClicks[0].x, 0, pendingClicks[0].x, pageHeight]}
                  stroke="#94a3b8" strokeWidth={2 / scale}
                  strokeScaleEnabled={false}
                />
              )}
              {pendingClicks.length > 0 && mode === 'mark-band' && (
                <Line
                  points={[bandAreaX0, pendingClicks[0].y, bandAreaX1, pendingClicks[0].y]}
                  stroke={activeBandColor} strokeWidth={2 / scale}
                  strokeScaleEnabled={false}
                />
              )}
            </Layer>

            {/* ── Ghost cursor layer ── */}
            {mouseDocPos && mode !== 'pan' && (
              <Layer listening={false}>
                {(mode === 'mark-work-area') && (
                  <Line
                    points={[ghostX, 0, ghostX, pageHeight]}
                    stroke="#94a3b8" strokeWidth={1 / scale} opacity={0.6}
                    dash={[5 / scale, 4 / scale]} strokeScaleEnabled={false}
                  />
                )}
                {(mode === 'mark-station') && (
                  <Line
                    points={[ghostX, 0, ghostX, pageHeight]}
                    stroke="#3b82f6" strokeWidth={1 / scale} opacity={0.5}
                    dash={[5 / scale, 4 / scale]} strokeScaleEnabled={false}
                  />
                )}
                {mode === 'mark-band' && (
                  <Line
                    points={[bandAreaX0, ghostY, bandAreaX1, ghostY]}
                    stroke={activeBandColor} strokeWidth={1 / scale} opacity={0.6}
                    dash={[5 / scale, 4 / scale]} strokeScaleEnabled={false}
                  />
                )}
                {mode === 'mark-mark' && (
                  <>
                    <Line
                      points={[ghostX - 8 / scale, ghostY, ghostX + 8 / scale, ghostY]}
                      stroke={MARK_SUBTYPES.find((m) => m.subtype === activeMarkSubtype)?.color ?? '#6b7280'}
                      strokeWidth={1 / scale} opacity={0.7} strokeScaleEnabled={false}
                    />
                    <Line
                      points={[ghostX, ghostY - 8 / scale, ghostX, ghostY + 8 / scale]}
                      stroke={MARK_SUBTYPES.find((m) => m.subtype === activeMarkSubtype)?.color ?? '#6b7280'}
                      strokeWidth={1 / scale} opacity={0.7} strokeScaleEnabled={false}
                    />
                  </>
                )}
              </Layer>
            )}
          </Stage>

          {/* Station name popup */}
          {stationPopup && (
            <div
              style={{
                position: 'absolute',
                left: Math.min(stationPopup.screenX + 8, size.w - 220),
                top: Math.min(stationPopup.screenY + 8, size.h - 90),
                zIndex: 50,
                background: '#fff',
                border: '1px solid #e2e8f0',
                borderRadius: 8,
                padding: '10px 12px',
                boxShadow: '0 6px 20px rgba(0,0,0,0.12)',
                minWidth: 210,
              }}
            >
              <div style={{ fontSize: 11, color: '#64748b', marginBottom: 6 }}>Название станции:</div>
              <input
                autoFocus
                value={stationName}
                onChange={(e) => setStationName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') confirmStation()
                  if (e.key === 'Escape') { setStationPopup(null); cancel() }
                }}
                placeholder="Введите название..."
                style={{
                  width: '100%', padding: '5px 8px', border: '1px solid #cbd5e1',
                  borderRadius: 5, fontSize: 12, fontFamily: 'inherit',
                  outline: 'none', boxSizing: 'border-box',
                }}
              />
              <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                <button
                  onClick={confirmStation}
                  disabled={!stationName.trim()}
                  style={{
                    flex: 1, padding: '5px', background: stationName.trim() ? '#3b82f6' : '#94a3b8',
                    color: '#fff', border: 'none', borderRadius: 5,
                    cursor: stationName.trim() ? 'pointer' : 'default', fontSize: 11, fontFamily: 'inherit',
                  }}
                >
                  Добавить
                </button>
                <button
                  onClick={() => { setStationPopup(null); cancel() }}
                  style={{
                    padding: '5px 10px', background: 'transparent', color: '#64748b',
                    border: '1px solid #e2e8f0', borderRadius: 5, cursor: 'pointer',
                    fontSize: 11, fontFamily: 'inherit',
                  }}
                >
                  Отмена
                </button>
              </div>
            </div>
          )}
        </div>

        {/* ── Sidebar ── */}
        <aside style={{
          width: 240,
          background: '#fff',
          borderLeft: '1px solid #e2e8f0',
          display: 'flex',
          flexDirection: 'column',
          flexShrink: 0,
          overflow: 'hidden',
        }}>
          <div style={{
            padding: '10px 14px', borderBottom: '1px solid #e2e8f0',
            fontSize: 12, fontWeight: 600, color: '#1e293b', flexShrink: 0,
          }}>
            Разметка
          </div>

          <div style={{ flex: 1, overflowY: 'auto' }}>

            {/* Work area */}
            <SideSection label="Рабочая область">
              {workArea ? (
                <SideRow
                  color="#6b7280"
                  label={`${Math.round(workArea.x_start)} — ${Math.round(workArea.x_end)} px`}
                  onDelete={() => {
                    // clear work area by saving a dummy that backend won't validate — instead
                    // just set workArea locally since backend has no DELETE work-area endpoint
                    useMarkupStore.setState({ workArea: null })
                  }}
                />
              ) : (
                <EmptyHint>Нажмите «Раб. зона» и кликните дважды</EmptyHint>
              )}
            </SideSection>

            {/* Bands */}
            <SideSection label={`Полосы (${bands.length})`}>
              {bands.length === 0
                ? <EmptyHint>Кнопки Скорости/Профиль/… → два клика по Y</EmptyHint>
                : bands.map((band) => {
                  const info = BAND_TYPES.find((b) => b.type === band.type)
                  return (
                    <SideRow
                      key={band.id}
                      color={info?.color ?? '#6b7280'}
                      label={info?.label ?? band.type}
                      sub={`y: ${Math.round(band.y_top)}–${Math.round(band.y_bottom)}`}
                      hint={band.is_informational ? 'не извлекает данные, для ориентации' : undefined}
                      selected={band.id === selectedId}
                      onClick={() => setSelected(band.id === selectedId ? null : band.id)}
                      onDelete={() => deleteBand(band.id)}
                    />
                  )
                })}
            </SideSection>

            {/* Stations */}
            <SideSection label={`Станции (${stations.length})`}>
              {stations.length === 0
                ? <EmptyHint>Нажмите «Станция» и кликните на карте</EmptyHint>
                : stations.map((st) => (
                  <SideRow
                    key={st.id}
                    color="#3b82f6"
                    label={st.name}
                    sub={`x: ${Math.round(st.x)}`}
                    selected={st.id === selectedId}
                    onClick={() => setSelected(st.id === selectedId ? null : st.id)}
                    onDelete={() => deleteStation(st.id)}
                  />
                ))}
            </SideSection>

            {/* Marks */}
            <SideSection label={`Метки (${marks.length})`}>
              {marks.length === 0
                ? <EmptyHint>Нажмите «Метка», выберите подтип и кликните</EmptyHint>
                : marks.map((mk) => {
                  const info = MARK_SUBTYPES.find((m) => m.subtype === mk.subtype)
                  return (
                    <SideRow
                      key={mk.id}
                      color={info?.color ?? '#6b7280'}
                      label={info?.label ?? mk.subtype}
                      sub={`x:${Math.round(mk.x)} y:${Math.round(mk.y)}`}
                      selected={mk.id === selectedId}
                      onClick={() => setSelected(mk.id === selectedId ? null : mk.id)}
                      onDelete={() => deleteMark(mk.id)}
                    />
                  )
                })}
            </SideSection>
          </div>

          {/* Export */}
          <div style={{ padding: '10px 14px', borderTop: '1px solid #e2e8f0', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
            <button
              onClick={() => setShowEditPanel(true)}
              style={{
                display: 'block', width: '100%', padding: '8px', background: '#10b981', color: '#fff',
                border: 'none', borderRadius: 6, fontSize: 12, fontWeight: 500, fontFamily: 'inherit',
                textAlign: 'center', cursor: 'pointer',
              }}
            >
              Извлечь и редактировать…
            </button>
            <a
              href={`/api/sessions/${sessionId}/export`}
              target="_blank"
              rel="noreferrer"
              style={{
                display: 'block', padding: '8px', background: '#3b82f6', color: '#fff',
                borderRadius: 6, fontSize: 12, fontWeight: 500, fontFamily: 'inherit',
                textAlign: 'center', textDecoration: 'none',
              }}
            >
              Скачать JSON
            </a>
          </div>
        </aside>
      </div>
    </div>
  )
}

// ── band short labels for toolbar buttons ──────────────────────────────────────

function bandShort(type: BandType): string {
  const map: Record<BandType, string> = {
    speed_limits:     'Скорости',
    profile:          'Профиль',
    track_plan:       'План',
    traction_modes:   'Тяга',
    coordinate_ruler: 'КШ',
    path_schema:      'Схема',
  }
  return map[type]
}

// ── small sidebar helpers ──────────────────────────────────────────────────────

function SideSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ borderBottom: '1px solid #f1f5f9' }}>
      <div style={{
        padding: '6px 14px 4px',
        fontSize: 10, fontWeight: 700, color: '#94a3b8',
        textTransform: 'uppercase', letterSpacing: '0.05em',
      }}>
        {label}
      </div>
      {children}
    </div>
  )
}

function EmptyHint({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ padding: '6px 14px 10px', fontSize: 11, color: '#cbd5e1' }}>
      {children}
    </div>
  )
}

function SideRow({
  color, label, sub, hint, selected, onClick, onDelete,
}: {
  color: string
  label: string
  sub?: string
  hint?: string
  selected?: boolean
  onClick?: () => void
  onDelete: () => void
}) {
  return (
    <div
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '6px 14px',
        background: selected ? color + '14' : 'transparent',
        cursor: onClick ? 'pointer' : 'default',
      }}
    >
      <span style={{ width: 8, height: 8, borderRadius: 2, background: color, flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 11, color: '#1e293b', fontWeight: selected ? 600 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {label}
        </div>
        {sub && (
          <div style={{ fontSize: 10, color: '#94a3b8' }}>{sub}</div>
        )}
        {hint && (
          <div style={{ fontSize: 10, color: '#f59e0b', display: 'flex', alignItems: 'center', gap: 3, marginTop: 1 }}>
            <span style={{ fontWeight: 700, fontSize: 11 }}>ⓘ</span>
            {hint}
          </div>
        )}
      </div>
      <button
        onClick={(e) => { e.stopPropagation(); onDelete() }}
        title="Удалить"
        style={{
          padding: '1px 5px', background: 'transparent', border: '1px solid #e2e8f0',
          borderRadius: 3, color: '#94a3b8', cursor: 'pointer', fontSize: 11, flexShrink: 0,
        }}
      >
        ×
      </button>
    </div>
  )
}
