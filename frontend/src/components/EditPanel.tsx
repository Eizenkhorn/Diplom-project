import { useState } from 'react'
import type { ExtractionResult } from '../types'
import { extractSession, saveEdits, exportSession } from '../api'
import { MARK_SUBTYPES } from '../types'

// ── types ──────────────────────────────────────────────────────────────────────

type TabId = 'warnings' | 'ruler' | 'profile' | 'speed' | 'stations' | 'marks'

interface PRow { start: number; end: number; angle: number }
interface SRow { start: number; end: number; limit: number; type: string }
interface StRow { name: string; coordinate: number; graphical: Record<string, unknown> }
interface MRow { subtype: string; coordinate: number; x: number; y: number; meta: Record<string, unknown> }

interface EditState {
  profile: PRow[]
  speed: SRow[]
  stations: StRow[]
  marks: MRow[]
  rulerStart: number
  rulerEnd: number
}

interface EditCell { tab: TabId; idx: number; field: string }

// ── helpers ────────────────────────────────────────────────────────────────────

function coordToPixelX(networkM: number, pts: Array<{ x_px: number; km: number }>): number {
  const km = networkM / 1000
  const s = [...pts].sort((a, b) => a.km - b.km)
  if (!s.length) return 0
  if (km <= s[0].km) return s[0].x_px
  if (km >= s[s.length - 1].km) return s[s.length - 1].x_px
  for (let i = 0; i < s.length - 1; i++) {
    if (s[i].km <= km && km <= s[i + 1].km) {
      const t = (km - s[i].km) / (s[i + 1].km - s[i].km)
      return s[i].x_px + t * (s[i + 1].x_px - s[i].x_px)
    }
  }
  return s[s.length - 1].x_px
}

function numOrOld<T>(val: string, old: T): number | T {
  const n = parseFloat(val)
  return isNaN(n) ? old : n
}

function intOrOld<T>(val: string, old: T): number | T {
  const n = parseInt(val, 10)
  return isNaN(n) ? old : n
}

function fmtM(m: number) { return (m / 1000).toFixed(3) + ' км' }
function fmtKm(m: number) { return Math.round(m / 1000) + ' км' }

// ── sub-components ─────────────────────────────────────────────────────────────

function Btn({ onClick, color, disabled, children }: {
  onClick: () => void; color: string; disabled?: boolean; children: React.ReactNode
}) {
  return (
    <button onClick={onClick} disabled={disabled} style={{
      padding: '6px 14px', background: disabled ? '#94a3b8' : color, color: '#fff',
      border: 'none', borderRadius: 6, cursor: disabled ? 'default' : 'pointer',
      fontSize: 12, fontWeight: 500, fontFamily: 'inherit', flexShrink: 0,
    }}>
      {children}
    </button>
  )
}

function TabBtn({ id, label, active, badge, onClick }: {
  id: TabId; label: string; active: boolean; badge?: number; onClick: () => void
}) {
  return (
    <button onClick={onClick} style={{
      padding: '6px 14px', background: active ? '#fff' : 'transparent',
      border: 'none', borderBottom: active ? '2px solid #3b82f6' : '2px solid transparent',
      color: active ? '#1e293b' : '#64748b', cursor: 'pointer',
      fontSize: 12, fontWeight: active ? 600 : 400, fontFamily: 'inherit',
      display: 'flex', alignItems: 'center', gap: 5, flexShrink: 0,
    }}>
      {label}
      {badge != null && badge > 0 && (
        <span style={{
          background: id === 'warnings' ? '#ef4444' : '#6b7280',
          color: '#fff', borderRadius: 10, padding: '1px 6px', fontSize: 10, fontWeight: 700,
        }}>{badge}</span>
      )}
    </button>
  )
}

// ── main component ─────────────────────────────────────────────────────────────

