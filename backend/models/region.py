from typing import Any, Literal

from pydantic import BaseModel

RegionType = Literal["profile", "speed_limit", "station", "coordinate_ruler", "track_plan", "other"]


class Region(BaseModel):
    id: str
    type: RegionType
    x: float
    y: float
    width: float
    height: float
    meta: dict[str, Any] = {}
