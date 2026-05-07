from typing import Any

from pydantic import BaseModel, field_validator

from models.annotation_types import VALID_REGION_TYPES


class Region(BaseModel):
    id: str
    type: str
    x: float
    y: float
    width: float
    height: float
    meta: dict[str, Any] = {}

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        if v not in VALID_REGION_TYPES:
            raise ValueError(f"Unknown region type '{v}'")
        return v
