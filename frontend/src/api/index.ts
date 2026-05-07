import type {
  ParsedDocument,
  SessionMarkup,
  WorkArea,
  HorizontalBand,
  StationPoint,
  MarkPoint,
  BandType,
  ExtractionResult,
} from '../types'

export interface SessionCreateResponse {
  session_id: string
  page_width: number
  page_height: number
  shape_count: number
  svg_url: string | null
}

async function _checkOk(res: Response) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error((body as { detail?: string }).detail ?? res.statusText)
  }
}

// ── sessions ──────────────────────────────────────────────────────────────────

export async function createSession(file: File): Promise<SessionCreateResponse> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch('/api/sessions', { method: 'POST', body: fd })
  await _checkOk(res)
  return res.json() as Promise<SessionCreateResponse>
}

export async function getSession(sessionId: string): Promise<SessionCreateResponse> {
  const res = await fetch(`/api/sessions/${sessionId}`)
  await _checkOk(res)
  return res.json() as Promise<SessionCreateResponse>
}

// ── markup ────────────────────────────────────────────────────────────────────

export async function getMarkup(sessionId: string): Promise<SessionMarkup> {
  const res = await fetch(`/api/sessions/${sessionId}/markup`)
  await _checkOk(res)
  return res.json() as Promise<SessionMarkup>
}

export async function setWorkArea(sessionId: string, wa: WorkArea): Promise<SessionMarkup> {
  const res = await fetch(`/api/sessions/${sessionId}/markup/work-area`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(wa),
  })
  await _checkOk(res)
  return res.json() as Promise<SessionMarkup>
}

// ── bands ─────────────────────────────────────────────────────────────────────

export interface BandCreate { type: BandType; y_top: number; y_bottom: number }

export async function createBand(sessionId: string, body: BandCreate): Promise<HorizontalBand> {
  const res = await fetch(`/api/sessions/${sessionId}/markup/bands`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  await _checkOk(res)
  return res.json() as Promise<HorizontalBand>
}

export async function deleteBand(sessionId: string, bandId: string): Promise<void> {
  const res = await fetch(`/api/sessions/${sessionId}/markup/bands/${bandId}`, { method: 'DELETE' })
  await _checkOk(res)
}

// ── stations ──────────────────────────────────────────────────────────────────

export interface StationCreate { x: number; name: string }

export async function createStation(sessionId: string, body: StationCreate): Promise<StationPoint> {
  const res = await fetch(`/api/sessions/${sessionId}/markup/stations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  await _checkOk(res)
  return res.json() as Promise<StationPoint>
}

export async function deleteStation(sessionId: string, stationId: string): Promise<void> {
  const res = await fetch(`/api/sessions/${sessionId}/markup/stations/${stationId}`, { method: 'DELETE' })
  await _checkOk(res)
}

// ── marks ─────────────────────────────────────────────────────────────────────

export interface MarkCreate { x: number; y: number; subtype: string; meta?: Record<string, unknown> }

export async function createMark(sessionId: string, body: MarkCreate): Promise<MarkPoint> {
  const res = await fetch(`/api/sessions/${sessionId}/markup/marks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  await _checkOk(res)
  return res.json() as Promise<MarkPoint>
}

export async function deleteMark(sessionId: string, markId: string): Promise<void> {
  const res = await fetch(`/api/sessions/${sessionId}/markup/marks/${markId}`, { method: 'DELETE' })
  await _checkOk(res)
}

// ── extraction / export ───────────────────────────────────────────────────────

export async function extractSession(sessionId: string): Promise<ExtractionResult> {
  const res = await fetch(`/api/sessions/${sessionId}/extract`)
  await _checkOk(res)
  return res.json() as Promise<ExtractionResult>
}

export async function exportSession(sessionId: string): Promise<unknown> {
  const res = await fetch(`/api/sessions/${sessionId}/export`)
  await _checkOk(res)
  return res.json()
}

// kept for tests
export async function parseFile(file: File): Promise<ParsedDocument> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch('/api/parse', { method: 'POST', body: fd })
  await _checkOk(res)
  return res.json() as Promise<ParsedDocument>
}
