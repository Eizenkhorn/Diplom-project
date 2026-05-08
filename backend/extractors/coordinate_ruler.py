"""Extract coordinate ruler (kilometrage scale) from a marked horizontal band."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel

from models.markup import HorizontalBand, WorkArea
from models.parsed import ParsedShape

_KM_RE = re.compile(r"^\s*(\d{1,4})\s*$")  # integer 1-9999


def _shape_center_x(s: ParsedShape) -> float:
    return s.x + s.width / 2


def _shape_center_y(s: ParsedShape) -> float:
    return s.y + s.height / 2


def _in_band_y(s: ParsedShape, band: HorizontalBand) -> bool:
    cy = _shape_center_y(s)
    return band.y_top <= cy <= band.y_bottom


def _in_work_area_x(s: ParsedShape, wa: WorkArea) -> bool:
    cx = _shape_center_x(s)
    return wa.x_start <= cx <= wa.x_end


class CoordinateMapping(BaseModel):
    """Pixel-to-network-coordinate mapping built from the coordinate ruler band."""

    points: list[tuple[float, int]]          # sorted by x_px; (x_px, kilometer)
    direction: Literal["ascending", "descending"]

    def x_to_network_coord(self, x: float) -> float:
        """Linearly interpolate (or extrapolate) pixel X → network metres (km × 1000)."""
        pts = self.points
        if not pts:
            return 0.0
        if len(pts) == 1:
            return pts[0][1] * 1000.0

        # Clamp extrapolation to the nearest edge segment
        if x <= pts[0][0]:
            x1, k1 = pts[0]
            x2, k2 = pts[1]
        elif x >= pts[-1][0]:
            x1, k1 = pts[-2]
            x2, k2 = pts[-1]
        else:
            for i in range(len(pts) - 1):
                if pts[i][0] <= x <= pts[i + 1][0]:
                    x1, k1 = pts[i]
                    x2, k2 = pts[i + 1]
                    break
            else:
                x1, k1 = pts[-2]
                x2, k2 = pts[-1]

        if x2 == x1:
            return k1 * 1000.0
        t = (x - x1) / (x2 - x1)
        result = (k1 + t * (k2 - k1)) * 1000.0
        if not (result == result):  # NaN check
            return k1 * 1000.0
        return result


def extract_coordinate_ruler(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    work_area: WorkArea,
    km_hint_start: Optional[int] = None,
    km_hint_end: Optional[int] = None,
) -> tuple[CoordinateMapping, dict, list[str]]:
    """Parse the coordinate ruler band into a CoordinateMapping.

    Algorithm:
    1. Collect text shapes inside band Y range and work area X range.
    2. Parse integer km labels; group by value.
    3. Reject values appearing ≥2 times (speed-scale contamination).
    4. Sort unique values by X; filter to monotone subsequence.
    5. If km hints provided and no labels detected, use them as fallback anchors.

    Returns (mapping, log_dict, warnings).
    """
    warnings: list[str] = []

    # ── 1. Filter shapes ─────────────────────────────────────────────────────────
    shapes_in_band_y = [s for s in shapes if s.text is not None and _in_band_y(s, band)]
    candidates = [s for s in shapes_in_band_y if _in_work_area_x(s, work_area)]

    log: dict = {
        "shapes_in_band_y": len(shapes_in_band_y),
        "shapes_in_band_xy": len(candidates),
        "kilometer_candidates": 0,
        "unique_values": 0,
        "rejected_duplicate_values": 0,
        "rejected_values_list": [],
        "monotone_points": 0,
        "found_kilometers": 0,
        "direction": None,
        "range": None,
    }

    # ── 2. Parse integer km labels; group by value ───────────────────────────────
    value_map: dict[int, list[float]] = {}  # km_value -> list[cx]
    for s in candidates:
        m = _KM_RE.match(s.text or "")
        if not m:
            continue
        km = int(m.group(1))
        if not (1 <= km <= 9999):
            continue
        value_map.setdefault(km, []).append(_shape_center_x(s))

    log["kilometer_candidates"] = sum(len(v) for v in value_map.values())

    # ── 3. Reject non-unique values (≥2 occurrences = speed-scale contamination) ─
    rejected_values: list[int] = []
    unique_points: list[tuple[float, int]] = []  # (cx, km)
    for km in sorted(value_map.keys()):
        occurrences = value_map[km]
        if len(occurrences) >= 2:
            rejected_values.append(km)
        else:
            unique_points.append((occurrences[0], km))

    log["unique_values"] = len(unique_points)
    log["rejected_duplicate_values"] = len(rejected_values)
    log["rejected_values_list"] = rejected_values[:20]

    if rejected_values:
        warnings.append(
            f"coordinate_ruler: rejected {len(rejected_values)} non-unique value(s) "
            f"(likely speed-scale contamination): {rejected_values[:10]}"
        )

    # Sort by X position
    unique_points.sort(key=lambda p: p[0])

    # ── 4. Monotone subsequence filter ───────────────────────────────────────────
    if len(unique_points) >= 2:
        tentative_dir: Literal["ascending", "descending"] = (
            "ascending" if unique_points[-1][1] > unique_points[0][1] else "descending"
        )
    else:
        tentative_dir = "ascending"

    mono: list[tuple[float, int]] = []
    for x, km in unique_points:
        if not mono:
            mono.append((x, km))
            continue
        last_km = mono[-1][1]
        if tentative_dir == "ascending":
            if km > last_km:
                mono.append((x, km))
        else:
            if km < last_km:
                mono.append((x, km))

    dropped = len(unique_points) - len(mono)
    if dropped:
        warnings.append(
            f"coordinate_ruler: dropped {dropped} non-monotone point(s) after uniqueness filter"
        )

    log["monotone_points"] = len(mono)
    points = mono

    # ── 5. Apply km hints as anchors if provided ─────────────────────────────────
    if km_hint_start is not None and km_hint_end is not None and work_area:
        if not points:
            points = [
                (work_area.x_start, km_hint_start),
                (work_area.x_end, km_hint_end),
            ]
            warnings.append(
                f"coordinate_ruler: no km labels detected — using hints "
                f"({km_hint_start}–{km_hint_end} km)"
            )
        else:
            kms = [km for _, km in points]
            hint_min = min(km_hint_start, km_hint_end)
            hint_max = max(km_hint_start, km_hint_end)
            # If detected range does not overlap with hint range at all, override
            if max(kms) < hint_min or min(kms) > hint_max:
                points = [
                    (work_area.x_start, km_hint_start),
                    (work_area.x_end, km_hint_end),
                ]
                warnings.append(
                    "coordinate_ruler: detected km range doesn't match hints — "
                    "overriding with hint anchors"
                )

    # ── 6. Determine direction ────────────────────────────────────────────────────
    if len(points) >= 2:
        direction: Literal["ascending", "descending"] = (
            "ascending" if points[-1][1] > points[0][1] else "descending"
        )
    else:
        direction = "ascending"
        warnings.append(
            f"coordinate_ruler: found only {len(points)} km label(s) "
            f"(need ≥ 2 for interpolation)"
        )

    # Remove duplicate X positions (keep first)
    deduped: list[tuple[float, int]] = []
    seen_x: set[int] = set()
    for x, km in points:
        ix = round(x)
        if ix not in seen_x:
            deduped.append((x, km))
            seen_x.add(ix)
    points = deduped

    # ── 7. Final log ──────────────────────────────────────────────────────────────
    log["found_kilometers"] = len(points)
    log["direction"] = direction
    if points:
        kms_final = [km for _, km in points]
        log["range"] = [min(kms_final), max(kms_final)]

    mapping = CoordinateMapping(points=points, direction=direction)
    return mapping, log, warnings
