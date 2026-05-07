import { useRef, useEffect, useState, useMemo, useCallback } from 'react'
import { Stage, Layer, Rect, Text, Image as KonvaImage } from 'react-konva'
import type Konva from 'konva'
import { useSessionStore } from '../store/session'

export default function MapCanvas() {
  const { pageWidth, pageHeight, shapes, shapesTotal, loading, fileName, svgUrl } = useSessionStore()

  const containerRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<Konva.Stage>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [scale, setScale] = useState(1)
  const [pos, setPos] = useState({ x: 0, y: 0 })
  const [showBboxes, setShowBboxes] = useState(false)
  const [bgImage, setBgImage] = useState<HTMLImageElement | null>(null)

  // Load SVG background image
  useEffect(() => {
    if (!svgUrl) {
      setBgImage(null)
      return
    }
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
    const { w, h } = size
    if (!pageWidth || !pageHeight || !w || !h) return
    const s = Math.min(w / pageWidth, h / pageHeight) * 0.95
    setScale(s)
    setPos({ x: (w - pageWidth * s) / 2, y: (h - pageHeight * s) / 2 })
  }, [pageWidth, pageHeight, size])

  // Auto-fit when document or container first becomes available
  const fittedDoc = useRef<string>('')
  useEffect(() => {
    const key = `${pageWidth}x${pageHeight}x${size.w}x${size.h}`
    if (!pageWidth || !pageHeight || !size.w || fittedDoc.current === key) return
    fittedDoc.current = key
    fitToScreen()
  }, [pageWidth, pageHeight, size, fitToScreen])

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

  // Build Konva bbox elements once per shapes update
  const shapeElements = useMemo(() => {
    const nodes: React.ReactNode[] = []
    for (const s of shapes) {
      if (s.shape_type === 'Group') continue
      const ew = Math.max(s.width, 0.5)
      const eh = Math.max(s.height, 0.5)
      nodes.push(
        <Rect
          key={s.id}
          x={s.x + ew / 2}
          y={s.y + eh / 2}
          width={ew}
          height={eh}
          offsetX={ew / 2}
          offsetY={eh / 2}
          rotation={s.rotation}
          fill="rgba(0,0,0,0.008)"
          stroke={showBboxes ? '#334155' : undefined}
          strokeWidth={showBboxes ? 1 : 0}
          strokeScaleEnabled={false}
          listening={true}
          perfectDrawEnabled={false}
        />,
      )
      if (showBboxes && s.text && s.width > 20) {
        nodes.push(
          <Text
            key={`t${s.id}`}
            x={s.x}
            y={s.y + s.height / 2 - 5}
            width={s.width}
            text={s.text}
            fontSize={10}
            fill="#1e293b"
            align="center"
            listening={false}
            perfectDrawEnabled={false}
          />,
        )
      }
    }
    return nodes
  }, [shapes, showBboxes])

  const progressText =
    loading && shapesTotal > 0
      ? `Загрузка ${shapes.length} / ${shapesTotal}…`
      : loading
        ? 'Загрузка…'
        : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Top bar */}
      <div
        style={{
          height: 44,
          background: '#0f172a',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '0 16px',
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: '#f8fafc' }}>МПРК</span>
        <span style={{ color: '#334155', fontSize: 13 }}>|</span>
        <span style={{ fontSize: 12, color: '#94a3b8', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {fileName ?? ''}
        </span>
        {progressText && (
          <span style={{ fontSize: 11, color: '#60a5fa' }}>{progressText}</span>
        )}
        <div style={{ flex: 1 }} />
        {!loading && shapes.length > 0 && (
          <span style={{ fontSize: 11, color: '#475569' }}>
            {shapes.length.toLocaleString('ru')} объектов
          </span>
        )}
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={showBboxes}
            onChange={(e) => setShowBboxes(e.target.checked)}
            style={{ cursor: 'pointer' }}
          />
          <span style={{ fontSize: 11, color: '#94a3b8', userSelect: 'none' }}>Bbox</span>
        </label>
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
          Fit to screen
        </button>
      </div>

      {/* Canvas */}
      <div
        ref={containerRef}
        style={{ flex: 1, overflow: 'hidden', background: '#e2e8f0', cursor: 'grab' }}
      >
        <Stage
          ref={stageRef}
          width={size.w || 1}
          height={size.h || 1}
          x={pos.x}
          y={pos.y}
          scaleX={scale}
          scaleY={scale}
          draggable
          onWheel={handleWheel}
          onDragEnd={handleDragEnd}
        >
          <Layer>
            {/* Page background */}
            <Rect
              x={0}
              y={0}
              width={pageWidth}
              height={pageHeight}
              fill="white"
              shadowEnabled={false}
              listening={false}
            />
            {/* SVG background image */}
            {bgImage && (
              <KonvaImage
                image={bgImage}
                x={0}
                y={0}
                width={pageWidth}
                height={pageHeight}
                listening={false}
              />
            )}
            {/* Interactive bbox overlay */}
            {shapeElements}
          </Layer>
        </Stage>
      </div>
    </div>
  )
}
