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

export type AnnotationType =
  | 'station'
  | 'profile_segment'
  | 'speed_limit'
  | 'coordinate_ruler'
