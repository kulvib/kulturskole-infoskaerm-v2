import asyncio
import logging
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from sqlmodel import Session, select, text
from sqlalchemy import or_
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

load_dotenv()

logger = logging.getLogger(__name__)

from .routers import clients
from .routers import calendar
from .routers import organizations
from .routers import users
from .routers import livestream_media
from .routers.livestream_v2 import router as livestream_v2_router
from .routers.client_auth_compat import router as client_auth_compat_router
from .routers.shared_domain import router as shared_domain_router
from .routers.terminal_auth import router as terminal_auth_router
from .routers import enrollment
from .routers import clientflow_releases
from .routers import clientflow_deployments
from .routers import clientflow_update
from .routers import websocket_tickets
from .routers.remote_desktop_auth import router as remote_desktop_auth_router
from .routers.remote_desktop_v2 import router as remote_desktop_v2_router
from .routers.terminal import agent_router as terminal_agent_router, router as terminal_router
from .routers.livestream_media import HLS_DIR

from .auth import (
    router as auth_router,
    get_current_superadmin_user,
    principal_is_client,
    verify_ws_token,
)
from .db import engine
from .models import Client, RefreshToken, User
from .branding import PRODUCT_NAME
from .schema_readiness import check_schema_readiness
from .release_identity import ReleaseIdentityUnavailable, build_release_identity
from .rate_limit import RateLimitExceeded, rate_limit_exception_handler
from .season_service import (
    maintain_current_and_next_seasons,
    seconds_until_next_daily_maintenance,
)
from .observability import (
    REQUEST_ID_HEADER,
    add_request_id_header,
    bind_request_id,
    get_request_id,
    json_error_response,
    log_safe_exception,
    log_unexpected_exception,
    reset_request_id,
)

IS_PRODUCTION = os.getenv("ENVIRONMENT", "production").strip().lower() == "production"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} skal være et heltal") from exc
    if value < minimum:
        raise RuntimeError(f"{name} skal være mindst {minimum}")
    return value


REFRESH_TOKEN_RETENTION_DAYS = _env_int("REFRESH_TOKEN_RETENTION_DAYS", 7, 1)
REFRESH_TOKEN_CLEANUP_INTERVAL_SECONDS = _env_int(
    "REFRESH_TOKEN_CLEANUP_INTERVAL_SECONDS",
    3600,
    300,
)


