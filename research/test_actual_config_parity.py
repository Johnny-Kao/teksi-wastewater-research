#!/usr/bin/env python3
"""Parity test: use upstream's actual DEFAULTS_CONN_ARG and real context class."""
import ast
import os
import textwrap
from pathlib import Path
import psycopg
import unittest

DSN = os.environ["TEST_DATABASE_URL"]
P = Path(__file__).resolve().parents[1] / "upstream/plugin/teksi_wastewater/utils/database_utils.py"

def upstream():
    source = P.read_text()
    tree = ast.parse(source)
    db = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DatabaseUtils")
    klass = next(n for n in db.body if isinstance(n, ast.ClassDef) and n.name == "PsycopgConnection")
    config = next(n for n in tree.body if isinstance(n, ast.Try) and
                  any(isinstance(x, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DEFAULTS_CONN_ARG" for t in x.targets) for x in n.body))
    assignments = [x for x in config.body if isinstance(x, ast.Assign) and
                   any(isinstance(t, ast.Name) and t.id in ("PSYCOPG_VERSION", "DEFAULTS_CONN_ARG") for t in x.targets)]
    namespace = {}
    exec(compile(ast.Module(body=assignments, type_ignores=[]), str(P), "exec"), namespace)
    class DatabaseUtils:
        @staticmethod
        def get_pgconf_as_psycopg_dsn(): return DSN
    namespace.update(psycopg=psycopg, DatabaseUtils=DatabaseUtils)
    exec(compile(textwrap.dedent(ast.get_source_segment(source, klass)), str(P), "exec"), namespace)
    return namespace["PsycopgConnection"], namespace["DEFAULTS_CONN_ARG"]

class RealParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.Context, cls.config = upstream()
        with psycopg.connect(DSN, autocommit=True) as db:
            db.execute("CREATE TABLE IF NOT EXISTS parity_probe (id integer PRIMARY KEY, val text NOT NULL)")
        assert cls.config == {"autocommit": True}, cls.config

    def setUp(self):
        with psycopg.connect(DSN, autocommit=True) as db:
            db.execute("TRUNCATE parity_probe")

    def row(self):
        with psycopg.connect(DSN, autocommit=True) as db:
            return db.execute("SELECT val FROM parity_probe WHERE id=1").fetchone()

    def test_upstream_actual_config_is_autocommit(self):
        self.assertEqual(self.config, {"autocommit": True})
        with self.Context() as connection:
            self.assertTrue(connection.autocommit)

    def test_sql_success_is_committed_before_later_python_error(self):
        with self.assertRaisesRegex(RuntimeError, "failure"):
            with self.Context() as connection:
                connection.execute("INSERT INTO parity_probe VALUES (1, 'persisted before exit')")
                raise RuntimeError("failure")
        self.assertEqual(self.row(), ("persisted before exit",))

    def test_sql_statement_error_does_not_undo_prior_autocommitted_statement(self):
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with self.Context() as connection:
                connection.execute("INSERT INTO parity_probe VALUES (1, 'first succeeded')")
                connection.execute("INSERT INTO parity_probe VALUES (1, 'duplicate')")
        self.assertEqual(self.row(), ("first succeeded",))

    def test_rollback_in_exit_alone_cannot_fix_autocommit(self):
        class ChangedExit(self.Context):
            def __exit__(self, exc_type, exc_val, exc_tb):
                try:
                    if exc_type: self.connection.rollback()
                    else: self.connection.commit()
                finally: self.connection.close()
        with self.assertRaises(RuntimeError):
            with ChangedExit() as connection:
                connection.execute("INSERT INTO parity_probe VALUES (1, 'still committed')")
                raise RuntimeError("failure")
        self.assertEqual(self.row(), ("still committed",))

    def test_explicit_transaction_is_atomic_even_when_connection_autocommit_true(self):
        with self.Context() as connection:
            with self.assertRaises(RuntimeError):
                with connection.transaction():
                    connection.execute("INSERT INTO parity_probe VALUES (1, 'not committed')")
                    raise RuntimeError("failure")
        self.assertIsNone(self.row())

if __name__ == "__main__":
    unittest.main(verbosity=2)
