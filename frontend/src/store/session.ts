import { create } from 'zustand'

interface SessionState {
  sessionId: string | null
  pageWidth: number
  pageHeight: number
  svgUrl: string | null
  fileName: string | null
  setSession: (id: string, w: number, h: number, name: string, svgUrl: string | null) => void
  clearSession: () => void
}

export const useSessionStore = create<SessionState>()((set) => ({
  sessionId: null,
  pageWidth: 0,
  pageHeight: 0,
  svgUrl: null,
  fileName: null,

  setSession: (id, w, h, name, svgUrl) => {
    localStorage.setItem('mprk_session_id', id)
    set({ sessionId: id, pageWidth: w, pageHeight: h, fileName: name, svgUrl })
  },

  clearSession: () => {
    localStorage.removeItem('mprk_session_id')
    set({ sessionId: null, pageWidth: 0, pageHeight: 0, svgUrl: null, fileName: null })
  },
}))
