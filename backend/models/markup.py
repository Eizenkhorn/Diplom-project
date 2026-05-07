from typing import Literal, Any

from pydantic import BaseModel, field_validator

from models.markup_types import VALID_MARK_SUBTYPES

BandType = Literal["speed_limits", "profile", "track_plan", "traction_modes", "coordinate_ruler"]


class WorkArea(BaseModel):
    x_start: float
    x_end: float


class HorizontalBand(BaseModel):
    id: str
    type: BandType
    y_top: float
    y_bottom: float
    extracted: dict[str, Any] = {}


class StationPoint(BaseModel):
    id: str
    x: float
    name: str


class MarkPoint(BaseModel):
    id: str
    x: float
    y: float
    subtype: str
    meta: dict[str, Any] = {}

    @field_validator("subtype")
    @classmethod
    def _validate_subtype(cls, v: str) -> str:
        if v not in VALID_MARK_SUBTYPES:
            raise ValueError(f"Unknown mark subtype '{v}'")
        return v


class SessionMarkup(BaseModel):
    work_area: WorkArea | None = None
    bands: list[HorizontalBand] = []
    stations: list[StationPoint] = []
    marks: list[MarkPoint] = []
