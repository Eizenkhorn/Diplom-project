import { create } from 'zustand'
import type { Region, RegionType } from '../types'
import {
  getRegions as apiGetRegions,
  createRegion as apiCreateRegion,
  updateRegion as apiUpdateRegion,
  deleteRegion as apiDeleteRegion,
  type RegionCreate,
  type RegionUpdate,
} from '../api'
import { useSessionStore } from './session'

interface RegionsState {
  regions: Region[]
  selectedId: string | null
  mode: 'pan' | 'draw' | 'select'
  drawType: RegionType
  loadRegions: (sessionId: string) => Promise<void>
  createRegion: (data: RegionCreate) => Promise<Region>
  updateRegion: (rid: string, patch: RegionUpdate) => Promise<void>
  deleteRegion: (rid: string) => Promise<void>
  setMode: (mode: 'pan' | 'draw' | 'select') => void
  setDrawType: (type: RegionType) => void
  selectRegion: (id: string | null) => void
  reset: () => void
}

export const useRegionsStore = create<RegionsState>()((set, get) => ({
  regions: [],
  selectedId: null,
  mode: 'pan',
  drawType: 'profile',

  loadRegions: async (sessionId) => {
    const regions = await apiGetRegions(sessionId)
    set({ regions, selectedId: null })
  },

  createRegion: async (data) => {
    const sessionId = useSessionStore.getState().sessionId
    if (!sessionId) throw new Error('No active session')
    const region = await apiCreateRegion(sessionId, data)
    set((s) => ({ regions: [...s.regions, region], drawType: data.type }))
    return region
  },

  updateRegion: async (rid, patch) => {
    const sessionId = useSessionStore.getState().sessionId
    if (!sessionId) return
    // Optimistic update
    set((s) => ({
      regions: s.regions.map((r) => (r.id === rid ? { ...r, ...patch } : r)),
    }))
    try {
      const updated = await apiUpdateRegion(sessionId, rid, patch)
      set((s) => ({
        regions: s.regions.map((r) => (r.id === rid ? updated : r)),
      }))
    } catch (err) {
      console.error('Region update failed:', err)
    }
  },

  deleteRegion: async (rid) => {
    const sessionId = useSessionStore.getState().sessionId
    if (!sessionId) return
    set((s) => ({
      regions: s.regions.filter((r) => r.id !== rid),
      selectedId: s.selectedId === rid ? null : s.selectedId,
    }))
    try {
      await apiDeleteRegion(sessionId, rid)
    } catch (err) {
      console.error('Region delete failed:', err)
    }
  },

  setMode: (mode) => set({ mode, selectedId: mode !== 'select' ? null : get().selectedId }),
  setDrawType: (type) => set({ drawType: type }),
  selectRegion: (id) => set({ selectedId: id }),
  reset: () => set({ regions: [], selectedId: null, mode: 'pan' }),
}))
