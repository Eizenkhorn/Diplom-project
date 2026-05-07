// ── parsed document (from vsdx parser) ────────────────────────────────────────

export interface ParsedShape {
  id: string
  text: string | null
  x: number
  y: number
  width: number
  height: number
  rotation: number
  shape_type: 'Shape' | 'Group' | 'Foreign' | 'Connector'
  parent_id: string | null
}

export interface ParsedDocument {
  page_width: number
  page_height: number
  shapes: ParsedShape[]
}

// ── markup models ──────────────────────────────────────────────────────────────

export type BandType =
  | 'speed_limits'
  | 'profile'
  | 'track_plan'
  | 'traction_modes'
  | 'coordinate_ruler'
  | 'path_schema'

export interface WorkArea {
  x_start: number
  x_end: number
}

export interface HorizontalBand {
  id: string
  type: BandType
  y_top: number
  y_bottom: number
  extracted: Record<string, unknown>
  is_informational: boolean
}

export interface StationPoint {
  id: string
  x: number
  name: string
}

export interface MarkPoint {
  id: string
  x: number
  y: number
  subtype: string
  meta: Record<string, unknown>
}

export interface SessionMarkup {
  work_area: WorkArea | null
  bands: HorizontalBand[]
  stations: StationPoint[]
  marks: MarkPoint[]
}

// ── type registries (must stay in sync with backend/models/markup_types.py) ───

export interface BandTypeInfo {
  type: BandType
  label: string
  color: string
  is_informational?: boolean
}

export interface MarkSubtypeInfo {
  subtype: string
  label: string
  color: string
}

export const BAND_TYPES: BandTypeInfo[] = [
  { type: 'speed_limits',    label: 'Ограничения скорости', color: '#ef4444' },
  { type: 'profile',         label: 'Профиль пути',         color: '#10b981' },
  { type: 'track_plan',      label: 'План пути',            color: '#f59e0b' },
  { type: 'traction_modes',  label: 'Режимы тяги',          color: '#a855f7' },
  { type: 'coordinate_ruler',label: 'Координатная шкала',   color: '#6b7280' },
  { type: 'path_schema',     label: 'Схема пути',           color: '#fbbf24', is_informational: true },
]

export const MARK_SUBTYPES: MarkSubtypeInfo[] = [
  { subtype: 'entry_signal',     label: 'Входной светофор',    color: '#ef4444' },
  { subtype: 'exit_signal',      label: 'Выходной светофор',   color: '#f97316' },
  { subtype: 'route_signal',     label: 'Маршрутный светофор', color: '#eab308' },
  { subtype: 'passing_signal',   label: 'Проходной светофор',  color: '#22c55e' },
  { subtype: 'crossing_guarded', label: 'Переезд',             color: '#06b6d4' },
  { subtype: 'neutral_insert',   label: 'Нейтральная вставка', color: '#8b5cf6' },
  { subtype: 'ktsm',             label: 'КТСМ',                color: '#ec4899' },
  { subtype: 'uksps',            label: 'УКСПС',               color: '#14b8a6' },
  { subtype: 'bridge',           label: 'Мост',                color: '#64748b' },
  { subtype: 'brake_marker',     label: 'Тормозной ориентир',  color: '#dc2626' },
  { subtype: 'station_axis',     label: 'Ось станции',         color: '#3b82f6' },
]
