export const MARK_SUBTYPE_LABELS: Record<string, string> = {
  entry_signal:        'Входной светофор',
  exit_signal:         'Выходной светофор',
  route_signal:        'Маршрутный светофор',
  passing_signal:      'Проходной светофор',
  crossing_guarded:    'Переезд охраняемый',
  crossing_unguarded:  'Переезд неохраняемый',
  neutral_insert:      'Нейтральная вставка',
  ktsm:                'КТСМ',
  uksps:               'УКСПС',
  bridge:              'Мост',
  brake_marker:        'Тормозной ориентир',
  station_axis:        'Ось станции',
}

export function getMarkSubtypeLabel(subtype: string): string {
  return MARK_SUBTYPE_LABELS[subtype] ?? subtype
}
