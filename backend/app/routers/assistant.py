import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai import assistant as engine
from app.db import get_db
from app.models import User
from app.security import current_user, membership

router = APIRouter(prefix="/api/v1/families/{family_id}/assistant", tags=["assistant"])


class Question(BaseModel):
    question: str


@router.post("/ask")
def ask(family_id: uuid.UUID, payload: Question,
        db: Session = Depends(get_db), user: User = Depends(current_user)):
    membership(db, user, family_id)
    return engine.ask(db, family_id, user.id, payload.question)


@router.post("/stream")
def stream_ask(family_id: uuid.UUID, payload: Question,
               db: Session = Depends(get_db), user: User = Depends(current_user)):
    membership(db, user, family_id)

    def event_generator():
        for event in engine.stream_ask(db, family_id, user.id, payload.question):
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
