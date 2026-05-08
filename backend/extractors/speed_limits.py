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

# Element classification
_DEGENERATE_PX = 0.5         # height/width below this → degenerate dimension
_MIN_ELEMENT_WIDTH_PX = 1.0  # minimum width for horizontal candidate

# Y→speed snap tolerance (Problem B: 3 → 7 px)
_SCALE_Y_TOLERANCE_PX = 7.0

# Scale grouping: gap in X between adjacent labels > this → new scale group (Problem C)
_SCALE_X_GROUP_GAP_PX = 100.0

# Segment merging / filtering
_MERGE_GAP_PX = 5.0          # merge adjacent pixel-segments within this gap
_MIN_MERGED_NET_M = 50.0     # discard merged segments shorter than this (metres)
_GAP_WARN_PX = 50.0          # warn if gap between pixel-segments exceeds this


class SpeedLimitSegment(BaseModel):
    start: float       # network metres (km × 1000)
    end: float
    limit: int         # km/h
    type: str = "track_category"


def _cx(s: ParsedShape) -> float:
    return s.x + s.width / 2


def _cy(s: ParsedShape) -> float:
    """Vertical centre. Y in parsed data is top edge; centre = y + height/2."""
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


def _build_local_scales(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    wa: WorkArea,
) -> tuple[list[dict], int, int, list[int], list[str]]:
    """Build a list of local Y→speed scales, one per scale repetition.

    Scale labels (integer text 0–200 inside band) are collected then sorted
    by cx. A new group starts whenever the X gap to the previous label
    exceeds _SCALE_X_GROUP_GAP_PX.  Groups with ≥2 distinct speed values
    become local scales.

    Returns (local_scales, raw_label_count, deduped_count, all_speed_values, warnings).
    Each local_scale: {'x_center': float, 'pts': [(cy, speed), ...] sorted by cy}.
    """
    warnings: list[str] = []

    candidates: list[tuple[float, float, int]] = []   # (cx, cy, speed)
    for s in shapes:
        if s.text is None:
            continue
        if not (band.y_top <= _cy(s) <= band.y_bottom):
            continue
        if not (wa.x_start <= _cx(s) <= wa.x_end):
            continue
        m = _SPEED_RE.match(s.text)
        if not m:
            continue
        v = int(m.group(1))
        if not (0 <= v <= 200):
            continue
        # Use _cy so Y is always the bbox centre, not the top edge (Problem A)
        candidates.append((_cx(s), _cy(s), v))

    raw_count = len(candidates)

    if not candidates:
        warnings.append("speed_limits: no speed-scale labels found in band")
        return [], 0, 0, [], warnings

    candidates.sort(key=lambda t: t[0])   # sort by cx

    # Group by X gap
    groups: list[list[tuple[float, float, int]]] = []
    current: list[tuple[float, float, int]] = [candidates[0]]
    for i in range(1, len(candidates)):
        if candidates[i][0] - candidates[i - 1][0] > _SCALE_X_GROUP_GAP_PX:
            groups.append(current)
            current = [candidates[i]]
        else:
            current.append(candidates[i])
    groups.append(current)

    local_scales: list[dict] = []
    for grp in groups:
        speed_y: dict[int, list[float]] = defaultdict(list)
        cx_vals: list[float] = []
        for cx, cy, v in grp:
            speed_y[v].append(cy)   # cy = centre Y (Problem A fix)
            cx_vals.append(cx)
        pts = sorted(
            [(sum(ys) / len(ys), v) for v, ys in speed_y.items()],
            key=lambda p: p[0],
        )
        if len(pts) >= 2:
            local_scales.append({
                "x_center": sum(cx_vals) / len(cx_vals),
                "pts": pts,
            })

    if not local_scales:
        warnings.append(
            f"speed_limits: no scale group with ≥2 speed levels found "
            f"({len(groups)} raw group(s) had ≤1 distinct value)"
        )

    all_speeds = sorted({v for sc in local_scales for _, v in sc["pts"]})
    deduped_count = sum(len(sc["pts"]) for sc in local_scales)

    return local_scales, raw_count, deduped_count, all_speeds, warnings


def _find_nearest_scale(local_scales: list[dict], cx: float) -> dict | None:
    """Return the local scale group whose x_center is closest to cx."""
    if not local_scales:
        return None
    return min(local_scales, key=lambda sc: abs(sc["x_center"] - cx))


def _y_to_speed_strict(
    y: float,
    pts: list[tuple[float, int]],
) -> tuple[Optional[int], float]:
    """Snap y to nearest scale point if within _SCALE_Y_TOLERANCE_PX.

    Returns (speed_or_None, distance_px).
    """
    if not pts:
        return None, float("inf")
    best_y, best_v = min(pts, key=lambda p: abs(p[0] - y))
    dist = abs(best_y - y)
    return (best_v if dist <= _SCALE_Y_TOLERANCE_PX else None), dist


