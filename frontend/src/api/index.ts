import type { ParsedDocument, Region, RegionType } from '../types'

export interface SessionCreateResponse {
  session_id: string
  page_width: number
  page_height: number
  shape_count: number
  svg_url: string | null
}

export interface RegionCreate {
  type: RegionType
  x: number
  y: number
  width: number
  height: number
  meta?: Record<string, unknown>
}

export interface RegionUpdate {
  type?: RegionType
  x?: number
  y?: number
  width?: number
  height?: number
  meta?: Record<string, unknown>
}

async function _checkOk(res: Response) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error((body as { detail?: string }).detail ?? res.statusText)
  }
}

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

export async function getRegions(sessionId: string): Promise<Region[]> {
  const res = await fetch(`/api/sessions/${sessionId}/regions`)
  await _checkOk(res)
  return res.json() as Promise<Region[]>
}

export async function createRegion(sessionId: string, body: RegionCreate): Promise<Region> {
  const res = await fetch(`/api/sessions/${sessionId}/regions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  await _checkOk(res)
  return res.json() as Promise<Region>
}

export async function updateRegion(sessionId: string, rid: string, body: RegionUpdate): Promise<Region> {
  const res = await fetch(`/api/sessions/${sessionId}/regions/${rid}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  await _checkOk(res)
  return res.json() as Promise<Region>
}

export async function deleteRegion(sessionId: string, rid: string): Promise<void> {
  const res = await fetch(`/api/sessions/${sessionId}/regions/${rid}`, { method: 'DELETE' })
  await _checkOk(res)
}

// kept for tests
export async function parseFile(file: File): Promise<ParsedDocument> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch('/api/parse', { method: 'POST', body: fd })
  await _checkOk(res)
  return res.json() as Promise<ParsedDocument>
}
