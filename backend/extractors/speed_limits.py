"""Extract speed limit segments from a marked horizontal band."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from pydantic import BaseModel

from extractors.coordinate_ruler import CoordinateMapping
from models.markup import HorizontalBand, WorkArea
from models.parsed import ParsedShape

_SPEED_RE = re.compile(r"^\s*(\d+)\s*$")

# Red tolerance: R≥140, G≤100, B≤100
_RED_R_MIN = 140
_RED_GB_MAX = 100

# Element classification: height/width below this → degenerate dimension (≈0)
_DEGENERATE_PX = 0.5

# Minimum element width to be a horizontal candidate (exclude dots)
_MIN_ELEMENT_WIDTH_PX = 1.0

# Y→speed strict snap tolerance
_SCALE_Y_TOLERANCE_PX = 3.0

# Merge gap: adjacent elements within this pixel distance → one segment
_MERGE_GAP_PX = 5.0

# Minimum merged segment network length (metres)
_MIN_MERGED_NET_M = 50.0

# Inter-segment gap warning threshold (pixel space)
_GAP_WARN_PX = 50.0

# Left-margin sizing for scale labels
_SCALE_MARGIN_RATIO = 0.05
_SCALE_MARGIN_EXTRA_PX = 100.0


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
    """Return True if the hex color is red-ish (R≥140, G≤100, B≤100)."""
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
    """Build Y→speed scale from labels in left margin, deduplicated by speed value.

    Returns (scale_pts, raw_label_count, warnings).
    scale_pts: list of (mean_y_px, speed_km_h) sorted by y ascending.
    """
    warnings: list[str] = []
    margin = (wa.x_end - wa.x_start) * _SCALE_MARGIN_RATIO + _SCALE_MARGIN_EXTRA_PX

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

    raw_count = sum(len(ys) for ys in speed_y_groups.values())

    scale_pts: list[tuple[float, int]] = [
        (sum(ys) / len(ys), v)
        for v, ys in speed_y_groups.items()
    ]

    if len(scale_pts) < 2:
        warnings.append(
            f"speed_limits: found only {len(scale_pts)} speed-scale label(s) — need ≥ 2"
        )

    scale_pts.sort(key=lambda p: p[0])
    return scale_pts, raw_count, warnings


def _y_to_speed_strict(
    y: float,
    scale: list[tuple[float, int]],
) -> tuple[Optional[int], float]:
    """Snap y to nearest scale point if within _SCALE_Y_TOLERANCE_PX.

    Returns (speed_or_None, distance_to_nearest_px).
    """
    if not scale:
        return None, float("inf")
    best_y, best_v = min(scale, key=lambda p: abs(p[0] - y))
    dist = abs(best_y - y)
    return (best_v if dist <= _SCALE_Y_TOLERANCE_PX else None), dist


def _y_to_speed_interp(y: float, scale: list[tuple[float, int]]) -> Optional[int]:
    """Linear interpolation y → speed (used in fallback path)."""
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


def extract_speed_limits(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    work_area: WorkArea,
    coord_mapping: CoordinateMapping,
) -> tuple[list[SpeedLimitSegment], dict, list[str]]:
    """Parse the speed limits band into a list of SpeedLimitSegment.

    Algorithm (red path):
    1. Find all red shapes in band.
    2. Classify: horizontal (h≤0.5px, w≥1px), vertical (w≤0.5px), other.
    3. For each horizontal: strict Y-snap to nearest scale point (±3px).
       Reject if too far — warns about scale/band misalignment.
    4. Group by speed value; sort by X; merge adjacent (gap≤5px).
    5. Gap continuity check in pixel space (warn if gap>50px).
    6. Convert X ranges to network coords; filter merged segments < 50m.
    7. Sort by network start; resolve overlaps (keep longer segment).

    Fallback (no red shapes): use all wide horizontal shapes + interpolation.

    Returns (segments, log_dict, warnings).
    """
    warnings: list[str] = []
    band_width = work_area.x_end - work_area.x_start

    shapes_in_band = sum(
        1 for s in shapes
        if band.y_top <= _cy(s) <= band.y_bottom
        and work_area.x_start <= _cx(s) <= work_area.x_end
    )

    # ── 1. Build Y→speed scale ───────────────────────────────────────────────
    scale, raw_label_count, scale_warnings = _build_speed_scale(shapes, band, work_area)
    warnings.extend(scale_warnings)
    scale_values = sorted({v for _, v in scale})

    # ── 2. Find red shapes in band ───────────────────────────────────────────
    red_in_band = [s for s in shapes if _in_band(s, band, work_area) and _is_red(s.line_color)]

    if not red_in_band:
        return _fallback_no_red(
            shapes, band, work_area, coord_mapping, scale, scale_values,
            raw_label_count, shapes_in_band, warnings,
        )

    # ── 3. Classify red shapes ───────────────────────────────────────────────
    horizontal: list[ParsedShape] = []
    vertical_skipped: list[ParsedShape] = []
    other_skipped: list[ParsedShape] = []

    for s in red_in_band:
        if s.height <= _DEGENERATE_PX and s.width >= _MIN_ELEMENT_WIDTH_PX:
            horizontal.append(s)
        elif s.width <= _DEGENERATE_PX:
            vertical_skipped.append(s)
        else:
            other_skipped.append(s)

    if other_skipped:
        warnings.append(
            f"speed_limits: {len(other_skipped)} red shape(s) skipped "
            f"(h and w both > {_DEGENERATE_PX}px, not horizontal/vertical)"
        )

    # ── 4. Y-snap each horizontal element → speed group ─────────────────────
    groups: dict[int, list[tuple[float, float]]] = defaultdict(list)
    rejected_far: list[dict] = []

    for s in horizontal:
        cy_s = _cy(s)
        speed, dist = _y_to_speed_strict(cy_s, scale)
        if speed is None:
            entry: dict = {
                "id": s.id,
                "x": round(s.x, 1),
                "y_center": round(cy_s, 1),
                "distance_px": round(dist, 1),
            }
            if scale:
                best_y, best_v = min(scale, key=lambda p: abs(p[0] - cy_s))
                entry["closest_scale_y"] = round(best_y, 1)
                entry["closest_scale_speed"] = best_v
            rejected_far.append(entry)
            continue
        x_end = s.x + s.width
        if x_end <= s.x:
            continue
        groups[speed].append((s.x, x_end))

    if rejected_far:
        warnings.append(
            f"speed_limits: {len(rejected_far)} horizontal red element(s) rejected "
            f"(Y too far from scale, >{_SCALE_Y_TOLERANCE_PX}px) — "
            "check that speed_limits band aligns with scale labels"
        )

    if not groups:
        warnings.append(
            "speed_limits: no horizontal red elements matched scale — "
            "check band Y placement relative to scale labels"
        )
        log = _empty_log(
            shapes_in_band, raw_label_count, scale, scale_values,
            len(red_in_band), len(horizontal), len(vertical_skipped), len(other_skipped),
            rejected_far,
        )
        return [], log, warnings

    # ── 5. Sort and merge adjacent elements per speed group ──────────────────
    by_speed_value: dict[str, dict] = {}
    merge_gaps_used: list[float] = []
    pixel_segments: list[tuple[float, float, int]] = []  # (x_start, x_end, speed)

    for speed in sorted(groups.keys()):
        raw = sorted(groups[speed], key=lambda t: t[0])
        by_speed_value[str(speed)] = {"raw_count": len(raw), "after_merge": 0}

        merged: list[tuple[float, float]] = [raw[0]]
        for x_start, x_end in raw[1:]:
            gap = x_start - merged[-1][1]
            if gap <= _MERGE_GAP_PX:
                if gap > 0:
                    merge_gaps_used.append(round(gap, 2))
                merged[-1] = (merged[-1][0], max(merged[-1][1], x_end))
            else:
                merged.append((x_start, x_end))

        by_speed_value[str(speed)]["after_merge"] = len(merged)
        for x0, x1 in merged:
            pixel_segments.append((x0, x1, speed))

    pixel_segments.sort(key=lambda t: t[0])

    # ── 6. Continuity check in pixel space ───────────────────────────────────
    for i in range(1, len(pixel_segments)):
        gap_px = pixel_segments[i][0] - pixel_segments[i - 1][1]
        if gap_px > _GAP_WARN_PX:
            warnings.append(
                f"speed_limits: gap of {round(gap_px, 1)}px between segments at "
                f"x≈{round(pixel_segments[i-1][1])} → x≈{round(pixel_segments[i][0])}"
            )

    # ── 7. Convert to network metres; filter short ───────────────────────────
    net_segs: list[SpeedLimitSegment] = []
    rejected_short: list[dict] = []

    for x0, x1, speed in pixel_segments:
        nl = coord_mapping.x_to_network_coord(x0)
        nr = coord_mapping.x_to_network_coord(x1)
        ns, ne = min(nl, nr), max(nl, nr)
        if ne - ns < _MIN_MERGED_NET_M:
            rejected_short.append({
                "x_start": round(x0, 1),
                "x_end": round(x1, 1),
                "speed": speed,
                "net_length_m": round(ne - ns, 1),
            })
            continue
        net_segs.append(SpeedLimitSegment(start=ns, end=ne, limit=speed))

    # ── 8. Sort by network start; resolve overlaps (keep longer) ─────────────
    net_segs.sort(key=lambda s: s.start)
    final: list[SpeedLimitSegment] = []
    for seg in net_segs:
        if final and seg.start < final[-1].end:
            prev = final[-1]
            if (seg.end - seg.start) > (prev.end - prev.start):
                warnings.append(
                    f"speed_limits: overlap — replaced {prev.limit} km/h segment with "
                    f"longer {seg.limit} km/h ({round(seg.start)}–{round(seg.end)})"
                )
                final[-1] = seg
            else:
                warnings.append(
                    f"speed_limits: overlap — kept {prev.limit} km/h, skipped "
                    f"{seg.limit} km/h ({round(seg.start)}–{round(seg.end)})"
                )
        else:
            final.append(seg)

    log = {
        "shapes_in_band": shapes_in_band,
        "scale_labels_raw": raw_label_count,
        "scale_labels_deduped": len(scale),
        "scale_speeds": scale_values,
        "candidate_line_shapes": len(red_in_band),
        "red_lines": len(red_in_band),
        "other_lines": 0,
        "used_color_filter": True,
        "red_elements_classified": {
            "total_red_in_band": len(red_in_band),
            "horizontal": len(horizontal),
            "vertical_skipped": len(vertical_skipped),
            "other_skipped": len(other_skipped),
        },
        "by_speed_value": by_speed_value,
        "merge_gaps_used": sorted(set(merge_gaps_used))[:20],
        "rejected_far_from_scale": rejected_far[:20],
        "rejected_short_after_merge": rejected_short[:20],
        "raw_segments": len(pixel_segments),
        "found_segments": len(final),
        "value_scale_points": scale_values,
        # kept for backward compat with old diagnostic fields
        "red_line_details": [],
        "rejected_red_segments": [],
    }
    return final, log, warnings


def _fallback_no_red(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    work_area: WorkArea,
    coord_mapping: CoordinateMapping,
    scale: list[tuple[float, int]],
    scale_values: list[int],
    raw_label_count: int,
    shapes_in_band: int,
    warnings: list[str],
) -> tuple[list[SpeedLimitSegment], dict, list[str]]:
    """Fallback: no red shapes — use wide horizontal shapes + interpolation."""
    min_width_fb = (work_area.x_end - work_area.x_start) * 0.03
    fb_candidates = [
        s for s in shapes
        if _in_band(s, band, work_area)
        and s.height <= 16
        and s.width >= min_width_fb
    ]
    warnings.append(
        "speed_limits: no red-colored shapes found — "
        f"fallback to {len(fb_candidates)} wide horizontal shapes; "
        "results may include grid lines"
    )

    raw_segs: list[tuple[float, float, int]] = []
    for s in fb_candidates:
        sp = _y_to_speed_interp(_cy(s), scale)
        if sp is None or not (0 <= sp <= 200):
            continue
        cl = min(scale_values or [sp], key=lambda v: abs(v - sp))
        if abs(cl - sp) <= 5:
            sp = cl
        nl = coord_mapping.x_to_network_coord(s.x)
        nr = coord_mapping.x_to_network_coord(s.x + s.width)
        ns, ne = min(nl, nr), max(nl, nr)
        if ne - ns < 10:
            continue
        raw_segs.append((ns, ne, sp))

    raw_segs.sort()
    merged_fb: list[SpeedLimitSegment] = []
    for ns, ne, sp in raw_segs:
        if merged_fb and merged_fb[-1].limit == sp and abs(merged_fb[-1].end - ns) < 500:
            merged_fb[-1] = SpeedLimitSegment(
                start=merged_fb[-1].start, end=ne, limit=sp
            )
        else:
            merged_fb.append(SpeedLimitSegment(start=ns, end=ne, limit=sp))

    log = {
        "shapes_in_band": shapes_in_band,
        "scale_labels_raw": raw_label_count,
        "scale_labels_deduped": len(scale),
        "scale_speeds": scale_values,
        "candidate_line_shapes": len(fb_candidates),
        "red_lines": 0,
        "other_lines": len(fb_candidates),
        "used_color_filter": False,
        "red_elements_classified": {
            "total_red_in_band": 0,
            "horizontal": 0,
            "vertical_skipped": 0,
            "other_skipped": 0,
        },
        "by_speed_value": {},
        "merge_gaps_used": [],
        "rejected_far_from_scale": [],
        "rejected_short_after_merge": [],
        "raw_segments": len(raw_segs),
        "found_segments": len(merged_fb),
        "value_scale_points": scale_values,
        "red_line_details": [],
        "rejected_red_segments": [],
    }
    return merged_fb, log, warnings


def _empty_log(
    shapes_in_band: int,
    raw_label_count: int,
    scale: list[tuple[float, int]],
    scale_values: list[int],
    total_red: int,
    horiz: int,
    vert: int,
    other: int,
    rejected_far: list[dict],
) -> dict:
    return {
        "shapes_in_band": shapes_in_band,
        "scale_labels_raw": raw_label_count,
        "scale_labels_deduped": len(scale),
        "scale_speeds": scale_values,
        "candidate_line_shapes": total_red,
        "red_lines": total_red,
        "other_lines": 0,
        "used_color_filter": True,
        "red_elements_classified": {
            "total_red_in_band": total_red,
            "horizontal": horiz,
            "vertical_skipped": vert,
            "other_skipped": other,
        },
        "by_speed_value": {},
        "merge_gaps_used": [],
        "rejected_far_from_scale": rejected_far,
        "rejected_short_after_merge": [],
        "raw_segments": 0,
        "found_segments": 0,
        "value_scale_points": scale_values,
        "red_line_details": [],
        "rejected_red_segments": [],
    }