def _normalize_cors_origin(raw: str | None) -> str | None:
    """Normaliser og valider en CORS-origin.

    CORS-origins må ikke indeholde path, query, fragment eller trailing slash.
    Det forebygger browser-level NetworkError, hvis Render env f.eks. sættes til
    https://display.planiq.dk/ i stedet for https://display.planiq.dk.
    """
    raw = (raw or "").strip().rstrip("/")
    if not raw:
        return None

    parsed = urlparse(raw)
    has_path_or_extra = bool(parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or has_path_or_extra:
        logger.warning("invalid_cors_origin_ignored")
        return None

    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _parse_allowed_origins() -> list[str]:
    origins: list[str] = []
    candidates: list[str] = []

    raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    if raw:
        candidates.extend([o.strip() for o in raw.split(",") if o.strip()])

    candidates.extend([
        os.getenv("FRONTEND_URL", ""),
        os.getenv("PASSWORD_RESET_FRONTEND_URL", ""),
        "https://display.planiq.dk",
        "https://www.display.planiq.dk",
    ])

    if not IS_PRODUCTION:
        candidates.extend([
            "http://localhost:5173",
            "http://localhost:4173",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:4173",
        ])

    for candidate in candidates:
        normalized = _normalize_cors_origin(candidate)
        if normalized and normalized not in origins:
            origins.append(normalized)

    return origins


ALLOWED_ORIGINS = _parse_allowed_origins()
if not ALLOWED_ORIGINS:
    raise RuntimeError(
        "Ingen CORS origins konfigureret — sæt FRONTEND_URL eller CORS_ALLOW_ORIGINS i miljøvariabler."
    )

logger.info("cors_origins_configured count=%s", len(ALLOWED_ORIGINS))


def _origin_from_referer(referer: str | None) -> str | None:
    if not referer:
        return None
    try:
        parsed = urlparse(referer)
        if not parsed.scheme or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        return None


def _request_origin_is_allowed(request: Request) -> bool:
    origin = request.headers.get("origin") or _origin_from_referer(request.headers.get("referer"))
    if origin:
        return origin in ALLOWED_ORIGINS
    return not IS_PRODUCTION


def _request_uses_cookie_auth(request: Request) -> bool:
    if not (request.cookies.get("access_token") or request.cookies.get("refresh_token")):
        return False
    authorization = request.headers.get("authorization") or ""
    return not authorization.lower().startswith("bearer ")





def cleanup_expired_refresh_tokens_once() -> int:
    """Slet gamle refresh-token-rækker efter den konfigurerede retentionperiode."""
    cutoff = (
        datetime.now(timezone.utc).replace(tzinfo=None)
        - timedelta(days=REFRESH_TOKEN_RETENTION_DAYS)
    )
    with Session(engine) as session:
        try:
            rows = session.exec(
                select(RefreshToken).where(
                    or_(
                        RefreshToken.expires_at < cutoff,
                        RefreshToken.session_expires_at < cutoff,
                        (
                            RefreshToken.revoked_at.is_not(None)
                            & (RefreshToken.revoked_at < cutoff)
                        ),
                    )
                )
            ).all()
            for row in rows:
                session.delete(row)
            if rows:
                session.commit()
                logger.info("Refresh-token cleanup: slettede %s gamle rækker", len(rows))
            return len(rows)
        except Exception as exc:
            session.rollback()
            log_safe_exception(logger, exc, event="refresh_token_cleanup_failed")
            return 0


def maintain_seasons_once() -> dict | None:
    """Ensure current/next seasons and remove passed season data."""
    with Session(engine) as session:
        try:
            summary = maintain_current_and_next_seasons(session)
            session.commit()
            logger.info(
                "Season maintenance completed: current=%s next=%s org_seasons=%s calendars=%s filled_days=%s deleted_calendar_seasons=%s deleted_organization_seasons=%s",
                summary["current_season"],
                summary["next_season"],
                summary["created_organization_seasons"],
                summary["created_client_calendars"],
                summary["filled_calendar_days"],
                summary["deleted_calendar_seasons"],
                summary["deleted_organization_seasons"],
            )
            return summary
        except Exception as exc:
            session.rollback()
            log_safe_exception(logger, exc, event="season_maintenance_failed")
            return None


async def season_maintenance_loop() -> None:
    """Run season rollover maintenance daily at 00:05 Europe/Copenhagen."""
    while True:
        try:
            await asyncio.sleep(seconds_until_next_daily_maintenance())
            await asyncio.to_thread(maintain_seasons_once)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_safe_exception(logger, exc, event="season_maintenance_loop_failed")


async def refresh_token_cleanup_loop() -> None:
    """Kør refresh-token-oprydning periodisk uden at blokere event loopet."""
    while True:
        try:
            await asyncio.sleep(REFRESH_TOKEN_CLEANUP_INTERVAL_SECONDS)
            await asyncio.to_thread(cleanup_expired_refresh_tokens_once)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_safe_exception(logger, exc, event="refresh_token_cleanup_loop_failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(cleanup_expired_refresh_tokens_once)
    await asyncio.to_thread(maintain_seasons_once)
    cleanup_task = asyncio.create_task(refresh_token_cleanup_loop())
    season_task = asyncio.create_task(season_maintenance_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        season_task.cancel()
        for task in (cleanup_task, season_task):
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title=f"{PRODUCT_NAME} API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if os.getenv("ENVIRONMENT") == "production" else "/docs",
    redoc_url=None if os.getenv("ENVIRONMENT") == "production" else "/redoc",
    openapi_url=None if os.getenv("ENVIRONMENT") == "production" else "/openapi.json",
)
app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "Cache-Control",
        "Pragma",
        "Expires",
        "If-Modified-Since",
        "Range",
        "X-CSRF-Token",
        REQUEST_ID_HEADER,
    ],
    expose_headers=[REQUEST_ID_HEADER],
)



