import { create } from 'zustand'
import type { ParsedDocument, AnnotationType } from '../types'

interface AppState {
  doc: ParsedDocument | null
  annotations: Record<string, AnnotationType>
  selectedShapeId: string | null
  setDoc: (doc: ParsedDocument) => void
  selectShape: (id: string | null) => void
  annotate: (shapeId: string, type: AnnotationType) => void
  removeAnnotation: (shapeId: string) => void
}

export const useAppStore = create<AppState>()((set) => ({
  doc: null,
  annotations: {},
  selectedShapeId: null,
  setDoc: (doc) => set({ doc, annotations: {}, selectedShapeId: null }),
  selectShape: (id) => set({ selectedShapeId: id }),
  annotate: (shapeId, type) =>
    set((s) => ({
      annotations: { ...s.annotations, [shapeId]: type },
      selectedShapeId: null,
    })),
  removeAnnotation: (shapeId) =>
    set((s) => {
      const next = { ...s.annotations }
      delete next[shapeId]
      return { annotations: next }
    }),
}))
