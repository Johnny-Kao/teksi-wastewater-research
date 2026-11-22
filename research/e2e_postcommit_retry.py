"""Real TEKSI/PostGIS import fault after main commit and retry.

Runs inside upstream QGIS docker image with upstream plugin installed.
No production database; official test fixtures only.
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, "/usr/src/plugin")
from teksi_wastewater.interlis.interlis_importer_exporter import InterlisImporterExporter
from teksi_wastewater.utils.database_utils import DatabaseUtils, TWWIntegrityChecker

c = DatabaseUtils.databaseConfig
c.PGSERVICE = None
c.PGHOST = "db"
c.PGPORT = "5432"
c.PGDATABASE = "tww"
c.PGUSER = "postgres"
c.PGPASS = "postgres"
DATA = Path("/usr/src/plugin/tests/qgis/data")

def count():
    return DatabaseUtils.fetchone("SELECT COUNT(*) FROM tww_od.reach")[0]

def check():
    checker = TWWIntegrityChecker()
    return checker._check_subclass_counts(raise_err=True)

def import_file(name):
    InterlisImporterExporter().interlis_import(
        str(DATA / name), show_selection_dialog=False,
        logs_next_to_file=False, srid=2056)

print("A02 E2E: importing official organization dataset", flush=True)
import_file("minimal-dataset-organisation-arbon-only.xtf")
before=count()
print(f"BASELINE_REACH_COUNT={before}",flush=True)
assert before == 0

original=TWWIntegrityChecker._check_subclass_counts
calls=[0]
def inject(self,*args,**kwargs):
    calls[0]+=1
    raise RuntimeError("RESEARCH_INJECT_POST_COMMIT")
TWWIntegrityChecker._check_subclass_counts=inject
try:
    try:
        import_file("minimal-dataset-SIA405-ABWASSER.xtf")
        raise AssertionError("Fault not triggered")
    except RuntimeError as exc:
        assert "RESEARCH_INJECT_POST_COMMIT" in str(exc),str(exc)
finally:
    TWWIntegrityChecker._check_subclass_counts=original

after_failure=count()
print(f"POST_COMMIT_REACH_COUNT={after_failure}",flush=True)
assert calls[0] == 1
assert after_failure > 0, "Fault occurred before commit, unexpected"

print("A02 E2E: attempting clean reimport of same official file",flush=True)
try:
    import_file("minimal-dataset-SIA405-ABWASSER.xtf")
    retry="success"
except Exception as e:
    retry=f"failure: {type(e).__name__}: {e}"
    traceback.print_exc()

after_retry=count()
print(f"RETRY_STATUS={retry}",flush=True)
print(f"RETRY_REACH_COUNT={after_retry}",flush=True)
try:
    value=check()
    print(f"RETRY_SUBCLASS_CHECK={value}",flush=True)
except Exception as e:
    print(f"RETRY_SUBCLASS_CHECK_ERROR={e}",flush=True)

print("A02 E2E COMPLETE; do not equate injected failure with production incidence",flush=True)
