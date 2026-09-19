from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
import os
from time import perf_counter
import sys
import warnings
import weakref

from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

load_dotenv()


def _env_int(name: str, default: int, *, min_value: int | None = None) -> int:
    """Læs integer fra miljøvariabel med sikker fallback."""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        warnings.warn(
            f"[DB] Ugyldig værdi for {name}={raw!r}; bruger default {default}",
            RuntimeWarning,
            stacklevel=2,
        )
        return default
    if min_value is not None and value < min_value:
        warnings.warn(
            f"[DB] {name}={value} er under minimum {min_value}; bruger {min_value}",
            RuntimeWarning,
            stacklevel=2,
        )
        return min_value
    return value


def _normalize_database_url(url: str) -> str:
    """
    Render/Heroku-lignende miljøer kan levere postgres://.
    SQLAlchemy forventer normalt postgresql://.
    """
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


IS_PRODUCTION = os.getenv("ENVIRONMENT", "production").strip().lower() == "production"
_DATABASE_URL_RAW = os.getenv("DATABASE_URL", "").strip()
DATABASE_URL_CONFIGURED = bool(_DATABASE_URL_RAW)

if not _DATABASE_URL_RAW:
    if IS_PRODUCTION:
        raise RuntimeError(
            "DATABASE_URL mangler. Backend nægter at starte i production uden eksplicit database."
        )
    _DATABASE_URL_RAW = "sqlite:///database.db"
    warnings.warn(
        "DATABASE_URL mangler; bruger lokal SQLite fallback, fordi ENVIRONMENT ikke er production.",
        RuntimeWarning,
        stacklevel=2,
    )

DATABASE_URL = _normalize_database_url(_DATABASE_URL_RAW)
IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_PRODUCTION and IS_SQLITE:
    raise RuntimeError(
        "SQLite må ikke bruges i production. Sæt DATABASE_URL til PostgreSQL/Neon i Render."
    )

if IS_SQLITE:
    try:
        workers_arg = sys.argv[sys.argv.index("--workers") + 1] if "--workers" in sys.argv else "1"
        num_workers = int(workers_arg)
    except (ValueError, IndexError):
        num_workers = 1
    if num_workers > 1:
        warnings.warn(
            "ADVARSEL: SQLite er ikke sikkert med flere workers. "
            "Brug PostgreSQL i produktion.",
            RuntimeWarning,
            stacklevel=2,
        )

_echo = os.getenv("ENVIRONMENT", "production") != "production"

# ---------------------------------------------------------------------------
# Engine / connection pool
# ---------------------------------------------------------------------------
# Din Render-fejl viste SQLAlchemy standard-poolen:
#   QueuePool limit of size 5 overflow 10 reached
# Derfor konfigurerer vi poolen eksplicit via Render Environment.
#
# Anbefalet start for Neon Free:
#   DB_POOL_SIZE=5
#   DB_MAX_OVERFLOW=2
#   DB_POOL_TIMEOUT=20
#   DB_POOL_RECYCLE=300
#
# Det betyder højst 7 samtidige DB-forbindelser fra denne backend-instans.
# Det begrænser ikke antallet af klienter; det begrænser kun samtidige DB-kald.
# ---------------------------------------------------------------------------
DB_POOL_SIZE = _env_int("DB_POOL_SIZE", 5, min_value=1)
DB_MAX_OVERFLOW = _env_int("DB_MAX_OVERFLOW", 2, min_value=0)
DB_POOL_TIMEOUT = _env_int("DB_POOL_TIMEOUT", 20, min_value=1)
DB_POOL_RECYCLE = _env_int("DB_POOL_RECYCLE", 300, min_value=30)

engine_kwargs: dict = {
    "echo": _echo,
}

if IS_SQLITE:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
    # Gør in-memory SQLite stabil ved tests; almindelig file-SQLite påvirkes ikke negativt.
    if DATABASE_URL in {"sqlite://", "sqlite:///:memory:"}:
        engine_kwargs["poolclass"] = StaticPool
else:
    engine_kwargs.update({
        "pool_size": DB_POOL_SIZE,
        "max_overflow": DB_MAX_OVERFLOW,
        "pool_timeout": DB_POOL_TIMEOUT,
        "pool_recycle": DB_POOL_RECYCLE,
        # Tjekker forbindelsen før genbrug, så døde Neon/Render connections ikke giver fejl.
        "pool_pre_ping": True,
        # LIFO genbruger varme forbindelser og lader ældre forbindelser lukke/recycles.
        "pool_use_lifo": True,
    })

