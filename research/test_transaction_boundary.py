#!/usr/bin/env python3
"""Independent reproduction using the actual upstream PsycopgConnection class.

The upstream source is pinned by the accompanying GitHub Actions checkout.
This does not import QGIS, and therefore does not claim whole-plugin coverage.
"""
import ast
import os
from pathlib import Path
import textwrap
import unittest
import psycopg

UPSTREAM = Path(__file__).resolve().parents[1] / "upstream" / "plugin" / "teksi_wastewater" / "utils" / "database_utils.py"
DSN = os.environ["TEST_DATABASE_URL"]


def upstream_context_class():
    source = UPSTREAM.read_text()
    tree = ast.parse(source)
    outer = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DatabaseUtils")
    inner = next(n for n in outer.body if isinstance(n, ast.ClassDef) and n.name == "PsycopgConnection")
    snippet = textwrap.dedent(ast.get_source_segment(source, inner))
    class DatabaseUtils:
        @staticmethod
        def get_pgconf_as_psycopg_dsn():
            return DSN
    namespace = {
        "psycopg": psycopg,
        "DatabaseUtils": DatabaseUtils,
        "PSYCOPG_VERSION": 3,
        "DEFAULTS_CONN_ARG": {},
    }
    exec(compile(snippet, str(UPSTREAM), "exec"), namespace)
    return namespace["PsycopgConnection"]


class SafePolicyContext(upstream_context_class()):
    """Research candidate only; NOT a patch to the upstream project."""
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()


class TransactionBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(DSN, autocommit=True) as connection:
            connection.execute("DROP TABLE IF EXISTS research_txn_probe")
            connection.execute("CREATE TABLE research_txn_probe (id integer PRIMARY KEY, payload text NOT NULL)")

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(DSN, autocommit=True) as connection:
            connection.execute("DROP TABLE research_txn_probe")

    def setUp(self):
        with psycopg.connect(DSN, autocommit=True) as connection:
            connection.execute("TRUNCATE research_txn_probe")

    def value(self):
        with psycopg.connect(DSN) as connection:
            return connection.execute("SELECT payload FROM research_txn_probe WHERE id = 1").fetchone()

    def test_upstream_context_commits_even_after_python_exception(self):
        Context = upstream_context_class()
        with self.assertRaisesRegex(ValueError, "post-write application failure"):
            with Context() as connection:
                connection.execute("INSERT INTO research_txn_probe VALUES (1, 'unexpectedly persisted')")
                raise ValueError("post-write application failure")
        self.assertEqual(self.value(), ("unexpectedly persisted",))

    def test_research_candidate_rolls_back_python_exception(self):
        with self.assertRaisesRegex(ValueError, "post-write application failure"):
            with SafePolicyContext() as connection:
                connection.execute("INSERT INTO research_txn_probe VALUES (1, 'must not persist')")
                raise ValueError("post-write application failure")
        self.assertIsNone(self.value())

    def test_successful_transaction_commits_in_both_policies(self):
        for Context in (upstream_context_class(), SafePolicyContext):
            with psycopg.connect(DSN, autocommit=True) as connection:
                connection.execute("TRUNCATE research_txn_probe")
            with Context() as connection:
                connection.execute("INSERT INTO research_txn_probe VALUES (1, 'success')")
            self.assertEqual(self.value(), ("success",))

    def test_postgresql_sql_error_does_not_persist_before_exception(self):
        Context = upstream_context_class()
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with Context() as connection:
                connection.execute("INSERT INTO research_txn_probe VALUES (1, 'first')")
                connection.execute("INSERT INTO research_txn_probe VALUES (1, 'duplicate')")
        self.assertIsNone(self.value())


if __name__ == "__main__":
    unittest.main(verbosity=2)
