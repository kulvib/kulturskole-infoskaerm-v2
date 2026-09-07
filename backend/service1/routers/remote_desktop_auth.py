"""Remote Desktop-owned HTTP authentication boundary for the installed agent."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..db import engine
from ..remote_desktop_v2 import issue_remote_desktop_token_response

router = APIRouter(tags=["remote-desktop-auth"])


class RemoteDesktopTokenBody(BaseModel):
    client_id: int = Field(gt=0)
    credential_id: str = Field(min_length=1, max_length=64)
    domain: str = Field(default="remote_desktop", min_length=1, max_length=64)
    client_secret: str = Field(min_length=32, max_length=512)


@router.post("/remote-desktop-auth/token")
def remote_desktop_token(body: RemoteDesktopTokenBody):
    if body.domain != "remote_desktop":
        raise HTTPException(status_code=404, detail="Domæne-endpoint ikke fundet")
    with Session(engine) as session:
        response = issue_remote_desktop_token_response(
            session,
            client_id=body.client_id,
            credential_id=body.credential_id,
            client_secret=body.client_secret,
        )
        session.commit()
        return response
