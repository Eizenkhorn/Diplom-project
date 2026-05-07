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

export type RegionType =
  | 'profile'
  | 'speed_limit'
  | 'station'
  | 'coordinate_ruler'
  | 'track_plan'
  | 'other'

export interface Region {
  id: string
  type: RegionType
  x: number
  y: number
  width: number
  height: number
  meta: Record<string, unknown>
}

export const ANNOTATION_TYPES: { type: RegionType; label: string; color: string }[] = [
  { type: 'profile', label: 'Профиль пути', color: '#10b981' },
  { type: 'speed_limit', label: 'Ограничения скорости', color: '#ef4444' },
  { type: 'station', label: 'Станции', color: '#3b82f6' },
  { type: 'coordinate_ruler', label: 'Координатная шкала', color: '#a855f7' },
  { type: 'track_plan', label: 'План пути', color: '#f59e0b' },
  { type: 'other', label: 'Прочее', color: '#6b7280' },
]
