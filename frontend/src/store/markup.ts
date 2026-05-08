import { create } from 'zustand'
import type { WorkArea, HorizontalBand, StationPoint, MarkPoint, BandType } from '../types'
import {
  getMarkup,
  setWorkArea as apiSetWorkArea,
  createBand as apiCreateBand,
  deleteBand as apiDeleteBand,
  createStation as apiCreateStation,
  deleteStation as apiDeleteStation,
  createMark as apiCreateMark,
  deleteMark as apiDeleteMark,
} from '../api'
import { useSessionStore } from './session'

export type MarkupMode =
  | 'pan'
  | 'mark-work-area'
  | 'mark-band'
  | 'mark-station'
  | 'mark-mark'

export interface Point { x: number; y: number }

interface MarkupState {
  mode: MarkupMode
  activeBandType: BandType | null
  activeMarkSubtype: string | null
  pendingClicks: Point[]
  workArea: WorkArea | null
  bands: HorizontalBand[]
  stations: StationPoint[]
  marks: MarkPoint[]
  selectedId: string | null

  setMode(mode: MarkupMode, bandType?: BandType, markSubtype?: string): void
  addPendingClick(p: Point): void
  cancel(): void
  loadMarkup(sessionId: string): Promise<void>
  saveWorkArea(wa: WorkArea): Promise<void>
  createBand(data: { type: BandType; y_top: number; y_bottom: number; km_hint_start?: number; km_hint_end?: number }): Promise<void>
  deleteBand(id: string): Promise<void>
  createStation(data: { x: number; name: string }): Promise<void>
  deleteStation(id: string): Promise<void>
  createMark(data: { x: number; y: number; subtype: string }): Promise<void>
  deleteMark(id: string): Promise<void>
  setSelected(id: string | null): void
  reset(): void
}

export const useMarkupStore = create<MarkupState>()((set, _get) => ({
  mode: 'pan',
  activeBandType: null,
  activeMarkSubtype: null,
  pendingClicks: [],
  workArea: null,
  bands: [],
  stations: [],
  marks: [],
  selectedId: null,

  setMode(mode, bandType, markSubtype) {
    set({
      mode,
      activeBandType: bandType ?? null,
      activeMarkSubtype: markSubtype ?? null,
      pendingClicks: [],
    })
  },

  addPendingClick(p) {
    set((s) => ({ pendingClicks: [...s.pendingClicks, p] }))
  },

  cancel() {
    set({ mode: 'pan', activeBandType: null, activeMarkSubtype: null, pendingClicks: [] })
  },

  async loadMarkup(sessionId) {
    const markup = await getMarkup(sessionId)
    set({
      workArea: markup.work_area,
      bands: markup.bands,
      stations: markup.stations,
      marks: markup.marks,
    })
  },

  async saveWorkArea(wa) {
    const sessionId = useSessionStore.getState().sessionId
    if (!sessionId) return
    const markup = await apiSetWorkArea(sessionId, wa)
    set({ workArea: markup.work_area, pendingClicks: [], mode: 'pan' })
  },

  async createBand(data) {
    const sessionId = useSessionStore.getState().sessionId
    if (!sessionId) return
    const band = await apiCreateBand(sessionId, data)
    set((s) => ({ bands: [...s.bands, band], pendingClicks: [], mode: 'pan' }))
  },

  async deleteBand(id) {
    const sessionId = useSessionStore.getState().sessionId
    if (!sessionId) return
    set((s) => ({ bands: s.bands.filter((b) => b.id !== id) }))
    await apiDeleteBand(sessionId, id).catch(console.error)
  },

  async createStation(data) {
    const sessionId = useSessionStore.getState().sessionId
    if (!sessionId) return
    const station = await apiCreateStation(sessionId, data)
    set((s) => ({ stations: [...s.stations, station], pendingClicks: [], mode: 'pan' }))
  },

  async deleteStation(id) {
    const sessionId = useSessionStore.getState().sessionId
    if (!sessionId) return
    set((s) => ({ stations: s.stations.filter((st) => st.id !== id) }))
    await apiDeleteStation(sessionId, id).catch(console.error)
  },

  async createMark(data) {
    const sessionId = useSessionStore.getState().sessionId
    if (!sessionId) return
    const mark = await apiCreateMark(sessionId, data)
    set((s) => ({ marks: [...s.marks, mark], pendingClicks: [], mode: 'pan' }))
  },

  async deleteMark(id) {
    const sessionId = useSessionStore.getState().sessionId
    if (!sessionId) return
    set((s) => ({ marks: s.marks.filter((m) => m.id !== id) }))
    await apiDeleteMark(sessionId, id).catch(console.error)
  },

  setSelected(id) { set({ selectedId: id }) },

  reset() {
    set({
      mode: 'pan',
      activeBandType: null,
      activeMarkSubtype: null,
      pendingClicks: [],
      workArea: null,
      bands: [],
      stations: [],
      marks: [],
      selectedId: null,
    })
  },
}))
