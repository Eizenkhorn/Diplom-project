from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class TrackPlanCurve(BaseModel):
    start: int            # network metres
    end: int
    radius: int | None    # curve radius, metres; None if no label found
    length: int | None    # curve length, metres; None if no label found
    direction: Literal["up", "down"]   # side from baseline


class LocomotiveRegimeSegment(BaseModel):
    start: int
    end: int
    mode: Literal["traction", "coasting", "braking", "unknown"]
    mode_label: str       # original text label from map
    color: str            # hex colour of the band line


class LocomotiveRegimeBand(BaseModel):
    locomotive_type: str         # e.g. "2ТЭ116"
    weight: int | None           # tonnes, may be absent
    raw_label: str               # full original label text
    segments: list[LocomotiveRegimeSegment]
