from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_migrations  # noqa: E402


def test_pg17_and_pg18_any_array_deparsing_compare_equal():
    pg17 = (
        "CHECK (status::text = ANY (ARRAY["
        "'queued'::character varying::text, "
        "'claimed'::character varying::text, "
        "'succeeded'::character varying::text]))"
    )
    pg18 = (
        "CHECK (status::text = ANY (ARRAY["
        "'queued'::character varying, "
        "'claimed'::character varying, "
        "'succeeded'::character varying]::text[]))"
    )

    assert run_migrations._normalise_constraint(pg17) == run_migrations._normalise_constraint(pg18)


def test_any_array_normalisation_does_not_hide_membership_drift():
    expected = (
        "CHECK (status::text = ANY (ARRAY["
        "'queued'::character varying::text, "
        "'claimed'::character varying::text]))"
    )
    changed = (
        "CHECK (status::text = ANY (ARRAY["
        "'queued'::character varying, "
        "'failed'::character varying]::text[]))"
    )

    assert run_migrations._normalise_constraint(expected) != run_migrations._normalise_constraint(changed)


def test_catalog_snapshot_excludes_postgresql_18_not_null_constraints():
    source = (SCRIPTS / "run_migrations.py").read_text(encoding="utf-8")

    assert "c.contype AS constraint_type" in source
    assert source.count('row.constraint_type != "n"') >= 3
