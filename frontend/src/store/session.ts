import { create } from 'zustand'
import type { ParsedShape } from '../types'

interface SessionState {
  sessionId: string | null
  pageWidth: number
  pageHeight: number
  shapes: ParsedShape[]
  shapesTotal: number
  loading: boolean
  fileName: string | null
  svgUrl: string | null
  error: string | null
  setSession: (id: string, w: number, h: number, total: number, name: string, svgUrl: string | null) => void
  setError: (e: string | null) => void
  loadShapes: (sessionId: string, total: number) => Promise<void>
}

export const useSessionStore = create<SessionState>()((set, get) => ({
  sessionId: null,
  pageWidth: 0,
  pageHeight: 0,
  shapes: [],
  shapesTotal: 0,
  loading: false,
  fileName: null,
  svgUrl: null,
  error: null,

  setSession: (id, w, h, total, name, svgUrl) =>
    set({ sessionId: id, pageWidth: w, pageHeight: h, shapesTotal: total, fileName: name, svgUrl, shapes: [], error: null }),

  setError: (e) => set({ error: e, loading: false }),

  loadShapes: async (sessionId, total) => {
    set({ loading: true, shapes: [] })
    const BATCH = 2000
    let offset = 0
    try {
      while (offset < total) {
        if (get().sessionId !== sessionId) return
        const res = await fetch(
          `/api/sessions/${sessionId}/shapes?offset=${offset}&limit=${BATCH}`,
        )
        if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
        const data = (await res.json()) as { shapes: ParsedShape[] }
        set((s) => ({ shapes: [...s.shapes, ...data.shapes] }))
        offset += BATCH
      }
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) })
    } finally {
      set({ loading: false })
    }
  },
}))