def _y_to_speed_interp(y: float, pts: list[tuple[float, int]]) -> Optional[int]:
    """Linear interpolation y → speed (used in fallback path)."""
    if not pts:
        return None
    if len(pts) == 1:
        return pts[0][1]
    if y <= pts[0][0]:
        return pts[0][1]
    if y >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        y1, v1 = pts[i]
        y2, v2 = pts[i + 1]
        if y1 <= y <= y2:
            t = (y - y1) / (y2 - y1)
            return round(v1 + t * (v2 - v1))
    return pts[-1][1]


def _merge_global_pts(local_scales: list[dict]) -> list[tuple[float, int]]:
    """Merge all local scale pts into one global list for fallback interpolation."""
    speed_y: dict[int, list[float]] = defaultdict(list)
    for sc in local_scales:
        for cy, v in sc["pts"]:
            speed_y[v].append(cy)
    return sorted(
        [(sum(ys) / len(ys), v) for v, ys in speed_y.items()],
        key=lambda p: p[0],
    )


def extract_speed_limits(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    work_area: WorkArea,
    coord_mapping: CoordinateMapping,
) -> tuple[list[SpeedLimitSegment], dict, list[str]]:
    """Parse the speed limits band into a list of SpeedLimitSegment.

    Algorithm (red path):
    1. Build local Y→speed scales: group scale labels by X (gap>100px → new group).
    2. Find all red shapes in band.
    3. Classify: horizontal (h≤0.5px, w≥1px), vertical (w≤0.5px), other.
    4. For each horizontal: find nearest local scale by X; strict Y-snap (±7px).
    5. Group by speed; sort by X; merge adjacent (gap≤5px).
    6. Gap continuity check (warn if gap>50px).
    7. Convert X ranges to network coords; filter merged segments < 50m.
    8. Sort by network start; resolve overlaps (keep longer segment).

    Fallback (no red shapes): wide horizontal shapes + interpolation.

    Returns (segments, log_dict, warnings).
    """
    warnings: list[str] = []

    shapes_in_band = sum(
        1 for s in shapes
        if band.y_top <= _cy(s) <= band.y_bottom
        and work_area.x_start <= _cx(s) <= work_area.x_end
    )

    # ── 1. Build local Y→speed scales ────────────────────────────────────────
    local_scales, raw_label_count, deduped_count, scale_values, scale_warnings = \
        _build_local_scales(shapes, band, work_area)
    warnings.extend(scale_warnings)

    # ── 2. Find red shapes in band ────────────────────────────────────────────
    red_in_band = [
        s for s in shapes
        if _in_band(s, band, work_area) and _is_red(s.line_color)
    ]

    if not red_in_band:
        return _fallback_no_red(
            shapes, band, work_area, coord_mapping,
            local_scales, scale_values,
            raw_label_count, deduped_count, shapes_in_band, warnings,
        )

    # ── 3. Classify red shapes ────────────────────────────────────────────────
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
            f"(h and w both > {_DEGENERATE_PX}px)"
        )

    # ── 4. Y-snap each horizontal element → speed group ──────────────────────
    groups: dict[int, list[tuple[float, float]]] = defaultdict(list)
    rejected_far: list[dict] = []
    matched_details: list[dict] = []

    for s in horizontal:
        cx_s = _cx(s)
        cy_s = _cy(s)   # = s.y + s.height/2  (top-edge Y, Problem A)

        nearest = _find_nearest_scale(local_scales, cx_s)
        if nearest is None:
            rejected_far.append({
                "id": s.id,
                "x_center": round(cx_s, 1),
                "y": round(cy_s, 1),
                "reason": "no scale groups found",
            })
            continue

        pts = nearest["pts"]
        speed, dist = _y_to_speed_strict(cy_s, pts)

        if speed is None:
            entry: dict = {
                "id": s.id,
                "x_center": round(cx_s, 1),
                "y": round(cy_s, 1),
                "matched_scale_x": round(nearest["x_center"], 1),
                "speed_value": None,
                "distance_px": round(dist, 1),
            }
            if pts:
                best_y, best_v = min(pts, key=lambda p: abs(p[0] - cy_s))
                entry["closest_scale_y"] = round(best_y, 1)
                entry["closest_scale_speed"] = best_v
            rejected_far.append(entry)
            continue

        x_end = s.x + s.width
        if x_end <= s.x:
            continue

        groups[speed].append((s.x, x_end))
        matched_details.append({
            "id": s.id,
            "x_center": round(cx_s, 1),
            "y": round(cy_s, 1),
            "matched_scale_x": round(nearest["x_center"], 1),
            "speed_value": speed,
            "distance_px": round(dist, 1),
        })

    if rejected_far:
        warnings.append(
            f"speed_limits: {len(rejected_far)} horizontal red element(s) rejected "
            f"(Y distance > {_SCALE_Y_TOLERANCE_PX}px from nearest local scale)"
        )

    if not groups:
        warnings.append(
            "speed_limits: no horizontal red elements matched any scale — "
            "check band Y alignment with scale labels"
        )
        log = _empty_log(
            shapes_in_band, raw_label_count, deduped_count,
            local_scales, scale_values,
            len(red_in_band), len(horizontal), len(vertical_skipped), len(other_skipped),
            rejected_far, matched_details,
        )
        return [], log, warnings

    # ── 5. Sort and merge adjacent elements per speed group ───────────────────
    by_speed_value: dict[str, dict] = {}
    merge_gaps_used: list[float] = []
    pixel_segments: list[tuple[float, float, int]] = []

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

    # ── 6. Continuity check ───────────────────────────────────────────────────
    for i in range(1, len(pixel_segments)):
        gap_px = pixel_segments[i][0] - pixel_segments[i - 1][1]
        if gap_px > _GAP_WARN_PX:
            warnings.append(
                f"speed_limits: gap of {round(gap_px, 1)}px between segments at "
                f"x≈{round(pixel_segments[i-1][1])} → x≈{round(pixel_segments[i][0])}"
            )

    # ── 7. Convert to network metres; filter short ────────────────────────────
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

    # ── 8. Sort; resolve overlaps (keep longer) ───────────────────────────────
    net_segs.sort(key=lambda s: s.start)
    final: list[SpeedLimitSegment] = []
    for seg in net_segs:
        if final and seg.start < final[-1].end:
            prev = final[-1]
            if (seg.end - seg.start) > (prev.end - prev.start):
                warnings.append(
                    f"speed_limits: overlap — replaced {prev.limit} km/h with "
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

    log = _make_log(
        shapes_in_band, raw_label_count, deduped_count,
        local_scales, scale_values,
        len(red_in_band), len(horizontal), len(vertical_skipped), len(other_skipped),
        by_speed_value, merge_gaps_used,
        rejected_far, rejected_short, matched_details,
        len(pixel_segments), len(final),
        used_color_filter=True,
        other_lines=0,
    )
    return final, log, warnings


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_log(
    shapes_in_band: int,
    raw_label_count: int,
    deduped_count: int,
    local_scales: list[dict],
    scale_values: list[int],
    total_red: int,
    horiz: int,
    vert: int,
    other: int,
    by_speed_value: dict,
    merge_gaps_used: list[float],
    rejected_far: list[dict],
    rejected_short: list[dict],
    matched_details: list[dict],
    raw_segments: int,
    found_segments: int,
    *,
    used_color_filter: bool,
    other_lines: int,
) -> dict:
    return {
        "shapes_in_band": shapes_in_band,
        "scale_labels_raw": raw_label_count,
        "scale_labels_deduped": deduped_count,
        "scale_speeds": scale_values,
        "candidate_line_shapes": total_red,
        "red_lines": total_red,
        "other_lines": other_lines,
        "used_color_filter": used_color_filter,
        "red_elements_classified": {
            "total_red_in_band": total_red,
            "horizontal": horiz,
            "vertical_skipped": vert,
            "other_skipped": other,
        },
        "by_speed_value": by_speed_value,
        "merge_gaps_used": sorted(set(merge_gaps_used))[:20],
        "rejected_far_from_scale": rejected_far[:20],
        "rejected_short_after_merge": rejected_short[:20],
        "raw_segments": raw_segments,
        "found_segments": found_segments,
        "value_scale_points": scale_values,
        # Problem D: extended diagnostic fields
        "scales_found": len(local_scales),
        "scale_groups": [
            {
                "x_center": round(sc["x_center"], 1),
                "y_to_speed": [[round(y, 1), v] for y, v in sc["pts"]],
            }
            for sc in local_scales[:60]
        ],
        "red_horizontal_with_scale_match": matched_details[:200],
        # backward compat stubs
        "red_line_details": [],
        "rejected_red_segments": [],
    }


def _fallback_no_red(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    work_area: WorkArea,
    coord_mapping: CoordinateMapping,
    local_scales: list[dict],
    scale_values: list[int],
    raw_label_count: int,
    deduped_count: int,
    shapes_in_band: int,
    warnings: list[str],
) -> tuple[list[SpeedLimitSegment], dict, list[str]]:
    """Fallback: no red shapes — use wide horizontal shapes + interpolation."""
    global_pts = _merge_global_pts(local_scales)

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
        sp = _y_to_speed_interp(_cy(s), global_pts)
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

    log = _make_log(
        shapes_in_band, raw_label_count, deduped_count,
        local_scales, scale_values,
        0, 0, 0, 0,
        {}, [],
        [], [], [],
        len(raw_segs), len(merged_fb),
        used_color_filter=False,
        other_lines=len(fb_candidates),
    )
    return merged_fb, log, warnings


def _empty_log(
    shapes_in_band: int,
    raw_label_count: int,
    deduped_count: int,
    local_scales: list[dict],
    scale_values: list[int],
    total_red: int,
    horiz: int,
    vert: int,
    other: int,
    rejected_far: list[dict],
    matched_details: list[dict],
) -> dict:
    return _make_log(
        shapes_in_band, raw_label_count, deduped_count,
        local_scales, scale_values,
        total_red, horiz, vert, other,
        {}, [],
        rejected_far, [], matched_details,
        0, 0,
        used_color_filter=True,
        other_lines=0,
    )
