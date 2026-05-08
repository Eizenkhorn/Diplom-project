import { useState } from 'react'
import type { ExtractionResult, ProfileSegment, SpeedLimitSegment } from '../types'
import { extractSession, exportSession } from '../api'

interface Props {
  sessionId: string
  onClose: () => void
}

export default function ExtractionPanel({ sessionId, onClose }: Props) {
  const [result, setResult] = useState<ExtractionResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showDiag, setShowDiag] = useState(false)

  async function handleExtract() {
    setLoading(true)
    setError(null)
    try {
      const data = await extractSession(sessionId)
      setResult(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  async function handleExport() {
    try {
      const data = await exportSession(sessionId)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `export_${sessionId.slice(0, 8)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const log = result?.extraction_log

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: '#fff', borderRadius: 12, width: 720, maxWidth: '95vw',
        maxHeight: '90vh', display: 'flex', flexDirection: 'column',
        boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
      }}>
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '16px 20px', borderBottom: '1px solid #e2e8f0',
        }}>
          <span style={{ fontWeight: 700, fontSize: 15, color: '#1e293b' }}>
            Извлечение данных
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            {result && (
              <button onClick={handleExport} style={btnStyle('#10b981')}>
                Скачать JSON
              </button>
            )}
            <button
              onClick={handleExtract}
              disabled={loading}
              style={btnStyle(loading ? '#94a3b8' : '#3b82f6')}
            >
              {loading ? 'Извлекаю…' : result ? 'Повторить' : 'Извлечь'}
            </button>
            <button onClick={onClose} style={btnStyle('#64748b')}>✕</button>
          </div>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
          {error && (
            <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 8, padding: '10px 14px', marginBottom: 16, color: '#dc2626', fontSize: 13 }}>
              {error}
            </div>
          )}

          {!result && !loading && (
            <div style={{ color: '#94a3b8', textAlign: 'center', padding: '40px 0', fontSize: 14 }}>
              Нажмите «Извлечь» чтобы запустить автоматическое извлечение данных из размеченных полос.
            </div>
          )}

          {loading && (
            <div style={{ color: '#64748b', textAlign: 'center', padding: '40px 0', fontSize: 14 }}>
              Обработка…
            </div>
          )}

          {result && log && (
            <>
              {/* Extraction summary */}
              <Section title="Сводка">
                <SummaryGrid log={log} />
              </Section>

              {/* Warnings */}
              {log.warnings.length > 0 && (
                <Section title={`Предупреждения (${log.warnings.length})`} accent="#f59e0b">
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {log.warnings.map((w, i) => (
                      <li key={i} style={{ fontSize: 12, color: '#92400e', marginBottom: 4 }}>{w}</li>
                    ))}
                  </ul>
                </Section>
              )}

              {/* Profile table */}
              {result.profile.length > 0 && (
                <Section title={`Профиль пути (${result.profile.length} сегментов, ${Math.round(log.profile.total_length_meters / 1000)} км)`}>
                  <DataTable
                    headers={['№', 'Начало м', 'Конец м', 'Уклон ‰']}
                    rows={result.profile.map((s, i) => [
                      String(i + 1),
                      String(Math.round(s.start)),
                      String(Math.round(s.end)),
                      String(s.angle),
                    ])}
                  />
                </Section>
              )}

              {/* Speed limits table */}
              {result.speedLimits.length > 0 && (
                <Section title={`Ограничения скорости (${result.speedLimits.length} сегментов)`}>
                  <DataTable
                    headers={['Нач. км×1000', 'Кон. км×1000', 'V км/ч', 'Тип']}
                    rows={result.speedLimits.map((s) => [
                      String(Math.round(s.start)),
                      String(Math.round(s.end)),
                      String(s.limit),
                      s.type,
                    ])}
                  />
                </Section>
              )}

              {/* Stations */}
              {result.stations.length > 0 && (
                <Section title={`Станции (${result.stations.length})`}>
                  <DataTable
                    headers={['Название', 'Координата (м)']}
                    rows={result.stations.map((st) => [st.name, String(st.coordinate)])}
                  />
                </Section>
              )}

              {/* Coordinate ruler */}
              {result.coordinateRuler.segments.length > 0 && (
                <Section title="Координатная шкала">
                  <DataTable
                    headers={['Начало км', 'Конец км']}
                    rows={result.coordinateRuler.segments.map((s) => [
                      String(s.startCoordinate),
                      String(s.endCoordinate),
                    ])}
                  />
                </Section>
              )}

              {/* Diagnostics (collapsible) */}
              <div style={{ marginBottom: 20 }}>
                <button
                  onClick={() => setShowDiag((v) => !v)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    background: 'none', border: 'none', cursor: 'pointer',
                    padding: '4px 0', color: '#64748b', fontSize: 11, fontWeight: 700,
                    textTransform: 'uppercase', letterSpacing: '0.06em', fontFamily: 'inherit',
                  }}
                >
                  <span style={{ fontSize: 12 }}>{showDiag ? '▾' : '▸'}</span>
                  Диагностика
                </button>
                {showDiag && (
                  <div style={{ marginTop: 8 }}>
                    <DiagSection title="Координатная шкала" entries={[
                      ['Фигуры в полосе (Y)', String(log.coordinate_ruler.shapes_in_band_y)],
                      ['Фигуры в полосе (X+Y)', String(log.coordinate_ruler.shapes_in_band_xy)],
                      ['Кандидаты-километры', String(log.coordinate_ruler.kilometer_candidates)],
                      ['Уникальных значений', String(log.coordinate_ruler.unique_values)],
                      ['Отброшено (дубли)', String(log.coordinate_ruler.rejected_duplicate_values)],
                      ...(log.coordinate_ruler.rejected_values_list.length > 0
                        ? [['Отброшенные значения', log.coordinate_ruler.rejected_values_list.join(', ')]] as [string, string][]
                        : []),
                      ['Монотонных точек', String(log.coordinate_ruler.monotone_points)],
                      ['Итого км-меток', String(log.coordinate_ruler.found_kilometers)],
                      ['Направление', log.coordinate_ruler.direction ?? '—'],
                      ['Диапазон км', log.coordinate_ruler.range ? `${log.coordinate_ruler.range[0]}–${log.coordinate_ruler.range[1]}` : '—'],
                    ]} />
                    <DiagSection title="Профиль пути" entries={[
                      ['Фигуры в полосе (Y)', String(log.profile.shapes_in_band_y)],
                      ['Фигуры в полосе (X+Y)', String(log.profile.shapes_in_band_xy)],
                      ['Углы', String(log.profile.angle_count)],
                      ['Длины', String(log.profile.length_count)],
                      ['Нераспознанных', String(log.profile.unclassified_count)],
                      ['Сегментов', String(log.profile.found_segments)],
                      ['Суммарная длина', `${Math.round(log.profile.total_length_meters)} м`],
                    ]} />
                    <DiagSection title="Ограничения скорости" entries={[
                      ['Фигур в полосе', String(log.speed_limits.shapes_in_band)],
                      ['Меток шкалы (сырых)', String(log.speed_limits.scale_labels_raw)],
                      ['Меток шкалы (после дедупл.)', String(log.speed_limits.scale_labels_deduped)],
                      ['Скорости шкалы', log.speed_limits.scale_speeds.join(', ') || '—'],
                      ['Линий-кандидатов', String(log.speed_limits.candidate_line_shapes)],
                      ['Красных линий', String(log.speed_limits.red_lines)],
                      ['Прочих линий', String(log.speed_limits.other_lines)],
                      ['Фильтр по цвету', log.speed_limits.used_color_filter ? 'да' : 'нет'],
                      ['Сырых сегментов', String(log.speed_limits.raw_segments)],
                      ['Итого сегментов', String(log.speed_limits.found_segments)],
                    ]} />
                    <DiagSection title="Станции" entries={[
                      ['Количество', String(log.stations.count)],
                      ['Координаты (м)', log.stations.coordinates.length > 0
                        ? log.stations.coordinates.slice(0, 10).join(', ') + (log.stations.coordinates.length > 10 ? '…' : '')
                        : '—'],
                    ]} />
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── helpers ───────────────────────────────────────────────────────────────────

function btnStyle(bg: string): React.CSSProperties {
  return {
    padding: '6px 14px', background: bg, color: '#fff',
    border: 'none', borderRadius: 6, cursor: 'pointer',
    fontSize: 12, fontWeight: 500, fontFamily: 'inherit',
  }
}

function Section({ title, accent, children }: { title: string; accent?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{
        fontSize: 11, fontWeight: 700, color: accent ?? '#64748b',
        textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8,
      }}>
        {title}
      </div>
      {children}
    </div>
  )
}

function DiagSection({ title, entries }: { title: string; entries: [string, string][] }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8', marginBottom: 4, textTransform: 'uppercase' }}>
        {title}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 8px' }}>
        {entries.map(([k, v]) => (
          <div key={k} style={{ display: 'contents' }}>
            <span style={{ fontSize: 11, color: '#64748b', padding: '2px 0' }}>{k}</span>
            <span style={{ fontSize: 11, color: '#1e293b', fontWeight: 500, padding: '2px 0', wordBreak: 'break-all' }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function SummaryGrid({ log }: { log: ExtractionResult['extraction_log'] }) {
  const items = [
    { label: 'Км-отметки', value: log.coordinate_ruler.found_kilometers + (log.coordinate_ruler.range ? ` (${log.coordinate_ruler.range[0]}–${log.coordinate_ruler.range[1]} км)` : ''), ok: log.coordinate_ruler.found_kilometers >= 2 },
    { label: 'Направление', value: log.coordinate_ruler.direction ?? '—', ok: !!log.coordinate_ruler.direction },
    { label: 'Сегменты профиля', value: String(log.profile.found_segments), ok: log.profile.found_segments > 0 },
    { label: 'Длина участка', value: log.profile.total_length_meters > 0 ? `${Math.round(log.profile.total_length_meters / 1000)} км` : '—', ok: log.profile.total_length_meters > 0 },
    { label: 'Ограничения скорости', value: String(log.speed_limits.found_segments), ok: log.speed_limits.found_segments > 0 },
    { label: 'Шкала скоростей', value: log.speed_limits.scale_speeds.join(', ') || '—', ok: log.speed_limits.scale_speeds.length > 0 },
    { label: 'Станции', value: String(log.stations.count), ok: log.stations.count > 0 },
  ]
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
      {items.map((it) => (
        <div key={it.label} style={{
          background: it.ok ? '#f0fdf4' : '#fafafa',
          border: `1px solid ${it.ok ? '#bbf7d0' : '#e2e8f0'}`,
          borderRadius: 6, padding: '8px 12px',
        }}>
          <div style={{ fontSize: 10, color: '#94a3b8', fontWeight: 600, marginBottom: 2 }}>{it.label}</div>
          <div style={{ fontSize: 12, color: '#1e293b', fontWeight: 500 }}>{it.value}</div>
        </div>
      ))}
    </div>
  )
}

function DataTable({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h} style={{ padding: '5px 8px', background: '#f8fafc', border: '1px solid #e2e8f0', textAlign: 'left', fontWeight: 600, color: '#64748b' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 200).map((row, i) => (
            <tr key={i} style={{ background: i % 2 ? '#f8fafc' : '#fff' }}>
              {row.map((cell, j) => (
                <td key={j} style={{ padding: '4px 8px', border: '1px solid #e2e8f0', color: '#1e293b' }}>{cell}</td>
              ))}
            </tr>
          ))}
          {rows.length > 200 && (
            <tr>
              <td colSpan={headers.length} style={{ padding: '4px 8px', color: '#94a3b8', fontStyle: 'italic' }}>
                …и ещё {rows.length - 200} строк
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