def _cors_origin_for_request(request):
    """Returnér en tilladt Origin til manuelle fejl-responses."""
    origin = request.headers.get("origin")
    if origin and origin in ALLOWED_ORIGINS:
        return origin
    return ALLOWED_ORIGINS[0] if ALLOWED_ORIGINS else "*"


def _apply_security_headers(request, response):
    """Tilføj Worklog/Flow-inspirerede basis security headers på API-svar.

    Render-headerne beskytter den statiske frontend. Denne middleware sikrer,
    at backend/API-svar også får et konsistent sikkerhedslag.
    """
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Permissions-Policy"] = (
        "geolocation=(), camera=(), microphone=(), payment=(), usb=(), "
        "bluetooth=(), accelerometer=(), gyroscope=(), magnetometer=()"
    )
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # API'et skal ikke kunne indlæse aktive ressourcer. Frontend-CSP sættes i render.yaml.
    if not request.url.path.startswith("/hls/"):
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    return response


def _apply_cors_headers(request, response):
    """
    CORSMiddleware får ikke altid lov at sætte headers på exceptions, der bliver
    til 500/503. Derfor sætter vi dem manuelt på vores fejl-responses, så
    browseren viser den rigtige backend-fejl i stedet for en misvisende CORS-fejl.
    """
    origin = _cors_origin_for_request(request)
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Vary"] = "Origin"
    return _apply_security_headers(request, response)


@app.middleware("http")
async def csrf_origin_middleware(request: Request, call_next):
    # Når browseren autentificerer via HttpOnly-cookie, skal muterende requests
    # komme fra en kendt frontend-origin. Bearer-token klienter påvirkes ikke.
    if request.method.upper() in UNSAFE_METHODS and _request_uses_cookie_auth(request):
        if not _request_origin_is_allowed(request):
            return _apply_cors_headers(
                request,
                JSONResponse(
                    status_code=403,
                    content={"detail": "Ugyldig eller manglende Origin for cookie-autentificeret request"},
                ),
            )
    return await call_next(request)


class HLSCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/hls/"):
            origin = request.headers.get("origin", "")
            allowed_origin = origin if origin in ALLOWED_ORIGINS else (ALLOWED_ORIGINS[0] if ALLOWED_ORIGINS else "*")

            if request.method == "OPTIONS":
                return Response(
                    status_code=204,
                    headers={
                        "Access-Control-Allow-Origin":  allowed_origin,
                        "Access-Control-Allow-Methods": "GET, OPTIONS, HEAD",
                        "Access-Control-Allow-Headers": "Authorization, Content-Type, Range",
                        "Access-Control-Allow-Credentials": "true",
                        "Access-Control-Max-Age":       "86400",
                    }
                )

            response = await call_next(request)
            response.headers["Access-Control-Allow-Origin"]      = allowed_origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"]     = "GET, OPTIONS, HEAD"
            response.headers["Access-Control-Allow-Headers"]     = "Authorization, Content-Type, Range"

            if request.url.path.endswith((".m3u8", ".ts", ".mp4")):
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                response.headers["Pragma"]        = "no-cache"
                response.headers["Expires"]       = "0"
            else:
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

            return response

        return await call_next(request)


app.add_middleware(HLSCORSMiddleware)


@app.middleware("http")
async def request_observability_middleware(request: Request, call_next):
    """Knyt alle HTTP-svar og uventede fejl til et sikkert request-id.

    Middleware-laget ligger yderst omkring Display-specifik HLS/CORS-håndtering,
    så også HLS-preflight og globale fejl får samme korrelations-id.
    """
    request_id, token = bind_request_id(request)
    try:
        try:
            response = await call_next(request)
        except SQLAlchemyTimeoutError as exc:
            log_unexpected_exception(
                logger,
                request,
                exc,
                status_code=503,
                event="database_pool_timeout",
                level=logging.WARNING,
            )
            response = json_error_response(
                request,
                status_code=503,
                error="database_unavailable",
                detail="Databasen er midlertidigt utilgængelig. Prøv igen senere.",
            )
        except Exception as exc:
            log_unexpected_exception(
                logger,
                request,
                exc,
                status_code=500,
                event="unexpected_request_error",
            )
            response = json_error_response(
                request,
                status_code=500,
                error="internal_server_error",
                detail="En intern serverfejl opstod. Prøv igen senere.",
            )

        response = _apply_cors_headers(request, response)
        return add_request_id_header(response, request_id)
    finally:
        reset_request_id(token)


