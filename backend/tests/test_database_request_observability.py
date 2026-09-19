from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session, create_engine

from service1.db import (
    begin_database_request_metrics,
    classify_database_url,
    install_database_request_metrics,
    reset_database_request_metrics,
)


def test_database_request_metrics_count_statements_selects_and_checkout() -> None:
    engine = create_engine("sqlite:///:memory:")
    install_database_request_metrics(engine)

    metrics, token = begin_database_request_metrics()
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1")).one()
            session.exec(text("SELECT 2")).one()
    finally:
        reset_database_request_metrics(token)

    assert metrics.statement_count == 2
    assert metrics.select_count == 2
    assert metrics.checkout_count == 1
    assert metrics.duration_ms >= 0.0


def test_neon_pooler_topology_is_classified_without_exposing_host_or_credentials() -> None:
    topology = classify_database_url(
        "postgresql://secret-user:secret-pass@ep-example-pooler.eu-central-1.aws.neon.tech/dbname?sslmode=require"
    )

    assert topology == {
        "backend": "postgresql",
        "driver": "psycopg2",
        "provider": "neon",
        "server_side_pooling": True,
    }
    serialized = repr(topology)
    assert "secret-user" not in serialized
    assert "secret-pass" not in serialized
    assert "ep-example" not in serialized


def test_direct_neon_endpoint_is_distinguishable_from_pooler() -> None:
    topology = classify_database_url(
        "postgresql://user:pass@ep-example.eu-central-1.aws.neon.tech/dbname"
    )
    assert topology["provider"] == "neon"
    assert topology["server_side_pooling"] is False
