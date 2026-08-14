from __future__ import annotations

from contextlib import asynccontextmanager, suppress
import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import Organization, User
from .routes import router
from .security import hash_password
from .services import reconcile_all_viewer_lifecycles

logger = logging.getLogger("clientflow")


def bootstrap_admin() -> None:
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    organization_name = os.getenv("ADMIN_ORG_NAME", "Kulturskolen").strip() or "Kulturskolen"
    with SessionLocal() as db:
        existing = db.scalar(select(User.id).limit(1))
        if existing is not None:
            return
        if not email or not password:
            logger.warning("No users exist and ADMIN_EMAIL/ADMIN_PASSWORD are not set")
            return
        organization = Organization(name=organization_name)
        db.add(organization)
        db.flush()
        db.add(
            User(
                organization_id=organization.id,
                email=email,
                password_hash=hash_password(password),
                role="admin",
            )
        )
        db.commit()
        logger.info("Initial admin created for %s", email)


async def viewer_lifecycle_sweeper() -> None:
    while True:
        await asyncio.sleep(settings.viewer_reconcile_interval_seconds)
        try:
            with SessionLocal() as db:
                actions = reconcile_all_viewer_lifecycles(db)
                db.commit()
            for client_id, action in actions:
                logger.info("Livestream viewer lifecycle: client=%s action=%s", client_id, action)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Livestream viewer lifecycle sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.hls_root.mkdir(parents=True, exist_ok=True)
    bootstrap_admin()
    task = asyncio.create_task(viewer_lifecycle_sweeper())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="ClientFlow Livestream", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self'; "
        "connect-src 'self'; media-src 'self' blob:; worker-src 'self' blob:; img-src 'self' data:; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    return response

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
