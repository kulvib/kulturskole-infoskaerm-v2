"""Remote Desktop short-lived browser WebSocket ticket endpoint.

The HTTP request remains same-origin through display.planiq.dk, while the
returned one-time ticket authorizes one direct Remote Desktop WebSocket
connection to the backend web service without exposing the ordinary access
token in a URL. Terminal has a separate ticket endpoint and runtime store.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..auth import (
    get_current_superadmin_user,
    oauth2_scheme,
    require_active_browser_auth_session_binding,
)
from ..db import get_session
from ..models import Client, User
from ..rate_limit import enforce_request_rate_limit
from ..websocket_auth import (
    BrowserWsTicketStoreFull,
    issue_browser_ws_ticket,
)

router = APIRouter(prefix="/websocket-tickets", tags=["websocket-auth"])
logger = logging.getLogger(__name__)


class BrowserWsCapability(str, Enum):
    REMOTE_DESKTOP = "remote_desktop"


class BrowserWsTicketRequest(BaseModel):
    client_id: int = Field(gt=0)
    capability: BrowserWsCapability


class BrowserWsTicketResponse(BaseModel):
    ticket: str
    subprotocol: str
    expires_at: datetime


@router.post("/browser", response_model=BrowserWsTicketResponse)
def create_browser_ws_ticket(
    payload: BrowserWsTicketRequest,
    request: Request,
    response: Response,
    user: User = Depends(get_current_superadmin_user),
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> BrowserWsTicketResponse:
    """Create one ticket bound to user, client and exact browser capability."""
    enforce_request_rate_limit(
        request,
        bucket="browser-ws-ticket",
        max_attempts=120,
        window_seconds=60,
        detail="For mange WebSocket-forbindelsesforsøg. Prøv igen om lidt.",
    )

    client = session.get(Client, payload.client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Klient ikke fundet")

    auth_session_binding = require_active_browser_auth_session_binding(
        session,
        token=token,
        user=user,
    )

    try:
        issued = issue_browser_ws_ticket(
            user=user,
            client_id=payload.client_id,
            capability=payload.capability.value,
            auth_session_binding=auth_session_binding,
        )
    except BrowserWsTicketStoreFull as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WebSocket-forbindelser er midlertidigt utilgængelige",
        ) from exc

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    logger.info(
        "browser_ws_ticket_issued client_id=%s user_id=%s capability=%s",
        payload.client_id,
        user.id,
        payload.capability.value,
    )
    return BrowserWsTicketResponse(
        ticket=issued.ticket,
        subprotocol=issued.subprotocol,
        expires_at=issued.expires_at,
    )
