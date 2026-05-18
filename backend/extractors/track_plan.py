"""Extract track-plan curves from a marked horizontal band.

Algorithm (v2 — no colour filter, step detection from Y-deviation):

1. Collect all graphic (non-text) shapes inside band + work_area.
2. Sort by x; build connected-component groups (x-gap < 10 px between
   right edge of one shape and left edge of the next).
3. Find baseline_y as median cy of horizontal-ish shapes (w >= 2h).
4. Identify "step" shapes: |cy – baseline_y| > STEP_THRESHOLD (5 px).
5. Group adjacent step shapes (x-gap < STEP_GROUP_GAP) → each group is
   one curve step.
6. Collect text shapes matching N/M in band + work_area.
7. Pair each N/M label with the nearest step (by X-centre, threshold
   MAX_LABEL_STEP_DIST). Unmatched steps → curves with radius/length = None.
   Unmatched labels → warning only.
8. Convert step x_left/x_right → network metres via coord_mapping.
"""
from __future__ import annotations

import re
import statistics
from typing import NamedTuple

from extractors.coordinate_ruler import CoordinateMapping
from models.export import TrackPlanCurve
from models.markup import HorizontalBand, WorkArea
from models.parsed import ParsedShape

_CURVE_LABEL_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")
_RADIUS_ONLY_RE = re.compile(r"^\s*(\d+)\s*$")
_RADIUS_MIN, _RADIUS_MAX = 100, 20_000

_STEP_THRESHOLD_PX    = 5.0    # cy must deviate > this from baseline to be a step
_STEP_GROUP_GAP_PX    = 20.0   # x-gap between step shapes → new step group
_POLYLINE_JOIN_GAP_PX = 10.0   # x-gap between shapes → new polyline component
_MAX_LABEL_STEP_DIST  = 300.0  # max X dist to match a label to a step


def _cx(s: ParsedShape) -> float:
    return s.x + s.width / 2

def _cy(s: ParsedShape) -> float:
    return s.y + s.height / 2


class _Step(NamedTuple):
    x_left: float
    x_right: float
    direction: str   # "up" | "down"


def _baseline_y(graphic: list[ParsedShape]) -> float:
    """Median cy of horizontal shapes (w >= 2h); falls back to all shapes."""
    horiz = [s for s in graphic if s.height < 1e-6 or s.width >= s.height * 2.0]
    src = horiz if len(horiz) >= 3 else graphic
    return statistics.median(_cy(s) for s in src)


def _detect_steps(graphic: list[ParsedShape], base_y: float) -> list[_Step]:
    """Group shapes displaced from base_y into step objects."""
    displaced = sorted(
        [s for s in graphic if abs(_cy(s) - base_y) > _STEP_THRESHOLD_PX],
        key=lambda s: s.x,
    )
    if not displaced:
        return []

    groups: list[list[ParsedShape]] = [[displaced[0]]]
    for s in displaced[1:]:
        prev_right = max(ps.x + ps.width for ps in groups[-1])
        if s.x <= prev_right + _STEP_GROUP_GAP_PX:
            groups[-1].append(s)
        else:
            groups.append([s])

    steps: list[_Step] = []
    for g in groups:
        x_left  = min(s.x for s in g)
        x_right = max(s.x + s.width for s in g)
        mean_cy = statistics.mean(_cy(s) for s in g)
        steps.append(_Step(
            x_left=x_left, x_right=x_right,
            direction="up" if mean_cy < base_y else "down",
        ))
    return steps


