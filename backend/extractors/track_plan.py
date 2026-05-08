"""Extract track-plan curves from a marked horizontal band."""
from __future__ import annotations

import re
from typing import Optional

from extractors.coordinate_ruler import CoordinateMapping
from models.export import TrackPlanCurve
from models.markup import HorizontalBand, WorkArea
from models.parsed import ParsedShape

# "radius/length" label: "3000/480", "1200/50", etc.
_CURVE_TEXT_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")

# Dark blue: R < 80, G < 80, B > 120
_BLUE_R_MAX = 80
_BLUE_G_MAX = 80
_BLUE_B_MIN = 120

_MIN_STEP_HEIGHT_PX = 3.0       # bumps taller than this; filters out flat baselines
_MAX_TEXT_STEP_DIST_PX = 300.0  # max X distance to pair text with a bump


def _cx(s: ParsedShape) -> float:
    return s.x + s.width / 2


def _cy(s: ParsedShape) -> float:
    return s.y + s.height / 2


def _is_dark_blue(color: Optional[str]) -> bool:
    if not color or len(color) != 7 or color[0] != "#":
        return False
    try:
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        return r < _BLUE_R_MAX and g < _BLUE_G_MAX and b > _BLUE_B_MIN
    except ValueError:
        return False


def _is_blue_shape(s: ParsedShape) -> bool:
    return _is_dark_blue(s.line_color) or _is_dark_blue(s.fill_color)


def extract_track_plan(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    work_area: WorkArea,
    coord_mapping: CoordinateMapping,
) -> tuple[list[TrackPlanCurve], dict, list[str]]:
    """Parse the track_plan band into a list of TrackPlanCurve.

    Algorithm:
    1. Collect blue (dark-blue) shapes inside band+work-area.
    2. Filter to "bumps": height > _MIN_STEP_HEIGHT_PX (excludes flat baseline).
    3. Collect text shapes matching "N/M" (radius/length) in band+work-area.
    4. Pair each text with the nearest bump by X-centre distance.
    5. Determine direction (up/down) from bump centre vs band mid-Y.
    6. Convert bump X extents → network metres via coord_mapping.

    Returns (curves, log_dict, warnings).
    """
    warnings: list[str] = []
    band_mid_y = (band.y_top + band.y_bottom) / 2

    in_band = [
        s for s in shapes
        if band.y_top <= _cy(s) <= band.y_bottom
        and work_area.x_start <= _cx(s) <= work_area.x_end
    ]

    blue_shapes = [s for s in in_band if _is_blue_shape(s)]
    step_shapes = [s for s in blue_shapes if s.height > _MIN_STEP_HEIGHT_PX]

    text_in_band = [
        s for s in shapes
        if s.text
        and band.y_top <= _cy(s) <= band.y_bottom
        and work_area.x_start <= _cx(s) <= work_area.x_end
    ]

    # Parse "N/M" texts: radius 100–20000 m, length 10–100 000 m
    curve_texts: list[tuple[float, int, int]] = []  # (cx, radius, length)
    for s in text_in_band:
        m = _CURVE_TEXT_RE.match(s.text or "")
        if not m:
            continue
        r_val = int(m.group(1))
        l_val = int(m.group(2))
        if 100 <= r_val <= 20_000 and 10 <= l_val <= 100_000:
            curve_texts.append((_cx(s), r_val, l_val))

    log: dict = {
        "shapes_in_band": len(in_band),
        "blue_shapes": len(blue_shapes),
        "step_shapes": len(step_shapes),
        "curve_texts_found": len(curve_texts),
        "curves_matched": 0,
        "unmatched_texts": 0,
    }

    if not step_shapes:
        warnings.append(
            f"track_plan: no blue bump shapes found in band "
            f"({len(blue_shapes)} blue, {len(in_band)} total in band)"
        )
        if not curve_texts:
            warnings.append("track_plan: no N/M curve-label texts found either")
        return [], log, warnings

    step_shapes.sort(key=_cx)

    curves: list[TrackPlanCurve] = []
    unmatched = 0

    for text_cx, radius, length in curve_texts:
        best_step: Optional[ParsedShape] = None
        best_dist = float("inf")
        for step in step_shapes:
            d = abs(_cx(step) - text_cx)
            if d < best_dist:
                best_dist = d
                best_step = step

        if best_step is None or best_dist > _MAX_TEXT_STEP_DIST_PX:
            unmatched += 1
            warnings.append(
                f"track_plan: label {radius}/{length} at x={text_cx:.0f}px "
                f"— nearest bump {best_dist:.0f}px away (threshold {_MAX_TEXT_STEP_DIST_PX}px)"
            )
            continue

        direction: str = "up" if _cy(best_step) < band_mid_y else "down"
        x_left = best_step.x
        x_right = best_step.x + best_step.width
        start_m = round(coord_mapping.x_to_network_coord(x_left))
        end_m = round(coord_mapping.x_to_network_coord(x_right))
        if start_m > end_m:
            start_m, end_m = end_m, start_m

        curves.append(TrackPlanCurve(
            start=start_m,
            end=end_m,
            radius=radius,
            length=length,
            direction=direction,  # type: ignore[arg-type]
        ))

    curves.sort(key=lambda c: c.start)
    log["curves_matched"] = len(curves)
    log["unmatched_texts"] = unmatched

    if not curves:
        warnings.append(
            "track_plan: bump shapes found but no N/M texts matched — "
            "verify that band Y bounds cover both the bumps and their labels"
        )

    return curves, log, warnings
