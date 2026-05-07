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
  | 'speed_limits'
  | 'traction_modes'
  | 'stations'
  | 'coordinate_ruler'
  | 'profile'
  | 'track_plan'
  | 'marks'
  | 'unknown'

export interface Region {
  id: string
  type: RegionType
  x: number
  y: number
  width: number
  height: number
  meta: Record<string, unknown>
}

export interface AnnotationType {
  type: RegionType
  label: string
  color: string
  description: string
  json_field: string | null
}

export const ANNOTATION_TYPES: AnnotationType[] = [
  {
    type: 'speed_limits',
    label: 'Ограничения скорости',
    color: '#ef4444',
    json_field: 'speedLimits',
    description: 'Красная огибающая линия по верхним черным штрихам',
  },
  {
    type: 'traction_modes',
    label: 'Режимы тяги',
    color: '#a855f7',
    json_field: 'locomotiveRegimeBands',
    description: 'Стрелки Тяга 2С / Тяга С / Р/т СП в верхней части карты',
  },
  {
    type: 'stations',
    label: 'Станции',
    color: '#3b82f6',
    json_field: 'stations',
    description: 'Названия станций и раздельных пунктов',
  },
  {
    type: 'coordinate_ruler',
    label: 'Координатная шкала',
    color: '#6b7280',
    json_field: 'coordinateRuler',
    description: 'Черная полоса с километровыми отметками',
  },
  {
    type: 'profile',
    label: 'Профиль пути',
    color: '#10b981',
    json_field: 'profile',
    description: 'Углы уклонов в ‰ и длины сегментов под километровой шкалой',
  },
  {
    type: 'track_plan',
    label: 'План пути',
    color: '#f59e0b',
    json_field: 'trackPlan',
    description: 'Синяя ступенчатая ломаная, отображающая план',
  },
  {
    type: 'marks',
    label: 'Метки и сигналы',
    color: '#eab308',
    json_field: 'marks',
    description: 'Светофоры, треугольники, иконки путевых объектов',
  },
  {
    type: 'unknown',
    label: 'Не определено',
    color: '#9ca3af',
    json_field: null,
    description: 'Регион требует уточнения типа',
  },
]
