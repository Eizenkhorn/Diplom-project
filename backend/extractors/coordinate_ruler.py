"""Extract coordinate ruler from a marked horizontal band.

v2: supports multiple km-systems on one map (piecewise-linear CoordinateMapping).
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel

from models.markup import HorizontalBand, WorkArea
from models.parsed import ParsedShape

_KM_RE = re.compile(r"^\s*(\d{1,4})\s*$")

_MAX_KM_GAP = 50
_MAX_MONO_VIOLATION = 0.30


def _cx(s: ParsedShape) -> float:
    return s.x + s.width / 2


def _cy(s: ParsedShape) -> float:
    return s.y + s.height / 2


class CoordSegment(BaseModel):
    """One contiguous km-system segment."""

    points: list[tuple[float, int]]
    direction: Literal["ascending", "descending"]

    def interpolate(self, x: float) -> float:
        pts = self.points
        if not pts:
            return 0.0
        if len(pts) == 1:
            return pts[0][1] * 1000.0
        if x <= pts[0][0]:
            x1, k1 = pts[0]; x2, k2 = pts[1]
        elif x >= pts[-1][0]:
            x1, k1 = pts[-2]; x2, k2 = pts[-1]
        else:
            for i in range(len(pts) - 1):
                if pts[i][0] <= x <= pts[i + 1][0]:
                    x1, k1 = pts[i]; x2, k2 = pts[i + 1]
                    break
            else:
                x1, k1 = pts[-2]; x2, k2 = pts[-1]
        if x2 == x1:
            return k1 * 1000.0
        return (k1 + (x - x1) / (x2 - x1) * (k2 - k1)) * 1000.0


class CoordinateMapping(BaseModel):
    """Piecewise-linear km mapping built from one or more CoordSegment objects."""

    segments: list[CoordSegment]

    @property
    def points(self) -> list[tuple[float, int]]:
        result: list[tuple[float, int]] = []
        for seg in self.segments:
            result.extend(seg.points)
        result.sort(key=lambda p: p[0])
        return result

    @property
    def direction(self) -> Literal["ascending", "descending"]:
        return self.segments[0].direction if self.segments else "ascending"

    def _seg_for_x(self, x: float) -> Optional[CoordSegment]:
        for seg in self.segments:
            if seg.points and seg.points[0][0] <= x <= seg.points[-1][0]:
                return seg
        return None

    def _seg_idx_for_network_m(self, m: float) -> int:
        km = m / 1000.0
        for i, seg in enumerate(self.segments):
            kms = [k for _, k in seg.points]
            if not kms:
                continue
            if min(kms) <= km <= max(kms):
                return i
        return -1

    def crosses_km_boundary(self, start_m: float, end_m: float) -> bool:
        if len(self.segments) <= 1:
            return False
        si = self._seg_idx_for_network_m(start_m)
        ei = self._seg_idx_for_network_m(end_m)
        return si >= 0 and ei >= 0 and si != ei

    def x_to_network_coord(self, x: float) -> float:
        if not self.segments:
            return 0.0
        seg = self._seg_for_x(x)
        if seg is not None:
            return seg.interpolate(x)
        nearest = min(
            self.segments,
            key=lambda s: min(
                abs(x - s.points[0][0]) if s.points else float("inf"),
                abs(x - s.points[-1][0]) if s.points else float("inf"),
            ),
        )
        return nearest.interpolate(x)


def _split_by_gap(pts: list[tuple[float, int]]) -> list[list[tuple[float, int]]]:
    if not pts:
        return []
    groups: list[list[tuple[float, int]]] = [[pts[0]]]
    for item in pts[1:]:
        if abs(item[1] - groups[-1][-1][1]) > _MAX_KM_GAP:
            groups.append([item])
        else:
            groups[-1].append(item)
    return groups


def _direction_and_violations(
    pts: list[tuple[float, int]],
) -> tuple[Literal["ascending", "descending"], float]:
    if len(pts) < 2:
        return "ascending", 0.0
    diffs = [pts[i + 1][1] - pts[i][1] for i in range(len(pts) - 1)]
    pos = sum(1 for d in diffs if d > 0)
    neg = sum(1 for d in diffs if d < 0)
    direction: Literal["ascending", "descending"] = "ascending" if pos >= neg else "descending"
    violations = neg if direction == "ascending" else pos
    return direction, violations / len(diffs)


def _to_monotone(
    pts: list[tuple[float, int]],
    direction: Literal["ascending", "descending"],
) -> list[tuple[float, int]]:
    mono: list[tuple[float, int]] = []
    for x, km in pts:
        if not mono:
            mono.append((x, km))
            continue
        last_km = mono[-1][1]
        if (direction == "ascending" and km > last_km) or (
            direction == "descending" and km < last_km
        ):
            mono.append((x, km))
    return mono


def _dedup_x(pts: list[tuple[float, int]]) -> list[tuple[float, int]]:
    seen: set[int] = set()
    result: list[tuple[float, int]] = []
    for x, km in pts:
        ix = round(x)
        if ix not in seen:
            seen.add(ix)
            result.append((x, km))
    return result


def extract_coordinate_ruler(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    work_area: WorkArea,
    km_hint_start: Optional[int] = None,
    km_hint_end: Optional[int] = None,
) -> tuple[CoordinateMapping, dict, list[str]]:
    warnings: list[str] = []

    shapes_in_y = [
        s for s in shapes
        if s.text is not None and band.y_top <= _cy(s) <= band.y_bottom
    ]
    candidates = [s for s in shapes_in_y if work_area.x_start <= _cx(s) <= work_area.x_end]

    log: dict = {
        "shapes_in_band_y": len(shapes_in_y),
        "shapes_in_band_xy": len(candidates),
        "kilometer_candidates": 0,
        "unique_values": 0,
        "rejected_duplicate_values": 0,
        "rejected_values_list": [],
        "monotone_points": 0,
        "found_kilometers": 0,
        "direction": None,
        "range": None,
        "segments_detected": 0,
        "segments_details": [],
        "gaps_found": [],
        "missing_kilometers_in_segments": [],
        "rejected_non_monotonic_segments": [],
    }

    value_map: dict[int, list[float]] = {}
    for s in candidates:
        m = _KM_RE.match(s.text or "")
        if not m:
            continue
        km = int(m.group(1))
        if not (1 <= km <= 9999):
            continue
        value_map.setdefault(km, []).append(_cx(s))

    log["kilometer_candidates"] = sum(len(v) for v in value_map.values())

    rejected_vals: list[int] = []
    unique_pts: list[tuple[float, int]] = []
    for km in sorted(value_map):
        occ = value_map[km]
        if len(occ) >= 2:
            rejected_vals.append(km)
        else:
            unique_pts.append((occ[0], km))

    log["unique_values"] = len(unique_pts)
    log["rejected_duplicate_values"] = len(rejected_vals)
    log["rejected_values_list"] = rejected_vals[:20]
    if rejected_vals:
        warnings.append(
            f"coordinate_ruler: rejected {len(rejected_vals)} duplicate km value(s) "
            f"(likely speed-scale contamination): {rejected_vals[:10]}"
        )

    unique_pts.sort(key=lambda p: p[0])
    raw_groups = _split_by_gap(unique_pts)

    for i in range(len(raw_groups) - 1):
        last = raw_groups[i][-1]
        nxt = raw_groups[i + 1][0]
        log["gaps_found"].append({
            "between_x": [round(last[0], 1), round(nxt[0], 1)],
            "from_km": last[1],
            "to_km": nxt[1],
            "delta": abs(nxt[1] - last[1]),
        })

    valid_segments: list[CoordSegment] = []
    missing_kms: list[int] = []

    for raw in raw_groups:
        if len(raw) < 2:
            continue
        direction, viol = _direction_and_violations(raw)
        if viol >= _MAX_MONO_VIOLATION:
            log["rejected_non_monotonic_segments"].append({
                "points_count": len(raw),
                "violation_ratio": round(viol, 2),
                "km_range": [raw[0][1], raw[-1][1]],
            })
            warnings.append(
                f"coordinate_ruler: rejected non-monotonic segment "
                f"({len(raw)} pts, {viol:.0%} violations) "
                f"km {raw[0][1]}–{raw[-1][1]}"
            )
            continue

        mono = _to_monotone(raw, direction)
        mono = _dedup_x(mono)
        if not mono:
            continue

        for j in range(len(mono) - 1):
            _, k1 = mono[j]; _, k2 = mono[j + 1]
            gap = abs(k2 - k1)
            if 1 < gap <= 3:
                step = 1 if k2 > k1 else -1
                missing_kms.extend(range(k1 + step, k2, step))

        log["segments_details"].append({
            "kilometer_range": [mono[0][1], mono[-1][1]],
            "x_range": [round(mono[0][0], 1), round(mono[-1][0], 1)],
            "direction": direction,
            "points_count": len(mono),
        })
        valid_segments.append(CoordSegment(points=mono, direction=direction))

    log["missing_kilometers_in_segments"] = missing_kms[:50]

    if not valid_segments and km_hint_start is not None and km_hint_end is not None:
        hint_dir: Literal["ascending", "descending"] = (
            "ascending" if km_hint_end >= km_hint_start else "descending"
        )
        valid_segments = [CoordSegment(
            points=[(work_area.x_start, km_hint_start), (work_area.x_end, km_hint_end)],
            direction=hint_dir,
        )]
        warnings.append(
            f"coordinate_ruler: no km labels detected — using hints "
            f"({km_hint_start}–{km_hint_end} km)"
        )
        log["segments_details"].append({
            "kilometer_range": [km_hint_start, km_hint_end],
            "x_range": [round(work_area.x_start, 1), round(work_area.x_end, 1)],
            "direction": hint_dir,
            "points_count": 2,
        })

    if not valid_segments:
        warnings.append(
            f"coordinate_ruler: found 0 valid km segments "
            f"(unique candidates: {len(unique_pts)})"
        )
        dx = max(1, int((work_area.x_end - work_area.x_start) // 1000))
        valid_segments = [CoordSegment(
            points=[(work_area.x_start, 0), (work_area.x_end, dx)],
            direction="ascending",
        )]

    all_pts = [p for seg in valid_segments for p in seg.points]
    log["monotone_points"] = len(all_pts)
    log["found_kilometers"] = len(all_pts)
    log["segments_detected"] = len(valid_segments)
    log["direction"] = valid_segments[0].direction
    all_kms = [km for _, km in all_pts]
    log["range"] = [min(all_kms), max(all_kms)]

    return CoordinateMapping(segments=valid_segments), log, warnings
