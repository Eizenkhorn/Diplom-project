import shutil
import uuid
from dataclasses import dataclass, field

from models.markup import SessionMarkup
from models.parsed import ParsedDocument


@dataclass
class Session:
    doc: ParsedDocument
    svg_path: str
    tmpdirs: list[str] = field(default_factory=list)
    markup: SessionMarkup = field(default_factory=SessionMarkup)
    edited_data: dict | None = None


sessions: dict[str, Session] = {}


def create_session(doc: ParsedDocument, svg_path: str, tmpdirs: list[str]) -> str:
    sid = str(uuid.uuid4())
    sessions[sid] = Session(doc=doc, svg_path=svg_path, tmpdirs=tmpdirs)
    return sid


def get_session(sid: str) -> Session | None:
    return sessions.get(sid)


def delete_session(sid: str) -> None:
    session = sessions.pop(sid, None)
    if session:
        for d in session.tmpdirs:
            shutil.rmtree(d, ignore_errors=True)
