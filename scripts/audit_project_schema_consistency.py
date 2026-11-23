#!/usr/bin/env python3
"""Read-only upstream audit with experimental changes in a temporary clone only."""
from collections import Counter, defaultdict
from pathlib import Path
import difflib
import json
import re
import sys
import xml.etree.ElementTree as ET

root = Path(sys.argv[1])
legacy = "dss2020_hydraulic_load_current"
current = "hydraulic_load_current"
project = root / "project/teksi_wastewater.qgs"
docs = root / "docs/en/tww_swmm/Import-Results.rst"
ui = root / "plugin/teksi_wastewater/processing_provider/swmm_import_results.py"
runtime = root / "plugin/teksi_wastewater/processing_provider/TwwSwmm.py"
report = {"source": str(root), "target": legacy, "findings": []}
def note(kind, **details):
    report["findings"].append({"kind": kind, **details})

# Audit all tracked source-like files, including all project files and documentation.
valid_extensions = {".py", ".sql", ".rst", ".md", ".qgs", ".qml", ".xml", ".json", ".yaml", ".yml", ".ui", ".txt", ".ini", ".cfg", ".csv", ".ili", ".toml"}
hits = []
prefixes = Counter()
files_seen = 0
for path in root.rglob("*"):
    if not path.is_file() or ".git" in path.parts or path.suffix.lower() not in valid_extensions:
        continue
    if path.stat().st_size > 30_000_000:
        continue
    files_seen += 1
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeError, OSError):
        continue
    rel = str(path.relative_to(root))
    for lineno, line in enumerate(content.splitlines(), 1):
        if legacy in line:
            hits.append({"file": rel, "line": lineno, "text": line.strip()[:180]})
        for ident in re.findall(r"\bdss2020_[A-Za-z0-9_]+\b", line):
            prefixes[ident] += 1
report["scanned_files"] = files_seen
report["legacy_references"] = hits
report["dss2020_identifiers"] = prefixes.most_common(30)
note("legacy_references", total=len(hits), files=dict(Counter(h["file"] for h in hits)))
assert len([h for h in hits if h["file"] == "project/teksi_wastewater.qgs"]) == 12, "Unexpected QGIS legacy occurrence count"
assert len([h for h in hits if h["file"] == str(ui.relative_to(root))]) == 1
assert len([h for h in hits if h["file"] == str(docs.relative_to(root))]) == 1

# Map layer-specific legacy references to actual current field configuration.
qgs = ET.parse(project)
layer_findings = []
orphans = []
for layer in qgs.findall(".//projectlayers/maplayer"):
    name = layer.findtext("layername") or "unnamed"
    layerid = layer.findtext("id") or "unknown"
    field_defs = {e.get("name") for e in layer.findall(".//fieldConfiguration/field") if e.get("name")}
    legacy_specs = []
    candidates = defaultdict(set)
    for parent in layer.iter():
        for child in parent:
            if child.tag != "field" or "name" not in child.attrib:
                continue
            n = child.get("name")
            if parent.tag in {"editable", "labelOnTop", "reuseLastValue"}:
                candidates[n].add(parent.tag)
                if n == legacy:
                    sibling = [e for e in parent if e.tag == "field" and e.get("name") == current]
                    legacy_specs.append({"parent": parent.tag, "current_sibling": bool(sibling),
                                         "legacy_attr": child.attrib,
                                         "current_sibling_attr": sibling[0].attrib if sibling else None})
    if legacy_specs:
        layer_findings.append({"layer": name, "id": layerid, "legacy": legacy_specs,
                               "has_current_field_definition": current in field_defs,
                               "has_legacy_field_definition": legacy in field_defs})
    # Potential stale settings: present in all 3 convenience settings, absent from layer's fieldConfiguration.
    if field_defs:
        for field, tags in candidates.items():
            if field not in field_defs and tags == {"editable", "labelOnTop", "reuseLastValue"}:
                orphans.append({"layer": name, "field": field, "settings": sorted(tags)})
report["layers_with_legacy"] = layer_findings
report["potential_orphan_settings"] = orphans[:150]
report["potential_orphan_total"] = len(orphans)

# Simulate changes in a throwaway clone: prefer removing stale redundant settings.
text = project.read_text()
lines = text.splitlines(keepends=True)
newlines = []
removed = 0
for line in lines:
    if legacy in line and re.search(r"<field\b[^>]*\bname=[\"']"+legacy+r"[\"']", line):
        removed += 1
        continue
    newlines.append(line)
assert removed == 12, f"Expected exactly 12 obsolete QGIS settings, found {removed}"
new_qgs = "".join(newlines)
ET.fromstring(new_qgs)
assert legacy not in new_qgs
report["candidate_qgs_removed"] = removed

def replacement(path):
    source = path.read_text()
    assert source.count(legacy) == 1
    new = source.replace(legacy, current)
    assert new.count(legacy) == 0
    return source, new
ui_old, ui_new = replacement(ui)
docs_old, docs_new = replacement(docs)
patch = []
for filename, before, after in [
    ("project/teksi_wastewater.qgs", text, new_qgs),
    (str(ui.relative_to(root)), ui_old, ui_new),
    (str(docs.relative_to(root)), docs_old, docs_new),
]:
    patch.extend(difflib.unified_diff(before.splitlines(keepends=True),
                                     after.splitlines(keepends=True),
                                     fromfile="a/"+filename, tofile="b/"+filename, n=3))
Path("candidate-cleanup.diff").write_text("".join(patch))
# Additional exact tests: all remaining references must be resolved after candidate changes.
assert not any(legacy in data for data in (new_qgs, ui_new, docs_new))
report["candidate_patch_lines"] = len(patch)
note("candidate_cleanup", qgs_removed=removed, docs_replaced=1, ui_replaced=1,
     qgs_xml_valid=True)

print("AUDIT SUMMARY")
print("Files scanned:", files_seen)
print("Legacy references:", len(hits))
print("Other dss2020-prefixed identifiers:", prefixes.most_common(20))
print("Affected layers:", json.dumps(layer_findings, ensure_ascii=False))
print("Possible unrelated QGIS stale settings count:", len(orphans))
print("Possible unrelated examples:", json.dumps(orphans[:35], ensure_ascii=False))
print("Candidate patch lines:", len(patch), "XML parse: PASS")
Path("audit-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
