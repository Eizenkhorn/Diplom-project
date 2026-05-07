"""Extract speed limit segments from a marked horizontal band."""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from extractors.coordinate_ruler import CoordinateMapping
from models.markup import HorizontalBand, WorkArea
from models.parsed import ParsedShape

# Known speed values that appear on the Y-axis of a speed chart
_SPEED_VALUES = {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 70, 80, 90, 100, 110, 120, 140, 160}
_SPEED_RE = re.compile(r"^\s*(\d+)\s*$")

# Tolerance for "red-ish" color (R > 160, G < 80, B < 80)
_RED_R_MIN = 160
_RED_GB_MAX = 80

# A segment with nearly constant Y counts as horizontal (px tolerance)
_HORIZ_TOLERANCE_PX = 8

# Minimum width to be considered a speed-limit segment (not a scale tick)
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
    """Return True if the hex color is red-ish."""
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
) -> tuple[list[tuple[float, int]], list[str]]:
    """Find speed-value labels on the Y-axis of the speed band.

    Returns list of (y_px, speed_km_h) sorted by y_px descending (0 km/h at bottom),
    and warnings.
    """
    warnings: list[str] = []

    # Left margin of the band: within first 5% of work-area width
    margin = (wa.x_end - wa.x_start) * 0.05 + 100

    scale_pts: list[tuple[float, int]] = []
    for s in shapes:
        if s.text is None:
            continue
        if not (band.y_top <= _cy(s) <= band.y_bottom):
            continue
        # Only look in the left margin
        if _cx(s) > wa.x_start + margin:
            continue
        m = _SPEED_RE.match(s.text)
        if not m:
            continue
        v = int(m.group(1))
        if v in _SPEED_VALUES or 0 <= v <= 200:
            scale_pts.append((_cy(s), v))

    if len(scale_pts) < 2:
        warnings.append(
            f"speed_limits: found only {len(scale_pts)} speed-scale label(s) "
            f"(need ≥ 2 for Y→speed mapping)"
        )
    scale_pts.sort(key=lambda p: p[0])   # sort by y ascending (top → bottom)
    return scale_pts, warnings


def _y_to_speed(y: float, scale: list[tuple[float, int]]) -> Optional[int]:
    """Map a pixel Y position to a speed value via linear interpolation."""
    if not scale:
        return None
    if len(scale) == 1:
        return scale[0][1]

    # Clamp to range
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


def extract_speed_limits(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    work_area: WorkArea,
    coord_mapping: CoordinateMapping,
) -> tuple[list[SpeedLimitSegment], dict, list[str]]:
    """Parse the speed limits band into a list of SpeedLimitSegment.

    Strategy:
    1. Build Y→speed scale from labeled gridlines on the left margin.
    2. Find horizontal line/connector shapes in the band:
       a. If color data available: prefer red-colored shapes.
       b. Fallback: shapes wider than MIN_SEGMENT_WIDTH_RATIO × band_width.
    3. Each horizontal shape → its Y maps to a speed, its X span → network coords.
    4. Merge adjacent segments with same speed limit.

    Returns (segments, stats_dict, warnings).
    """
    warnings: list[str] = []
    band_width = work_area.x_end - work_area.x_start

    # ── 1. Build Y→speed scale ───────────────────────────────────────────────
    scale, scale_warnings = _build_speed_scale(shapes, band, work_area)
    warnings.extend(scale_warnings)

    scale_values = sorted({v for _, v in scale})

    # ── 2. Find speed-limit line shapes ─────────────────────────────────────
    min_width = band_width * _MIN_SEGMENT_WIDTH_RATIO

    # Candidate: a "thin" shape (height ≈ 0 or connector) spanning enough width
    def is_line_shape(s: ParsedShape) -> bool:
        return (
            s.height <= _HORIZ_TOLERANCE_PX * 2
            and s.width >= min_width
            and _in_band(s, band, work_area)
        )

    candidates = [s for s in shapes if is_line_shape(s)]

    # Separate red-colored vs uncolored / non-red
    red_lines = [s for s in candidates if _is_red(s.line_color)]
    other_lines = [s for s in candidates if not _is_red(s.line_color)]

    if red_lines:
        limit_shapes = red_lines
    elif candidates:
        # No explicit red color — use all wide horizontal shapes and warn
        limit_shapes = other_lines
        warnings.append(
            "speed_limits: no red-colored lines found — using all wide horizontal "
            f"shapes as fallback ({len(limit_shapes)} shapes). "
            "Results may include grid lines; consider verifying manually."
        )
    else:
        warnings.append(
            "speed_limits: no horizontal line shapes found in band — "
            "speed limits not extracted"
        )
        stats = {
            "found_segments": 0,
            "value_scale_points": scale_values,
            "used_color_filter": False,
        }
        return [], stats, warnings

    used_color = bool(red_lines)

    # ── 3. Map each shape to (x_start_net, x_end_net, speed) ────────────────
    raw_segments: list[tuple[float, float, int]] = []   # (net_start, net_end, limit)

    for s in limit_shapes:
        speed = _y_to_speed(_cy(s), scale)
        if speed is None or not (0 <= speed <= 200):
            continue
        # Snap to nearest known speed value if close enough (within 5 km/h)
        closest = min(scale_values or [speed], key=lambda v: abs(v - speed))
        if abs(closest - speed) <= 5:
            speed = closest

        # Convert pixel X to network metres
        net_left = coord_mapping.x_to_network_coord(s.x)
        net_right = coord_mapping.x_to_network_coord(s.x + s.width)
        # Ensure start < end in network metres (could be reversed for descending ruler)
        net_start = min(net_left, net_right)
        net_end = max(net_left, net_right)
        if net_end - net_start < 10:  # too short (< 10m), skip
            continue
        raw_segments.append((net_start, net_end, speed))

    # Sort by network start coordinate
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

    if merged:
        bad = [s for s in merged if not (0 <= s.limit <= 200)]
        if bad:
            warnings.append(
                f"speed_limits: {len(bad)} segment(s) with out-of-range limit values"
            )

    stats = {
        "found_segments": len(merged),
        "value_scale_points": scale_values,
        "used_color_filter": used_color,
    }
    return merged, stats, warnings
