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
        return (k1 + t * (k2 - k1)) * 1000.0


def extract_coordinate_ruler(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    work_area: WorkArea,
) -> tuple[CoordinateMapping, list[str]]:
    """Parse the coordinate ruler band into a CoordinateMapping.

    Returns (mapping, warnings).
    """
    warnings: list[str] = []

    # Filter: text shapes in band's Y range and work area's X range
    candidates = [
        s for s in shapes
        if s.text is not None
        and _in_band_y(s, band)
        and _in_work_area_x(s, work_area)
    ]

    # Extract kilometer labels: integer 1-9999
    points: list[tuple[float, int]] = []
    for s in candidates:
        m = _KM_RE.match(s.text or "")
        if m:
            km = int(m.group(1))
            if 1 <= km <= 9999:
                points.append((_shape_center_x(s), km))

    if len(points) < 2:
        warnings.append(
            f"coordinate_ruler: found only {len(points)} km labels "
            f"(need ≥ 2 for interpolation)"
        )

    # Sort by x
    points.sort(key=lambda p: p[0])

    # Remove duplicate X positions (keep first occurrence)
    deduped: list[tuple[float, int]] = []
    seen_x: set[int] = set()
    for x, km in points:
        ix = round(x)
        if ix not in seen_x:
            deduped.append((x, km))
            seen_x.add(ix)
    points = deduped

    # Detect direction from first and last km values
    if len(points) >= 2:
        direction: Literal["ascending", "descending"] = (
            "ascending" if points[-1][1] > points[0][1] else "descending"
        )
        # Validate rough monotonicity (allow ±1 km jitter from OCR/label errors)
        non_mono = 0
        for i in range(1, len(points)):
            delta = points[i][1] - points[i - 1][1]
            if direction == "ascending" and delta < -1:
                non_mono += 1
            elif direction == "descending" and delta > 1:
                non_mono += 1
        if non_mono > len(points) // 4:
            warnings.append(
                f"coordinate_ruler: {non_mono} non-monotone km steps detected — "
                "check band placement"
            )
    else:
        direction = "descending"

    mapping = CoordinateMapping(points=points, direction=direction)
    return mapping, warnings
