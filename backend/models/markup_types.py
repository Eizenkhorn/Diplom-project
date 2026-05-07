from typing import Any

BAND_TYPES: list[dict[str, Any]] = [
    {"type": "speed_limits",    "label": "Ограничения скорости", "color": "#ef4444",  "is_informational": False},
    {"type": "profile",         "label": "Профиль пути",         "color": "#10b981",  "is_informational": False},
    {"type": "track_plan",      "label": "План пути",            "color": "#f59e0b",  "is_informational": False},
    {"type": "traction_modes",  "label": "Режимы тяги",          "color": "#a855f7",  "is_informational": False},
    {"type": "coordinate_ruler","label": "Координатная шкала",   "color": "#6b7280",  "is_informational": False},
    {"type": "path_schema",     "label": "Схема пути",           "color": "#fbbf24",  "is_informational": True},
]

MARK_SUBTYPES: list[dict[str, Any]] = [
    {"subtype": "entry_signal",      "label": "Входной светофор",     "color": "#ef4444"},
    {"subtype": "exit_signal",       "label": "Выходной светофор",    "color": "#f97316"},
    {"subtype": "route_signal",      "label": "Маршрутный светофор",  "color": "#eab308"},
    {"subtype": "passing_signal",    "label": "Проходной светофор",   "color": "#22c55e"},
    {"subtype": "crossing_guarded",  "label": "Переезд",              "color": "#06b6d4"},
    {"subtype": "neutral_insert",    "label": "Нейтральная вставка",  "color": "#8b5cf6"},
    {"subtype": "ktsm",              "label": "КТСМ",                 "color": "#ec4899"},
    {"subtype": "uksps",             "label": "УКСПС",                "color": "#14b8a6"},
    {"subtype": "bridge",            "label": "Мост",                 "color": "#64748b"},
    {"subtype": "brake_marker",      "label": "Тормозной ориентир",   "color": "#dc2626"},
    {"subtype": "station_axis",      "label": "Ось станции",          "color": "#3b82f6"},
]

VALID_BAND_TYPES: frozenset[str] = frozenset(b["type"] for b in BAND_TYPES)
INFORMATIONAL_BAND_TYPES: frozenset[str] = frozenset(b["type"] for b in BAND_TYPES if b["is_informational"])
VALID_MARK_SUBTYPES: frozenset[str] = frozenset(m["subtype"] for m in MARK_SUBTYPES)