export default function EditPanel({ sessionId, onClose, onNavigate }: {
  sessionId: string
  onClose: () => void
  onNavigate: (docX: number) => void
}) {
  const [result, setResult] = useState<ExtractionResult | null>(null)
  const [edit, setEdit] = useState<EditState | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<TabId>('warnings')
  const [editCell, setEditCell] = useState<EditCell | null>(null)
  const [editVal, setEditVal] = useState('')

  // add-row form state per section
  const [addProfile, setAddProfile] = useState<Partial<PRow>>({})
  const [addSpeed, setAddSpeed] = useState<Partial<SRow>>({})
  const [addStation, setAddStation] = useState<Partial<StRow>>({})
  const [addMark, setAddMark] = useState<Partial<MRow>>({})

  // ── extract ──────────────────────────────────────────────────────────────────

  async function handleExtract() {
    setLoading(true); setError(null)
    try {
      const r = await extractSession(sessionId)
      setResult(r)
      setEdit(toEditState(r))
      setTab('warnings')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  function toEditState(r: ExtractionResult): EditState {
    return {
      profile: r.profile.map(s => ({ ...s })),
      speed: r.speedLimits.map(s => ({ ...s })),
      stations: r.stations.map(s => ({ name: s.name, coordinate: s.coordinate, graphical: s.graphical })),
      marks: r.marks.map(m => ({ subtype: m.subtype, coordinate: m.coordinate, x: m.x, y: m.y, meta: m.meta })),
      rulerStart: r.coordinateRuler.segments[0]?.startCoordinate ?? 0,
      rulerEnd: r.coordinateRuler.segments[0]?.endCoordinate ?? 0,
    }
  }

  // ── inline editing ───────────────────────────────────────────────────────────

  function startEdit(t: TabId, idx: number, field: string, val: string) {
    setEditCell({ tab: t, idx, field }); setEditVal(val)
  }

  function applyEdit() {
    if (!editCell || !edit) { setEditCell(null); return }
    const { tab: t, idx, field } = editCell
    const e = { ...edit }
    if (t === 'profile') {
      const rows = [...e.profile]
      rows[idx] = { ...rows[idx], [field]: numOrOld(editVal, rows[idx][field as keyof PRow]) }
      e.profile = rows
    } else if (t === 'speed') {
      const rows = [...e.speed]
      if (field === 'type') rows[idx] = { ...rows[idx], type: editVal }
      else rows[idx] = { ...rows[idx], [field]: field === 'limit' ? intOrOld(editVal, rows[idx].limit) : numOrOld(editVal, rows[idx][field as keyof SRow]) }
      e.speed = rows
    } else if (t === 'stations') {
      const rows = [...e.stations]
      if (field === 'name') rows[idx] = { ...rows[idx], name: editVal }
      else rows[idx] = { ...rows[idx], [field]: numOrOld(editVal, rows[idx][field as keyof StRow]) }
      e.stations = rows
    } else if (t === 'marks') {
      const rows = [...e.marks]
      if (field === 'subtype') rows[idx] = { ...rows[idx], subtype: editVal }
      else rows[idx] = { ...rows[idx], [field]: numOrOld(editVal, rows[idx][field as keyof MRow]) }
      e.marks = rows
    } else if (t === 'ruler') {
      if (field === 'rulerStart') e.rulerStart = numOrOld(editVal, e.rulerStart) as number
      if (field === 'rulerEnd') e.rulerEnd = numOrOld(editVal, e.rulerEnd) as number
    }
    setEdit(e); setEditCell(null)
  }

  function deleteRow(t: TabId, idx: number) {
    if (!edit) return
    const e = { ...edit }
    if (t === 'profile') e.profile = edit.profile.filter((_, i) => i !== idx)
    else if (t === 'speed') e.speed = edit.speed.filter((_, i) => i !== idx)
    else if (t === 'stations') e.stations = edit.stations.filter((_, i) => i !== idx)
    else if (t === 'marks') e.marks = edit.marks.filter((_, i) => i !== idx)
    setEdit(e)
  }

  // ── navigation ───────────────────────────────────────────────────────────────

  function navigate(networkM: number) {
    const pts = result?.coord_mapping_points ?? []
    if (!pts.length) return
    onNavigate(coordToPixelX(networkM, pts))
  }

  // ── save ─────────────────────────────────────────────────────────────────────

  async function handleSave() {
    if (!edit || !result) return
    setSaving(true); setError(null)
    try {
      const now = new Date().toISOString()
      await saveEdits(sessionId, {
        metadata: { ...result.metadata, updatedAt: now },
        coordinateRuler: {
          segments: [{ startCoordinate: edit.rulerStart, endCoordinate: edit.rulerEnd, adjustments: [] }],
        },
        stations: edit.stations,
        profile: edit.profile,
        speedLimits: edit.speed,
        locomotives: [], cars: [], canvasLayers: [], trackPlan: [],
        optimalSpeedCurve: [], speedCurve: [], optimalRegimeBands: [],
        locomotiveRegimeBands: [], longitudinalForces: [],
        marks: edit.marks,
        extraction_log: result.extraction_log,
      })
      setSaved(true); setTimeout(() => setSaved(false), 3000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  // ── export ───────────────────────────────────────────────────────────────────

  async function handleExport() {
    try {
      const data = await exportSession(sessionId)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `export_${sessionId.slice(0, 8)}.json`
      a.click(); URL.revokeObjectURL(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  // ── cell renderer ─────────────────────────────────────────────────────────────

  const cellStyle: React.CSSProperties = {
    padding: '4px 8px', border: '1px solid #e2e8f0', fontSize: 12, color: '#1e293b',
    cursor: 'text', userSelect: 'none',
  }
  const editingInput: React.CSSProperties = {
    width: '100%', padding: '2px 4px', border: '1px solid #93c5fd',
    borderRadius: 3, fontSize: 12, outline: 'none', fontFamily: 'inherit',
    boxSizing: 'border-box',
  }

  function Cell({ t, idx, field, value }: { t: TabId; idx: number; field: string; value: string | number }) {
    const isMe = editCell?.tab === t && editCell.idx === idx && editCell.field === field
    return (
      <td style={cellStyle} onClick={() => !isMe && startEdit(t, idx, field, String(value))}>
        {isMe
          ? <input autoFocus style={editingInput} value={editVal}
              onChange={e => setEditVal(e.target.value)}
              onBlur={applyEdit}
              onKeyDown={e => { if (e.key === 'Enter') applyEdit(); if (e.key === 'Escape') setEditCell(null) }}
            />
          : value
        }
      </td>
    )
  }

  // ── table structure ───────────────────────────────────────────────────────────

  const TH = ({ children }: { children: React.ReactNode }) => (
    <th style={{ padding: '5px 8px', background: '#f8fafc', border: '1px solid #e2e8f0', textAlign: 'left', fontWeight: 600, color: '#64748b', fontSize: 11, whiteSpace: 'nowrap' }}>
      {children}
    </th>
  )

  const rowHover: React.CSSProperties = { cursor: 'pointer' }

  function DelBtn({ onClick }: { onClick: () => void }) {
    return (
      <td style={{ ...cellStyle, textAlign: 'center', width: 32 }}>
        <button onClick={onClick} title="Удалить" style={{
          padding: '1px 5px', background: 'transparent', border: '1px solid #fca5a5',
          borderRadius: 3, color: '#ef4444', cursor: 'pointer', fontSize: 11,
        }}>×</button>
      </td>
    )
  }

  const log = result?.extraction_log
  const warnings = log?.warnings ?? []
  const largGaps = log?.speed_limits?.gaps_too_large_warned ?? []
  const allWarns = warnings.length + largGaps.length

  // ── render ────────────────────────────────────────────────────────────────────

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }} onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div style={{
        background: '#fff', borderRadius: 12, width: 860, maxWidth: '96vw',
        maxHeight: '92vh', display: 'flex', flexDirection: 'column',
        boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
      }}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px', borderBottom: '1px solid #e2e8f0', flexShrink: 0 }}>
          <span style={{ fontWeight: 700, fontSize: 15, color: '#1e293b' }}>Редактор данных</span>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {saved && <span style={{ fontSize: 12, color: '#10b981', fontWeight: 500 }}>✓ Сохранено</span>}
            {edit && <Btn onClick={handleSave} color={saving ? '#94a3b8' : '#10b981'} disabled={saving}>{saving ? 'Сохраняю…' : 'Сохранить правки'}</Btn>}
            {edit && <Btn onClick={handleExport} color="#6b7280">Скачать JSON</Btn>}
            <Btn onClick={handleExtract} color={loading ? '#94a3b8' : '#3b82f6'} disabled={loading}>
              {loading ? 'Извлекаю…' : edit ? 'Повторить' : 'Извлечь и проверить'}
            </Btn>
            <button onClick={onClose} style={{ padding: '6px 12px', background: '#f1f5f9', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 12, color: '#64748b', fontFamily: 'inherit' }}>✕</button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div style={{ margin: '10px 20px 0', background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 8, padding: '8px 14px', color: '#dc2626', fontSize: 12, flexShrink: 0 }}>
            {error}
          </div>
        )}

        {/* Empty state */}
        {!edit && !loading && (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: 14 }}>
            Нажмите «Извлечь и проверить» чтобы загрузить данные
          </div>
        )}
        {loading && (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#64748b', fontSize: 14 }}>
            Обработка…
          </div>
        )}

        {/* Tabs + body */}
        {edit && result && (
          <>
            {/* Tab bar */}
            <div style={{ display: 'flex', borderBottom: '1px solid #e2e8f0', paddingLeft: 12, flexShrink: 0, overflowX: 'auto' }}>
              <TabBtn id="warnings" label="Предупреждения" active={tab === 'warnings'} badge={allWarns} onClick={() => setTab('warnings')} />
              <TabBtn id="ruler" label="Координ. шкала" active={tab === 'ruler'} onClick={() => setTab('ruler')} />
              <TabBtn id="profile" label={`Профиль (${edit.profile.length})`} active={tab === 'profile'} onClick={() => setTab('profile')} />
              <TabBtn id="speed" label={`Скорости (${edit.speed.length})`} active={tab === 'speed'} onClick={() => setTab('speed')} />
              <TabBtn id="stations" label={`Станции (${edit.stations.length})`} active={tab === 'stations'} onClick={() => setTab('stations')} />
              <TabBtn id="marks" label={`Метки (${edit.marks.length})`} active={tab === 'marks'} onClick={() => setTab('marks')} />
            </div>

            {/* Body */}
            <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>

              {/* ── Warnings ── */}
              {tab === 'warnings' && (
                <div>
                  {largGaps.length > 0 && (
                    <div style={{ marginBottom: 16 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: '#dc2626', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
                        Большие пропуски в покрытии скоростей
                      </div>
                      {largGaps.map((g, i) => {
                        const gap = g as { gap_meters: number; at_km: number; limits: number[] }
                        return (
                          <div key={i} style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 6, padding: '8px 12px', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 10 }}>
                            <div style={{ flex: 1, fontSize: 12, color: '#991b1b' }}>
                              Пропуск {Math.round(gap.gap_meters / 1000)} км между {gap.limits[0]} и {gap.limits[1]} км/ч у км {gap.at_km}
                            </div>
                            <button onClick={() => { navigate(gap.at_km * 1000); setTab('speed') }} style={{ padding: '3px 8px', background: '#ef4444', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 11, fontFamily: 'inherit', flexShrink: 0 }}>
                              Перейти / добавить
                            </button>
                          </div>
                        )
                      })}
                    </div>
                  )}
                  {warnings.length > 0 && (
                    <div>
                      <div style={{ fontSize: 11, fontWeight: 700, color: '#f59e0b', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
                        Предупреждения ({warnings.length})
                      </div>
                      <ul style={{ margin: 0, paddingLeft: 18 }}>
                        {warnings.map((w, i) => (
                          <li key={i} style={{ fontSize: 12, color: '#92400e', marginBottom: 4 }}>{w}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {allWarns === 0 && <div style={{ color: '#10b981', fontSize: 13 }}>✓ Предупреждений нет</div>}
                </div>
              )}

              {/* ── Coord ruler ── */}
              {tab === 'ruler' && (
                <div style={{ maxWidth: 400 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>Диапазон координат</div>
                  <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12 }}>
                    <thead><tr><TH>Поле</TH><TH>Значение (км)</TH></tr></thead>
                    <tbody>
                      <tr>
                        <td style={{ ...cellStyle, fontWeight: 500 }}>Начало (км)</td>
                        <Cell t="ruler" idx={0} field="rulerStart" value={edit.rulerStart} />
                      </tr>
                      <tr>
                        <td style={{ ...cellStyle, fontWeight: 500 }}>Конец (км)</td>
                        <Cell t="ruler" idx={0} field="rulerEnd" value={edit.rulerEnd} />
                      </tr>
                    </tbody>
                  </table>
                  <p style={{ fontSize: 11, color: '#94a3b8', marginTop: 10 }}>Нажмите на ячейку для редактирования. Координаты в км.</p>
                </div>
              )}

              {/* ── Profile ── */}
              {tab === 'profile' && (
                <div>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead><tr><TH>#</TH><TH>Начало м</TH><TH>Конец м</TH><TH>Уклон ‰</TH><TH></TH></tr></thead>
                    <tbody>
                      {edit.profile.map((row, i) => (
                        <tr key={i} style={rowHover} onClick={() => navigate((row.start + row.end) / 2)}>
                          <td style={{ ...cellStyle, color: '#94a3b8', width: 32 }}>{i + 1}</td>
                          <Cell t="profile" idx={i} field="start" value={Math.round(row.start)} />
                          <Cell t="profile" idx={i} field="end" value={Math.round(row.end)} />
                          <Cell t="profile" idx={i} field="angle" value={row.angle} />
                          <DelBtn onClick={e => { (e as unknown as React.MouseEvent).stopPropagation?.(); deleteRow('profile', i) }} />
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <AddProfileRow onAdd={row => setEdit(e => e ? { ...e, profile: [...e.profile, row] } : e)} state={addProfile} setState={setAddProfile} />
                </div>
              )}

              {/* ── Speed limits ── */}
              {tab === 'speed' && (
                <div>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead><tr><TH>#</TH><TH>Начало (м сети)</TH><TH>Конец (м сети)</TH><TH>V км/ч</TH><TH>Тип</TH><TH></TH></tr></thead>
                    <tbody>
                      {edit.speed.map((row, i) => (
                        <tr key={i} style={rowHover} onClick={() => navigate((row.start + row.end) / 2)}>
                          <td style={{ ...cellStyle, color: '#94a3b8', width: 32 }}>{i + 1}</td>
                          <Cell t="speed" idx={i} field="start" value={Math.round(row.start)} />
                          <Cell t="speed" idx={i} field="end" value={Math.round(row.end)} />
                          <Cell t="speed" idx={i} field="limit" value={row.limit} />
                          <Cell t="speed" idx={i} field="type" value={row.type} />
                          <DelBtn onClick={e => { (e as unknown as React.MouseEvent).stopPropagation?.(); deleteRow('speed', i) }} />
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div style={{ marginTop: 8, fontSize: 11, color: '#94a3b8' }}>
                    Всего: {edit.speed.length} сегментов. {fmtKm(edit.speed[0]?.start ?? 0)} — {fmtKm(edit.speed[edit.speed.length - 1]?.end ?? 0)}
                  </div>
                  <AddSpeedRow onAdd={row => setEdit(e => e ? { ...e, speed: [...e.speed, row] } : e)} state={addSpeed} setState={setAddSpeed} />
                </div>
              )}

              {/* ── Stations ── */}
              {tab === 'stations' && (
                <div>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead><tr><TH>#</TH><TH>Название</TH><TH>Координата (м)</TH><TH></TH></tr></thead>
                    <tbody>
                      {edit.stations.map((row, i) => (
                        <tr key={i} style={rowHover} onClick={() => navigate(row.coordinate)}>
                          <td style={{ ...cellStyle, color: '#94a3b8', width: 32 }}>{i + 1}</td>
                          <Cell t="stations" idx={i} field="name" value={row.name} />
                          <Cell t="stations" idx={i} field="coordinate" value={Math.round(row.coordinate)} />
                          <DelBtn onClick={e => { (e as unknown as React.MouseEvent).stopPropagation?.(); deleteRow('stations', i) }} />
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <AddStationRow onAdd={row => setEdit(e => e ? { ...e, stations: [...e.stations, row] } : e)} state={addStation} setState={setAddStation} />
                </div>
              )}

              {/* ── Marks ── */}
              {tab === 'marks' && (
                <div>
                  {edit.marks.length === 0
                    ? <div style={{ color: '#94a3b8', fontSize: 13 }}>Меток нет</div>
                    : (
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                        <thead><tr><TH>#</TH><TH>Подтип</TH><TH>Координата (м)</TH><TH>X px</TH><TH>Y px</TH><TH></TH></tr></thead>
                        <tbody>
                          {edit.marks.map((row, i) => (
                            <tr key={i} style={rowHover} onClick={() => navigate(row.coordinate)}>
                              <td style={{ ...cellStyle, color: '#94a3b8', width: 32 }}>{i + 1}</td>
                              <Cell t="marks" idx={i} field="subtype" value={row.subtype} />
                              <Cell t="marks" idx={i} field="coordinate" value={Math.round(row.coordinate)} />
                              <Cell t="marks" idx={i} field="x" value={Math.round(row.x)} />
                              <Cell t="marks" idx={i} field="y" value={Math.round(row.y)} />
                              <DelBtn onClick={e => { (e as unknown as React.MouseEvent).stopPropagation?.(); deleteRow('marks', i) }} />
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )
                  }
                  <AddMarkRow onAdd={row => setEdit(e => e ? { ...e, marks: [...e.marks, row] } : e)} state={addMark} setState={setAddMark} />
                </div>
              )}

            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── add-row forms ─────────────────────────────────────────────────────────────

const addRowStyle: React.CSSProperties = {
  display: 'flex', gap: 6, alignItems: 'center', marginTop: 8, flexWrap: 'wrap',
}
const addInput = (w?: number): React.CSSProperties => ({
  width: w ?? 100, padding: '4px 6px', border: '1px solid #cbd5e1', borderRadius: 4,
  fontSize: 12, fontFamily: 'inherit', outline: 'none',
})

function AddProfileRow({ onAdd, state, setState }: {
  onAdd: (r: PRow) => void
  state: Partial<PRow>
  setState: React.Dispatch<React.SetStateAction<Partial<PRow>>>
}) {
  return (
    <div style={addRowStyle}>
      <input style={addInput(90)} placeholder="Начало м" type="number" value={state.start ?? ''}
        onChange={e => setState(s => ({ ...s, start: parseFloat(e.target.value) }))} />
      <input style={addInput(90)} placeholder="Конец м" type="number" value={state.end ?? ''}
        onChange={e => setState(s => ({ ...s, end: parseFloat(e.target.value) }))} />
      <input style={addInput(70)} placeholder="Уклон ‰" type="number" step="0.1" value={state.angle ?? ''}
        onChange={e => setState(s => ({ ...s, angle: parseFloat(e.target.value) }))} />
      <button onClick={() => {
        if (state.start == null || state.end == null || state.angle == null) return
        onAdd({ start: state.start, end: state.end, angle: state.angle })
        setState({})
      }} style={{ padding: '4px 10px', background: '#10b981', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontFamily: 'inherit' }}>
        + Добавить
      </button>
    </div>
  )
}

function AddSpeedRow({ onAdd, state, setState }: {
  onAdd: (r: SRow) => void
  state: Partial<SRow>
  setState: React.Dispatch<React.SetStateAction<Partial<SRow>>>
}) {
  return (
    <div style={addRowStyle}>
      <input style={addInput(110)} placeholder="Начало м" type="number" value={state.start ?? ''}
        onChange={e => setState(s => ({ ...s, start: parseFloat(e.target.value) }))} />
      <input style={addInput(110)} placeholder="Конец м" type="number" value={state.end ?? ''}
        onChange={e => setState(s => ({ ...s, end: parseFloat(e.target.value) }))} />
      <input style={addInput(60)} placeholder="V км/ч" type="number" value={state.limit ?? ''}
        onChange={e => setState(s => ({ ...s, limit: parseInt(e.target.value, 10) }))} />
      <input style={addInput(120)} placeholder="Тип" value={state.type ?? 'track_category'}
        onChange={e => setState(s => ({ ...s, type: e.target.value }))} />
      <button onClick={() => {
        if (state.start == null || state.end == null || state.limit == null) return
        onAdd({ start: state.start, end: state.end, limit: state.limit, type: state.type ?? 'track_category' })
        setState({})
      }} style={{ padding: '4px 10px', background: '#10b981', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontFamily: 'inherit' }}>
        + Добавить
      </button>
    </div>
  )
}

function AddStationRow({ onAdd, state, setState }: {
  onAdd: (r: StRow) => void
  state: Partial<StRow>
  setState: React.Dispatch<React.SetStateAction<Partial<StRow>>>
}) {
  return (
    <div style={addRowStyle}>
      <input style={addInput(140)} placeholder="Название" value={state.name ?? ''}
        onChange={e => setState(s => ({ ...s, name: e.target.value }))} />
      <input style={addInput(120)} placeholder="Координата м" type="number" value={state.coordinate ?? ''}
        onChange={e => setState(s => ({ ...s, coordinate: parseFloat(e.target.value) }))} />
      <button onClick={() => {
        if (!state.name || state.coordinate == null) return
        onAdd({ name: state.name, coordinate: state.coordinate, graphical: {} })
        setState({})
      }} style={{ padding: '4px 10px', background: '#10b981', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontFamily: 'inherit' }}>
        + Добавить
      </button>
    </div>
  )
}

function AddMarkRow({ onAdd, state, setState }: {
  onAdd: (r: MRow) => void
  state: Partial<MRow>
  setState: React.Dispatch<React.SetStateAction<Partial<MRow>>>
}) {
  return (
    <div style={addRowStyle}>
      <select style={{ ...addInput(150), padding: '4px 4px' }}
        value={state.subtype ?? MARK_SUBTYPES[0].subtype}
        onChange={e => setState(s => ({ ...s, subtype: e.target.value }))}
      >
        {MARK_SUBTYPES.map(m => <option key={m.subtype} value={m.subtype}>{m.label}</option>)}
      </select>
      <input style={addInput(120)} placeholder="Координата м" type="number" value={state.coordinate ?? ''}
        onChange={e => setState(s => ({ ...s, coordinate: parseFloat(e.target.value) }))} />
      <button onClick={() => {
        const sub = state.subtype ?? MARK_SUBTYPES[0].subtype
        if (state.coordinate == null) return
        onAdd({ subtype: sub, coordinate: state.coordinate, x: 0, y: 0, meta: {} })
        setState({})
      }} style={{ padding: '4px 10px', background: '#10b981', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontFamily: 'inherit' }}>
        + Добавить
      </button>
    </div>
  )
}

// suppress unused import warning
void fmtM