engine = create_engine(DATABASE_URL, **engine_kwargs)


@dataclass
class DatabaseRequestMetrics:
    """Dataminimerede DB-målinger for én HTTP-request.

    Ingen SQL-tekst, parametre, credentials eller databasehost gemmes. Objektet er
    mutabelt med vilje: AnyIO kopierer ContextVar-konteksten til sync endpoint-
    workers, og begge contexts kan dermed opdatere/læse det samme metrics-objekt.
    """

    statement_count: int = 0
    select_count: int = 0
    checkout_count: int = 0
    duration_ms: float = 0.0


_REQUEST_DB_METRICS: ContextVar[DatabaseRequestMetrics | None] = ContextVar(
    "clientflow_request_db_metrics",
    default=None,
)
_INSTRUMENTED_ENGINES: weakref.WeakSet[Engine] = weakref.WeakSet()


def begin_database_request_metrics() -> tuple[DatabaseRequestMetrics, Token]:
    metrics = DatabaseRequestMetrics()
    return metrics, _REQUEST_DB_METRICS.set(metrics)


def reset_database_request_metrics(token: Token) -> None:
    _REQUEST_DB_METRICS.reset(token)


def _metrics_before_cursor_execute(_conn, _cursor, statement, _parameters, context, _executemany) -> None:
    metrics = _REQUEST_DB_METRICS.get()
    if metrics is None:
        return
    metrics.statement_count += 1
    if str(statement).lstrip().upper().startswith("SELECT"):
        metrics.select_count += 1
    # ExecutionContext er statement-lokalt og undgår global/thread-local timing-state.
    context._clientflow_db_started_at = perf_counter()


def _metrics_after_cursor_execute(_conn, _cursor, _statement, _parameters, context, _executemany) -> None:
    metrics = _REQUEST_DB_METRICS.get()
    if metrics is None:
        return
    started_at = getattr(context, "_clientflow_db_started_at", None)
    if started_at is not None:
        metrics.duration_ms += max(0.0, (perf_counter() - started_at) * 1000.0)


def _metrics_checkout(_dbapi_connection, _connection_record, _connection_proxy) -> None:
    metrics = _REQUEST_DB_METRICS.get()
    if metrics is not None:
        metrics.checkout_count += 1


def install_database_request_metrics(target_engine: Engine) -> None:
    """Installér letvægts-måling én gang pr. SQLAlchemy Engine."""
    if target_engine in _INSTRUMENTED_ENGINES:
        return
    event.listen(target_engine, "before_cursor_execute", _metrics_before_cursor_execute)
    event.listen(target_engine, "after_cursor_execute", _metrics_after_cursor_execute)
    event.listen(target_engine, "checkout", _metrics_checkout)
    _INSTRUMENTED_ENGINES.add(target_engine)


def classify_database_url(url: str) -> dict[str, object]:
    """Returnér kun ikke-hemmelige topologi-egenskaber for en DB-URL."""
    parsed = make_url(_normalize_database_url(url))
    host = str(parsed.host or "").strip().lower()
    neon = host.endswith(".neon.tech")
    # Neon markerer PgBouncer endpointet med ``-pooler`` umiddelbart før regionen.
    neon_pooler = neon and "-pooler." in host
    return {
        "backend": parsed.get_backend_name(),
        "driver": parsed.get_driver_name(),
        "provider": "neon" if neon else "other",
        "server_side_pooling": bool(neon_pooler),
    }


def database_runtime_topology() -> dict[str, object]:
    """Sikker runtime-topologi til superadmin-diagnostik; ingen host/URL/secrets."""
    topology = classify_database_url(DATABASE_URL)
    topology.update({
        "pool_class": type(engine.pool).__name__,
        "application_pooling": not IS_SQLITE,
        "pool_size": None if IS_SQLITE else DB_POOL_SIZE,
        "max_overflow": None if IS_SQLITE else DB_MAX_OVERFLOW,
        "pool_timeout_seconds": None if IS_SQLITE else DB_POOL_TIMEOUT,
        "pool_recycle_seconds": None if IS_SQLITE else DB_POOL_RECYCLE,
        "pool_pre_ping": False if IS_SQLITE else True,
        "pool_use_lifo": False if IS_SQLITE else True,
    })
    return topology


install_database_request_metrics(engine)


def get_session():
    """
    FastAPI dependency.

    with Session(engine) sikrer, at DB-forbindelsen altid afleveres tilbage
    til SQLAlchemy poolen — også hvis endpointet fejler med en exception.
    """
    with Session(engine) as session:
        yield session
