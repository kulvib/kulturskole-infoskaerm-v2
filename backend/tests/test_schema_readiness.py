from __future__ import annotations

from contextlib import contextmanager
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, text

from service1.schema_readiness import (
    RepositorySchemaState,
    check_schema_readiness,
    load_repository_schema_state,
)


@contextmanager
def _database_with_revisions(
    revisions: tuple[str, ...] = (),
    *,
    create_version_table: bool = True,
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            if create_version_table:
                connection.execute(
                    text(
                        "CREATE TABLE alembic_version ("
                        "version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                    )
                )
                for revision in revisions:
                    connection.execute(
                        text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                        {"revision": revision},
                    )
            yield connection
    finally:
        engine.dispose()


class SchemaReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_repository_schema_state.cache_clear()
        cls.repository_state = load_repository_schema_state()
        if len(cls.repository_state.heads) != 1:
            raise AssertionError("Testbaselinen skal have præcis ét Alembic-head")
        cls.head = cls.repository_state.heads[0]
        cls.older_revision = next(
            revision
            for revision in cls.repository_state.known_revisions
            if revision != cls.head
        )

    @classmethod
    def tearDownClass(cls) -> None:
        load_repository_schema_state.cache_clear()

    def test_current_repository_head_is_ready(self) -> None:
        with _database_with_revisions((self.head,)) as connection:
            result = check_schema_readiness(
                connection,
                repository_state=self.repository_state,
            )

        self.assertTrue(result.ready)
        self.assertEqual(result.reason, "ready")
        self.assertEqual(result.repository_head_count, 1)
        self.assertEqual(result.database_head_count, 1)

    def test_missing_alembic_version_table_is_not_ready(self) -> None:
        with _database_with_revisions(create_version_table=False) as connection:
            result = check_schema_readiness(
                connection,
                repository_state=self.repository_state,
            )

        self.assertFalse(result.ready)
        self.assertEqual(result.reason, "version_table_missing")
        self.assertEqual(result.database_head_count, 0)

    def test_empty_alembic_version_table_is_not_ready(self) -> None:
        with _database_with_revisions() as connection:
            result = check_schema_readiness(
                connection,
                repository_state=self.repository_state,
            )

        self.assertFalse(result.ready)
        self.assertEqual(result.reason, "version_table_empty")
        self.assertEqual(result.database_head_count, 0)

    def test_known_older_revision_is_not_ready(self) -> None:
        with _database_with_revisions((self.older_revision,)) as connection:
            result = check_schema_readiness(
                connection,
                repository_state=self.repository_state,
            )

        self.assertFalse(result.ready)
        self.assertEqual(result.reason, "database_revision_outdated")
        self.assertEqual(result.database_head_count, 1)

    def test_unknown_revision_is_not_ready(self) -> None:
        with _database_with_revisions(("unknown_revision",)) as connection:
            result = check_schema_readiness(
                connection,
                repository_state=self.repository_state,
            )

        self.assertFalse(result.ready)
        self.assertEqual(result.reason, "database_revision_unknown")
        self.assertEqual(result.database_head_count, 1)

    def test_multiple_database_heads_are_not_ready(self) -> None:
        with _database_with_revisions((self.head, self.older_revision)) as connection:
            result = check_schema_readiness(
                connection,
                repository_state=self.repository_state,
            )

        self.assertFalse(result.ready)
        self.assertEqual(result.reason, "database_heads_multiple")
        self.assertEqual(result.database_head_count, 2)

    def test_multiple_repository_heads_are_not_ready(self) -> None:
        repository_state = RepositorySchemaState(
            heads=(self.head, "second_repository_head"),
            known_revisions=self.repository_state.known_revisions,
        )
        with _database_with_revisions((self.head,)) as connection:
            result = check_schema_readiness(
                connection,
                repository_state=repository_state,
            )

        self.assertFalse(result.ready)
        self.assertEqual(result.reason, "repository_heads_invalid")
        self.assertEqual(result.repository_head_count, 2)
        self.assertEqual(result.database_head_count, 0)

    def test_unreadable_repository_metadata_is_not_ready(self) -> None:
        with _database_with_revisions((self.head,)) as connection:
            with patch(
                "service1.schema_readiness.load_repository_schema_state",
                side_effect=RuntimeError("migration-path-must-not-leak"),
            ):
                result = check_schema_readiness(connection)

        self.assertFalse(result.ready)
        self.assertEqual(result.reason, "repository_metadata_unavailable")
        self.assertEqual(result.repository_head_count, 0)
        self.assertEqual(result.database_head_count, 0)

    def test_database_errors_propagate_to_endpoint_classifier(self) -> None:
        with _database_with_revisions((self.head,)) as connection:
            with patch(
                "service1.schema_readiness.inspect",
                side_effect=RuntimeError("database-credential-must-not-leak"),
            ):
                with self.assertRaises(RuntimeError):
                    check_schema_readiness(
                        connection,
                        repository_state=self.repository_state,
                    )


if __name__ == "__main__":
    unittest.main()
