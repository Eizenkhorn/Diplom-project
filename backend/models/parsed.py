from pydantic import BaseModel


class ParsedShape(BaseModel):
    id: str
    text: str | None
    x: float                # left-top bbox px, Konva system (y grows down)
    y: float
    width: float
    height: float
    rotation: float         # degrees, CCW from Visio Angle cell
    shape_type: str         # "Shape" | "Group" | "Foreign" | "Connector"
    parent_id: str | None   # ID of containing Group, or None for top-level


class ParsedDocument(BaseModel):
    page_width: float       # canvas size in pixels
    page_height: float
    shapes: list[ParsedShape]
