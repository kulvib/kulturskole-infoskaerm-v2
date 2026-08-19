"""Terminal-owned HTTP authentication boundary for the ClientFlow Terminal agent."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..db import engine
from ..terminal_v2 import issue_terminal_token_response

router = APIRouter(tags=["terminal-auth"])


class TerminalTokenBody(BaseModel):
    client_id: int = Field(gt=0)
    credential_id: str = Field(min_length=1, max_length=64)
    domain: str = Field(default="terminal", min_length=1, max_length=64)
    client_secret: str = Field(min_length=32, max_length=512)


@router.post("/terminal-auth/token")
def terminal_token(body: TerminalTokenBody):
    """Issue a token from Terminal-owned credential storage only."""
    if body.domain != "terminal":
        raise HTTPException(status_code=404, detail="Domæne-endpoint ikke fundet")
    with Session(engine) as session:
        response = issue_terminal_token_response(
            session,
            client_id=body.client_id,
            credential_id=body.credential_id,
            client_secret=body.client_secret,
        )
        session.commit()
        return response
