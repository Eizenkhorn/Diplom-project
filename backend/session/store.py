import uuid
from models.parsed import ParsedDocument

sessions: dict[str, ParsedDocument] = {}


def create_session(doc: ParsedDocument) -> str:
    sid = str(uuid.uuid4())
    sessions[sid] = doc
    return sid


def get_session(sid: str) -> ParsedDocument | None:
    return sessions.get(sid)