def _hls_stop_marker_exists_for_static(path: str) -> bool:
    try:
        client_id_text = (path or "").split("/", 1)[0]
        if not client_id_text:
            return False
        marker_path = os.path.join(HLS_DIR, client_id_text, ".stream_stopped.json")
        return os.path.exists(marker_path)
    except Exception:
        return False


class AuthenticatedHLSStaticFiles(StaticFiles):
    def _extract_bearer_token(self, request: Request) -> str | None:
        authorization = request.headers.get("authorization") or ""
        if authorization.lower().startswith("bearer "):
            return authorization[7:]
        return request.cookies.get("access_token")

    def _check_hls_access(self, request: Request, path: str) -> None:
        # HLS-filer ligger under /hls/{client_id}/... . Uden numerisk client_id
        # afviser vi i stedet for at expose vilkårlige filer i HLS_DIR.
        client_id_text = (path or "").split("/", 1)[0]
        try:
            client_id = int(client_id_text)
        except Exception:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HLS stream ikke fundet")

        token = self._extract_bearer_token(request)
        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ikke logget ind")
        if _request_uses_cookie_auth(request) and not _request_origin_is_allowed(request):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ugyldig Origin for HLS stream")

        with Session(engine) as session:
            principal = verify_ws_token(token, session)
            if not principal:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ugyldigt token")

            client = session.get(Client, client_id)
            if not client:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HLS stream ikke fundet")

            if principal_is_client(principal):
                if principal.id == client_id and client.status == "approved":
                    return
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ingen adgang til HLS stream")

            if getattr(principal, "is_superadmin", False):
                return

            same_org = getattr(principal, "organization_id", None) == getattr(client, "organization_id", None)
            if getattr(principal, "is_admin", False) and same_org:
                return

            if (
                getattr(principal, "role", None) in ("bruger", "viewer")
                and client.status == "approved"
                and same_org
            ):
                return

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ingen adgang til HLS stream")

    async def get_response(self, path, scope):
        request = Request(scope)
        self._check_hls_access(request, path)

        # Når Ubuntu-klienten har kvitteret et eksplicit livestream_stop, skriver
        # backend en stop-marker. Den skjuler gamle manifest/segmenter, indtil en
        # ny uploader-generation udfører det autoritative HLS-reset.
        if path.endswith((".m3u8", ".ts", ".mp4")) and _hls_stop_marker_exists_for_static(path):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HLS stream er stoppet")

        # index.m3u8 is rewritten in-place by the generation-aware uploader.
        # Starlette FileResponse stats the file before streaming it; if the
        # playlist grows between stat() and send(), Content-Length becomes stale
        # and Uvicorn raises "Response content longer than Content-Length".
        # Snapshot the small playlist into memory first so headers and body are
        # always derived from the exact same immutable bytes.
        if path.endswith('.m3u8'):
            full_path, stat_result = await asyncio.to_thread(self.lookup_path, path)
            if stat_result is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HLS stream ikke fundet")
            try:
                payload = await asyncio.to_thread(Path(full_path).read_bytes)
            except (FileNotFoundError, IsADirectoryError, PermissionError):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HLS stream ikke fundet")
            response = Response(content=payload, media_type="application/vnd.apple.mpegurl")
        else:
            response = await super().get_response(path, scope)

        if path.endswith('.m3u8'):
            response.headers["Content-Type"] = "application/vnd.apple.mpegurl"
        elif path.endswith('.ts'):
            response.headers["Content-Type"] = "video/mp2t"
        elif path.endswith('.mp4'):
            response.headers["Content-Type"] = "video/mp4"
        if path.endswith(('.m3u8', '.ts', '.mp4')):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


