"""Convert user-marked station points to the target JSON station format."""
from __future__ import annotations

from extractors.coordinate_ruler import CoordinateMapping
from models.markup import StationPoint


def extract_stations(
    station_points: list[StationPoint],
    coord_mapping: CoordinateMapping,
) -> tuple[list[dict], dict, list[str]]:
    """Convert markup StationPoints to target JSON station dicts.

    The `coordinate` field is in network metres (km × 1000), matching the
    coordinate system of speedLimits.start/end.

    Returns (stations, log_dict, warnings).
    """
    warnings: list[str] = []
    stations: list[dict] = []

    def _safe_round(v: float) -> int:
        if v != v or v == float("inf") or v == float("-inf"):
            return 0
        return round(v)

    for sp in station_points:
        net_coord = _safe_round(coord_mapping.x_to_network_coord(sp.x))

        station = {
            "name": sp.name,
            "coordinate": net_coord,
            "graphical": {
                "layerPosition": 0,
                "coordinate": net_coord,
                "horizontalOffset": 0,
                "verticalPositionPercent": 50,
                "fontSize": 11,
                "fontColor": "#374151",
                "lineHeight": 14,
                "rotation": 0,
                "objectColor": "#1d4ed8",
            },
        }
        stations.append(station)

    # Sort by coordinate (descending if ruler is descending, ascending otherwise)
    if coord_mapping.direction == "descending" and stations:
        stations.sort(key=lambda s: s["coordinate"], reverse=True)
    elif stations:
        stations.sort(key=lambda s: s["coordinate"])

    if not stations:
        warnings.append("stations: no station points marked")

    log = {
        "count": len(stations),
        "coordinates": [s["coordinate"] for s in stations],
    }
    return stations, log, warnings
