import { useRef, useEffect, useState, useCallback } from 'react'
import { Stage, Layer, Shape, Rect } from 'react-konva'
import type Konva from 'konva'
import { useAppStore } from '../store'

const ANNOTATION_COLORS: Record<string, string> = {
  station: '#10b981',
  profile_segment: '#f59e0b',
  speed_limit: '#ef4444',
  coordinate_ruler: '#8b5cf6',
}

export default function DiagramCanvas() {
  const containerRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<Konva.Stage>(null)
  const [containerSize, setContainerSize] = useState({ w: 0, h: 0 })
  const [stagePos, setStagePos] = useState({ x: 0, y: 0 })
  const [stageScale, setStageScale] = useState(1)
  const [isDragging, setIsDragging] = useState(false)

  const doc = useAppStore((s) => s.doc)
  const selectedId = useAppStore((s) => s.selectedShapeId)
  const annotations = useAppStore((s) => s.annotations)
  const selectShape = useAppStore((s) => s.selectShape)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setContainerSize({ w: width, h: height })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Fit document to container on first load
  const fitted = useRef(false)
  useEffect(() => {
    fitted.current = false
  }, [doc])

  useEffect(() => {
    if (!doc || containerSize.w === 0 || containerSize.h === 0) return
    if (fitted.current) return
    fitted.current = true
    const scale =
      Math.min(containerSize.w / doc.page_width, containerSize.h / doc.page_height) * 0.95
    setStageScale(scale)
    setStagePos({
      x: (containerSize.w - doc.page_width * scale) / 2,
      y: (containerSize.h - doc.page_height * scale) / 2,
    })
  }, [doc, containerSize])

  const handleWheel = useCallback((e: Konva.KonvaEventObject<WheelEvent>) => {
    e.evt.preventDefault()
    const stage = stageRef.current
    if (!stage) return
    const pointer = stage.getPointerPosition()
    if (!pointer) return
    const oldScale = stage.scaleX()
    const factor = e.evt.deltaY < 0 ? 1.15 : 1 / 1.15
    const newScale = Math.max(0.01, Math.min(10, oldScale * factor))
    const docX = (pointer.x - stage.x()) / oldScale
    const docY = (pointer.y - stage.y()) / oldScale
    setStageScale(newScale)
    setStagePos({
      x: pointer.x - docX * newScale,
      y: pointer.y - docY * newScale,
    })
  }, [])

  const handleDragEnd = useCallback((e: Konva.KonvaEventObject<DragEvent>) => {
    setStagePos({ x: e.target.x(), y: e.target.y() })
    setIsDragging(false)
  }, [])

  const handleClick = useCallback(
    (e: Konva.KonvaEventObject<MouseEvent>) => {
      if (!doc) return
      const stage = stageRef.current
      if (!stage) return
      const pointer = stage.getPointerPosition()
      if (!pointer) return
      const scale = stage.scaleX()
      const docX = (pointer.x - stage.x()) / scale
      const docY = (pointer.y - stage.y()) / scale

      for (let i = doc.shapes.length - 1; i >= 0; i--) {
        const s = doc.shapes[i]
        if (s.shape_type === 'Group') continue
        const hw = Math.max(s.width, 6) / 2
        const hh = Math.max(s.height, 6) / 2
        if (
          Math.abs(docX - (s.x + s.width / 2)) <= hw &&
          Math.abs(docY - (s.y + s.height / 2)) <= hh
        ) {
          selectShape(s.id)
          return
        }
      }
      selectShape(null)
    },
    [doc, selectShape],
  )

  if (!doc) {
    return (
      <div
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#94a3b8',
          fontSize: 14,
          background: '#f8fafc',
          userSelect: 'none',
        }}
      >
        Загрузите файл .vsdx чтобы начать разметку
      </div>
    )
  }

  const { w, h } = containerSize
  // Visible region in document space (with margin for partially-visible shapes)
  const pad = 300
  const visX1 = (-stagePos.x) / stageScale - pad
  const visY1 = (-stagePos.y) / stageScale - pad
  const visX2 = visX1 + w / stageScale + pad * 2
  const visY2 = visY1 + h / stageScale + pad * 2

  const highlightedIds = new Set([
    ...(selectedId ? [selectedId] : []),
    ...Object.keys(annotations),
  ])

  return (
    <div
      ref={containerRef}
      style={{
        flex: 1,
        overflow: 'hidden',
        background: '#e2e8f0',
        cursor: isDragging ? 'grabbing' : 'grab',
      }}
    >
      <Stage
        ref={stageRef}
        width={w || 800}
        height={h || 500}
        x={stagePos.x}
        y={stagePos.y}
        scaleX={stageScale}
        scaleY={stageScale}
        draggable
        onWheel={handleWheel}
        onDragStart={() => setIsDragging(true)}
        onDragEnd={handleDragEnd}
        onClick={handleClick}
      >
        {/* Page background */}
        <Layer listening={false}>
          <Rect
            x={0}
            y={0}
            width={doc.page_width}
            height={doc.page_height}
            fill="white"
            shadowEnabled={false}
          />
        </Layer>

        {/* All non-highlighted shapes — single canvas pass for performance */}
        <Layer listening={false}>
          <Shape
            sceneFunc={(ctx: any) => {
              // Access native canvas context directly for custom batch drawing
              const c: CanvasRenderingContext2D = ctx._context
              c.strokeStyle = '#94a3b8'
              c.lineWidth = 1

              for (const s of doc.shapes) {
                if (s.shape_type === 'Group') continue
                if (highlightedIds.has(s.id)) continue
                // Viewport culling — skip shapes outside visible region
                if (s.x + s.width < visX1 || s.x > visX2) continue
                if (s.y + s.height < visY1 || s.y > visY2) continue

                const cx = s.x + s.width / 2
                const cy = s.y + s.height / 2

                c.save()
                c.translate(cx, cy)
                if (s.rotation !== 0) c.rotate(s.rotation * (Math.PI / 180))

                if (s.width < 1.5 && s.height < 1.5) {
                  c.fillStyle = '#94a3b8'
                  c.beginPath()
                  c.arc(0, 0, 1.5, 0, Math.PI * 2)
                  c.fill()
                } else {
                  c.beginPath()
                  c.rect(-s.width / 2, -s.height / 2, s.width, s.height)
                  c.stroke()
                }

                c.restore()
              }
            }}
          />
        </Layer>

        {/* Selected and annotated shapes — individual elements */}
        <Layer listening={false}>
          {doc.shapes
            .filter((s) => highlightedIds.has(s.id) && s.shape_type !== 'Group')
            .map((s) => {
              const type = annotations[s.id]
              const isSelected = s.id === selectedId
              const color = isSelected ? '#3b82f6' : (ANNOTATION_COLORS[type] ?? '#6366f1')
              const ew = Math.max(s.width, 4)
              const eh = Math.max(s.height, 4)
              return (
                <Rect
                  key={s.id}
                  x={s.x + s.width / 2}
                  y={s.y + s.height / 2}
                  width={ew}
                  height={eh}
                  offsetX={ew / 2}
                  offsetY={eh / 2}
                  rotation={s.rotation}
                  fill={color + '44'}
                  stroke={color}
                  strokeWidth={2 / stageScale}
                  shadowEnabled={false}
                  perfectDrawEnabled={false}
                  listening={false}
                />
              )
            })}
        </Layer>
      </Stage>
    </div>
  )
}
