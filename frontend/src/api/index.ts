import type { ParsedDocument } from '../types'

export async function parseFile(file: File): Promise<ParsedDocument> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch('/api/parse', { method: 'POST', body: fd })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error((body as { detail?: string }).detail ?? res.statusText)
  }
  return res.json() as Promise<ParsedDocument>
}