app.mount("/hls", AuthenticatedHLSStaticFiles(directory=HLS_DIR), name="hls")
logger.info("hls_static_mount_configured")

app.include_router(clients.router,    prefix="/api")
app.include_router(organizations.router, prefix="/api")
# Browser-login bruger /auth/* direkte. /api/auth/* bevares som Worklog-kompatibelt alias,
# så gamle bundles eller Render rewrites ikke sender auth-kald til frontendens SPA fallback.
app.include_router(auth_router,       prefix="/auth")
app.include_router(auth_router,       prefix="/api/auth")
app.include_router(calendar.router,   prefix="/api")
app.include_router(users.router,      prefix="/api")
app.include_router(enrollment.router, prefix="/api")
app.include_router(clientflow_releases.router, prefix="/api")
app.include_router(clientflow_deployments.router, prefix="/api")
app.include_router(clientflow_update.router, prefix="/api")
app.include_router(websocket_tickets.router, prefix="/api")
app.include_router(livestream_media.router, prefix="/api")
app.include_router(client_auth_compat_router, prefix="/api")
app.include_router(shared_domain_router, prefix="/api")
app.include_router(livestream_v2_router, prefix="/api")
app.include_router(terminal_auth_router,    prefix="/api")
app.include_router(remote_desktop_auth_router, prefix="/api")
app.include_router(remote_desktop_v2_router, prefix="/api")
app.include_router(terminal_router,        prefix="/api")
app.include_router(terminal_agent_router,  prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/version")
def version(request: Request):
    """Returnér deploymentets ufølsomme releaseidentitet uden databasekald."""
    try:
        payload = build_release_identity(PRODUCT_NAME)
    except ReleaseIdentityUnavailable:
        logger.warning(
            "release_identity_unavailable request_id=%s",
            get_request_id(request),
        )
        response = json_error_response(
            request,
            status_code=503,
            error="release_identity_unavailable",
            detail="Releaseidentiteten er ikke tilgængelig",
            extra={"status": "unavailable"},
        )
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    response = JSONResponse(content=payload)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response



@app.get("/health/db")
def health_db(request: Request):
    """Kontrollér både databaseforbindelse og Alembic schema-readiness."""
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1"))
            schema_status = check_schema_readiness(session.connection())
    except Exception as exc:
        logger.warning(
            "database_health_check_failed request_id=%s error_type=%s",
            get_request_id(request),
            type(exc).__name__,
        )
        return json_error_response(
            request,
            status_code=503,
            error="database_unavailable",
            detail="Databasen svarer ikke",
            extra={"status": "unavailable"},
        )

    if not schema_status.ready:
        logger.warning(
            "database_schema_not_ready request_id=%s reason=%s "
            "repository_head_count=%s database_head_count=%s",
            get_request_id(request),
            schema_status.reason,
            schema_status.repository_head_count,
            schema_status.database_head_count,
        )
        return json_error_response(
            request,
            status_code=503,
            error="database_schema_not_ready",
            detail="Databaseskemaet er ikke klar",
            extra={"status": "unavailable"},
        )

    return {"status": "ok"}


@app.get("/health/db-pool")
def health_db_pool(
    request: Request,
    _admin: User = Depends(get_current_superadmin_user),
):
    """Debug-endpoint til Render. Kræver superadmin og lækker ikke exceptions."""
    try:
        return {
            "status": "ok",
            "pool": engine.pool.status(),
        }
    except Exception as exc:
        logger.warning(
            "database_pool_health_check_failed request_id=%s error_type=%s",
            get_request_id(request),
            type(exc).__name__,
        )
        return json_error_response(
            request,
            status_code=503,
            error="database_unavailable",
            detail="Databasen svarer ikke",
            extra={"status": "unavailable"},
        )


@app.get("/")
def read_root():
    return {"message": f"{PRODUCT_NAME} API kører"}


@app.get("/ping")
def ping():
    return {"message": "pong"}
