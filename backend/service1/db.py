from sqlmodel import create_engine, Session
from sqlalchemy.pool import StaticPool
import os
import sys
import warnings
from dotenv import load_dotenv

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
        "pool_size": _env_int("DB_POOL_SIZE", 5, min_value=1),
        "max_overflow": _env_int("DB_MAX_OVERFLOW", 2, min_value=0),
        "pool_timeout": _env_int("DB_POOL_TIMEOUT", 20, min_value=1),
        "pool_recycle": _env_int("DB_POOL_RECYCLE", 300, min_value=30),
        # Tjekker forbindelsen før genbrug, så døde Neon/Render connections ikke giver fejl.
        "pool_pre_ping": True,
        # LIFO genbruger varme forbindelser og lader ældre forbindelser lukke/recycles.
        "pool_use_lifo": True,
    })

engine = create_engine(DATABASE_URL, **engine_kwargs)



def get_session():
    """
    FastAPI dependency.

    with Session(engine) sikrer, at DB-forbindelsen altid afleveres tilbage
    til SQLAlchemy poolen — også hvis endpointet fejler med en exception.
    """
    with Session(engine) as session:
        yield session
