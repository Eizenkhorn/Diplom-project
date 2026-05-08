"""Extract speed limit segments from a marked horizontal band."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from pydantic import BaseModel

from extractors.coordinate_ruler import CoordinateMapping
from models.markup import HorizontalBand, WorkArea
from models.parsed import ParsedShape

_SPEED_VALUES = {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 70, 80, 90, 100, 110, 120, 140, 160}
_SPEED_RE = re.compile(r"^\s*(\d+)\s*$")

# Broadened red tolerance: R≥140, G≤100, B≤100
_RED_R_MIN = 140
_RED_GB_MAX = 100

_HORIZ_TOLERANCE_PX = 8
_MIN_SEGMENT_WIDTH_RATIO = 0.03  # at least 3% of work-area width


class SpeedLimitSegment(BaseModel):
    start: float       # network metres (km × 1000)
    end: float
    limit: int         # km/h
    type: str = "track_category"


def _cx(s: ParsedShape) -> float:
    return s.x + s.width / 2


def _cy(s: ParsedShape) -> float:
    return s.y + s.height / 2


def _in_band(s: ParsedShape, band: HorizontalBand, wa: WorkArea) -> bool:
    return (
        band.y_top <= _cy(s) <= band.y_bottom
        and wa.x_start <= _cx(s) <= wa.x_end
    )


def _is_red(color: Optional[str]) -> bool:
    """Return True if the hex color is red-ish (broadened tolerance)."""
    if not color or len(color) != 7 or color[0] != "#":
        return False
    try:
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        return r >= _RED_R_MIN and g <= _RED_GB_MAX and b <= _RED_GB_MAX
    except ValueError:
        return False


def _build_speed_scale(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    wa: WorkArea,
) -> tuple[list[tuple[float, int]], int, list[str]]:
    """Find speed-value labels on the Y-axis of the speed band.

    Deduplicates by speed value (uses mean Y for duplicate speed labels).
    Returns (scale_pts, raw_label_count, warnings).
    scale_pts: list of (y_px, speed_km_h) sorted by y_px ascending.
    """
    warnings: list[str] = []

    # Left margin: first 5% of work-area width + 100px buffer
    margin = (wa.x_end - wa.x_start) * 0.05 + 100

    # Collect raw labels: group Y positions by speed value
    speed_y_groups: dict[int, list[float]] = defaultdict(list)
    for s in shapes:
        if s.text is None:
            continue
        if not (band.y_top <= _cy(s) <= band.y_bottom):
            continue
        if _cx(s) > wa.x_start + margin:
            continue
        m = _SPEED_RE.match(s.text)
        if not m:
            continue
        v = int(m.group(1))
        if not (0 <= v <= 200):
            continue
        speed_y_groups[v].append(_cy(s))

    raw_label_count = sum(len(ys) for ys in speed_y_groups.values())

    # Deduplicate: one entry per speed value, use mean Y
    scale_pts: list[tuple[float, int]] = []
    for v, ys in speed_y_groups.items():
        mean_y = sum(ys) / len(ys)
        scale_pts.append((mean_y, v))

    if len(scale_pts) < 2:
        warnings.append(
            f"speed_limits: found only {len(scale_pts)} speed-scale label(s) "
            f"(need ≥ 2 for Y→speed mapping)"
        )

    scale_pts.sort(key=lambda p: p[0])  # ascending Y (top→bottom)
    return scale_pts, raw_label_count, warnings


def _y_to_speed(y: float, scale: list[tuple[float, int]]) -> Optional[int]:
    """Map a pixel Y position to a speed value via linear interpolation."""
    if not scale:
        return None
    if len(scale) == 1:
        return scale[0][1]
    if y <= scale[0][0]:
        return scale[0][1]
    if y >= scale[-1][0]:
        return scale[-1][1]
    for i in range(len(scale) - 1):
        y1, v1 = scale[i]
        y2, v2 = scale[i + 1]
        if y1 <= y <= y2:
            t = (y - y1) / (y2 - y1)
            return round(v1 + t * (v2 - v1))
    return scale[-1][1]


def _remove_overlaps(segs: list[SpeedLimitSegment]) -> list[SpeedLimitSegment]:
    """Clip overlapping segments so each network metre belongs to at most one segment."""
    if len(segs) <= 1:
        return segs
    result: list[SpeedLimitSegment] = [segs[0]]
    for seg in segs[1:]:
        prev = result[-1]
        if seg.start < prev.end:
            # Overlap: clip new segment's start to prev end
            clipped = seg.start = prev.end  # noqa: F841 (use via variable below)
            clipped_start = prev.end
            if seg.end > clipped_start:
                result.append(SpeedLimitSegment(
                    start=clipped_start, end=seg.end,
                    limit=seg.limit, type=seg.type,
                ))
        else:
            result.append(seg)
    return result


def extract_speed_limits(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    work_area: WorkArea,
    coord_mapping: CoordinateMapping,
) -> tuple[list[SpeedLimitSegment], dict, list[str]]:
    """Parse the speed limits band into a list of SpeedLimitSegment.

    Strategy:
    1. Build Y→speed scale from labeled gridlines on the left margin (deduplicated by speed).
    2. Find horizontal line/connector shapes in the band.
       a. If color data available: prefer red-colored shapes (broadened tolerance).
       b. Fallback: all wide horizontal shapes.
    3. Each horizontal shape → Y maps to speed, X span → network coords.
    4. Merge adjacent same-speed segments; remove overlaps.

    Returns (segments, log_dict, warnings).
    """
    warnings: list[str] = []
    band_width = work_area.x_end - work_area.x_start

    # Count total shapes in band for diagnostics
    shapes_in_band = sum(
        1 for s in shapes
        if band.y_top <= _cy(s) <= band.y_bottom
        and work_area.x_start <= _cx(s) <= work_area.x_end
    )

    # ── 1. Build Y→speed scale ───────────────────────────────────────────────
    scale, raw_label_count, scale_warnings = _build_speed_scale(shapes, band, work_area)
    warnings.extend(scale_warnings)
    scale_values = sorted({v for _, v in scale})

    # ── 2. Find speed-limit line shapes ─────────────────────────────────────
    min_width = band_width * _MIN_SEGMENT_WIDTH_RATIO

    def is_line_shape(s: ParsedShape) -> bool:
        return (
            s.height <= _HORIZ_TOLERANCE_PX * 2
            and s.width >= min_width
            and _in_band(s, band, work_area)
        )

    candidates = [s for s in shapes if is_line_shape(s)]
    red_lines = [s for s in candidates if _is_red(s.line_color)]
    other_lines = [s for s in candidates if not _is_red(s.line_color)]

    if red_lines:
        limit_shapes = red_lines
        used_color = True
    elif candidates:
        limit_shapes = other_lines
        used_color = False
        warnings.append(
            "speed_limits: no red-colored lines found — using all wide horizontal "
            f"shapes as fallback ({len(limit_shapes)} shapes). "
            "Results may include grid lines; verify manually."
        )
    else:
        warnings.append(
            "speed_limits: no horizontal line shapes found in band — "
            "speed limits not extracted"
        )
        log = {
            "shapes_in_band": shapes_in_band,
            "scale_labels_raw": raw_label_count,
            "scale_labels_deduped": len(scale),
            "scale_speeds": scale_values,
            "candidate_line_shapes": 0,
            "red_lines": 0,
            "other_lines": 0,
            "used_color_filter": False,
            "raw_segments": 0,
            "found_segments": 0,
            "value_scale_points": scale_values,
        }
        return [], log, warnings

    # ── 3. Map each shape to (net_start, net_end, speed) ────────────────────
    raw_segments: list[tuple[float, float, int]] = []

    for s in limit_shapes:
        speed = _y_to_speed(_cy(s), scale)
        if speed is None or not (0 <= speed <= 200):
            continue
        # Snap to nearest known scale value if within 5 km/h
        closest = min(scale_values or [speed], key=lambda v: abs(v - speed))
        if abs(closest - speed) <= 5:
            speed = closest

        net_left = coord_mapping.x_to_network_coord(s.x)
        net_right = coord_mapping.x_to_network_coord(s.x + s.width)
        net_start = min(net_left, net_right)
        net_end = max(net_left, net_right)
        if net_end - net_start < 10:  # < 10 m, skip
            continue
        raw_segments.append((net_start, net_end, speed))

    raw_segments.sort(key=lambda t: t[0])

    # ── 4. Merge adjacent same-speed segments ────────────────────────────────
    merged: list[SpeedLimitSegment] = []
    for net_start, net_end, speed in raw_segments:
        if merged and merged[-1].limit == speed and abs(merged[-1].end - net_start) < 500:
            merged[-1] = SpeedLimitSegment(
                start=merged[-1].start,
                end=net_end,
                limit=speed,
                type="track_category",
            )
        else:
            merged.append(SpeedLimitSegment(
                start=net_start, end=net_end,
                limit=speed, type="track_category",
            ))

    # ── 5. Remove overlaps ───────────────────────────────────────────────────
    final = _remove_overlaps(merged)

    bad = [s for s in final if not (0 <= s.limit <= 200)]
    if bad:
        warnings.append(
            f"speed_limits: {len(bad)} segment(s) with out-of-range limit values removed"
        )
        final = [s for s in final if 0 <= s.limit <= 200]

    log = {
        "shapes_in_band": shapes_in_band,
        "scale_labels_raw": raw_label_count,
        "scale_labels_deduped": len(scale),
        "scale_speeds": scale_values,
        "candidate_line_shapes": len(candidates),
        "red_lines": len(red_lines),
        "other_lines": len(other_lines),
        "used_color_filter": used_color,
        "raw_segments": len(raw_segments),
        "found_segments": len(final),
        "value_scale_points": scale_values,
    }
    return final, log, warnings