def extract_track_plan(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    work_area: WorkArea,
    coord_mapping: CoordinateMapping,
) -> tuple[list[TrackPlanCurve], dict, list[str]]:
    """Parse the track_plan band into a list of TrackPlanCurve."""
    warnings: list[str] = []

    # ── shapes in band + work_area ────────────────────────────────────────────
    in_band_all = [
        s for s in shapes
        if band.y_top <= _cy(s) <= band.y_bottom
        and work_area.x_start <= _cx(s) <= work_area.x_end
    ]

    graphic = sorted(
        [
            s for s in in_band_all
            if not (s.text and s.text.strip()) and s.shape_type != "Foreign"
        ],
        key=lambda s: s.x,
    )

    # ── N/M labels ────────────────────────────────────────────────────────────
    curve_labels: list[tuple[float, int, int | None]] = []   # (cx, radius, length_or_None)
    for s in in_band_all:
        if not s.text:
            continue
        m = _CURVE_LABEL_RE.match(s.text)
        if m:
            curve_labels.append((_cx(s), int(m.group(1)), int(m.group(2))))
            continue
        m2 = _RADIUS_ONLY_RE.match(s.text)
        if m2:
            r_val = int(m2.group(1))
            if _RADIUS_MIN <= r_val <= _RADIUS_MAX:
                curve_labels.append((_cx(s), r_val, None))

    # ── connected polyline groups ─────────────────────────────────────────────
    polyline_groups: list[list[ParsedShape]] = []
    if graphic:
        cur: list[ParsedShape] = [graphic[0]]
        for s in graphic[1:]:
            prev_right = max(ps.x + ps.width for ps in cur)
            if s.x <= prev_right + _POLYLINE_JOIN_GAP_PX:
                cur.append(s)
            else:
                polyline_groups.append(cur)
                cur = [s]
        polyline_groups.append(cur)

    log: dict = {
        "shapes_in_band_total":  len(in_band_all),
        "path_segments_in_band": len(graphic),
        "merged_polylines":      len(polyline_groups),
        "steps_detected":        0,
        "curve_labels_found":    len(curve_labels),
        "labels_matched_to_steps": 0,
        "orphan_steps":          [],
        "orphan_labels":         [],
    }

    if not graphic:
        warnings.append(
            f"track_plan: no graphic shapes in band+work_area "
            f"({len(in_band_all)} total shapes including text)"
        )
        log["orphan_labels"] = [
            {"cx": round(cx), "radius": r, "length": l}
            for cx, r, l in curve_labels
        ]
        return [], log, warnings

    # ── step detection ────────────────────────────────────────────────────────
    base_y = _baseline_y(graphic)
    steps  = _detect_steps(graphic, base_y)
    log["steps_detected"] = len(steps)

    if not steps:
        warnings.append(
            f"track_plan: no steps detected from {len(graphic)} graphic shapes "
            f"(baseline_y={base_y:.1f}px, threshold={_STEP_THRESHOLD_PX}px). "
            "Verify that band Y bounds cover the plan-path bumps."
        )
        log["orphan_labels"] = [
            {"cx": round(cx), "radius": r, "length": l}
            for cx, r, l in curve_labels
        ]
        return [], log, warnings

    # ── match labels to steps ─────────────────────────────────────────────────
    curve_labels.sort(key=lambda t: t[0])
    matched_step_idxs: set[int] = set()
    curves: list[TrackPlanCurve] = []

    for label_cx, radius, length in curve_labels:
        best_i = -1
        best_d = float("inf")
        for i, step in enumerate(steps):
            d = abs((step.x_left + step.x_right) / 2 - label_cx)
            if d < best_d:
                best_d, best_i = d, i

        if best_i < 0 or best_d > _MAX_LABEL_STEP_DIST:
            log["orphan_labels"].append(
                {"cx": round(label_cx), "radius": radius, "length": length}
            )
            warnings.append(
                f"track_plan: orphan label {radius}/{length} at x={label_cx:.0f}px "
                f"(nearest step {best_d:.0f}px away, threshold {_MAX_LABEL_STEP_DIST}px)"
            )
            continue

        matched_step_idxs.add(best_i)
        step = steps[best_i]
        s_m = round(coord_mapping.x_to_network_coord(step.x_left))
        e_m = round(coord_mapping.x_to_network_coord(step.x_right))
        if s_m > e_m:
            s_m, e_m = e_m, s_m
        curves.append(TrackPlanCurve(
            start=s_m, end=e_m,
            radius=radius, length=length,
            direction=step.direction,  # type: ignore[arg-type]
        ))

    # ── orphan steps (no label) → curves with radius/length = None ────────────
    for i, step in enumerate(steps):
        if i in matched_step_idxs:
            continue
        s_m = round(coord_mapping.x_to_network_coord(step.x_left))
        e_m = round(coord_mapping.x_to_network_coord(step.x_right))
        if s_m > e_m:
            s_m, e_m = e_m, s_m
        log["orphan_steps"].append(
            {"start": s_m, "end": e_m, "direction": step.direction}
        )
        warnings.append(
            f"track_plan: curve without radius/length label "
            f"at x={step.x_left:.0f}–{step.x_right:.0f}px ({s_m}–{e_m} m)"
        )
        curves.append(TrackPlanCurve(
            start=s_m, end=e_m,
            radius=None, length=None,
            direction=step.direction,  # type: ignore[arg-type]
        ))

    curves.sort(key=lambda c: c.start)
    log["labels_matched_to_steps"] = len(matched_step_idxs)

    return curves, log, warnings
