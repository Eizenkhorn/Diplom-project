from typing import Any

ANNOTATION_TYPES: list[dict[str, Any]] = [
    {
        "type": "speed_limits",
        "label": "Ограничения скорости",
        "color": "#ef4444",
        "json_field": "speedLimits",
        "description": "Красная огибающая линия по верхним черным штрихам",
    },
    {
        "type": "traction_modes",
        "label": "Режимы тяги",
        "color": "#a855f7",
        "json_field": "locomotiveRegimeBands",
        "description": "Стрелки Тяга 2С / Тяга С / Р/т СП в верхней части карты",
    },
    {
        "type": "stations",
        "label": "Станции",
        "color": "#3b82f6",
        "json_field": "stations",
        "description": "Названия станций и раздельных пунктов",
    },
    {
        "type": "coordinate_ruler",
        "label": "Координатная шкала",
        "color": "#6b7280",
        "json_field": "coordinateRuler",
        "description": "Черная полоса с километровыми отметками",
    },
    {
        "type": "profile",
        "label": "Профиль пути",
        "color": "#10b981",
        "json_field": "profile",
        "description": "Углы уклонов в ‰ и длины сегментов под километровой шкалой",
    },
    {
        "type": "track_plan",
        "label": "План пути",
        "color": "#f59e0b",
        "json_field": "trackPlan",
        "description": "Синяя ступенчатая ломаная, отображающая план",
    },
    {
        "type": "marks",
        "label": "Метки и сигналы",
        "color": "#eab308",
        "json_field": "marks",
        "description": "Светофоры, треугольники, иконки путевых объектов",
    },
    {
        "type": "unknown",
        "label": "Не определено",
        "color": "#9ca3af",
        "json_field": None,
        "description": "Регион требует уточнения типа",
    },
]

VALID_REGION_TYPES: frozenset[str] = frozenset(t["type"] for t in ANNOTATION_TYPES)
