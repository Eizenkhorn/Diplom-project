import type { ParsedDocument } from '../types'

export interface SessionCreateResponse {
  session_id: string
  page_width: number
  page_height: number
  shape_count: number
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

// kept for tests
export async function parseFile(file: File): Promise<ParsedDocument> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch('/api/parse', { method: 'POST', body: fd })
  await _checkOk(res)
  return res.json() as Promise<ParsedDocument>
}
