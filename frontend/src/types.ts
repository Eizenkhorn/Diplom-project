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

// ── extraction results ────────────────────────────────────────────────────────

export interface ProfileSegment {
  start: number
  end: number
  angle: number
}

export interface SpeedLimitSegment {
  start: number
  end: number
  limit: number
  type: string
}

export interface ExtractionLog {
  coordinate_ruler: {
    shapes_in_band_y: number
    shapes_in_band_xy: number
    kilometer_candidates: number
    unique_values: number
    rejected_duplicate_values: number
    rejected_values_list: number[]
    monotone_points: number
    found_kilometers: number
    direction: string | null
    range: [number, number] | null
  }
  profile: {
    shapes_in_band_y: number
    shapes_in_band_xy: number
    angle_count: number
    length_count: number
    unclassified_count: number
    found_segments: number
    total_length_meters: number
  }
  speed_limits: {
    shapes_in_band: number
    scale_labels_raw: number
    scale_labels_deduped: number
    scale_speeds: number[]
    candidate_line_shapes: number
    red_lines: number
    other_lines: number
    used_color_filter: boolean
    raw_segments: number
    found_segments: number
    value_scale_points: number[]
    red_line_details: Array<Record<string, unknown>>
    rejected_red_segments: Array<Record<string, unknown>>
    red_elements_classified: {
      total_red_in_band: number
      horizontal: number
      vertical_skipped: number
      other_skipped: number
    }
    by_speed_value: Record<string, { raw_count: number; after_merge: number }>
    merge_gaps_used: number[]
    rejected_far_from_scale: Array<Record<string, unknown>>
    rejected_short_after_merge: Array<Record<string, unknown>>
    scales_found: number
    scale_groups: Array<{ x_center: number; y_to_speed: Array<[number, number]> }>
    red_horizontal_with_scale_match: Array<Record<string, unknown>>
    gaps_closed: Array<Record<string, unknown>>
    gaps_too_large_warned: Array<Record<string, unknown>>
    merged_same_limit: Array<Record<string, unknown>>
  }
  stations: {
    count: number
    coordinates: number[]
  }
  warnings: string[]
}

export interface ExtractionResult {
  extraction_log: ExtractionLog
  metadata: { id: string; name: string; createdAt: string; updatedAt: string }
  coordinateRuler: { segments: Array<{ startCoordinate: number; endCoordinate: number; adjustments: unknown[] }> }
  stations: Array<{ name: string; coordinate: number; graphical: Record<string, unknown> }>
  profile: ProfileSegment[]
  speedLimits: SpeedLimitSegment[]
  marks: unknown[]
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
