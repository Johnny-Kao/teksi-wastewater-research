#!/usr/bin/env python3
"""Read-only audit of legacy QGIS field references in TEKSI's project file."""
import collections
import pathlib
import sys
import xml.etree.ElementTree as ET

LEGACY = "dss2020_hydraulic_load_current"
CURRENT = "hydraulic_load_current"


def audit(project_path):
    data = pathlib.Path(project_path).read_bytes()
    print(f"Project: {project_path}, size={len(data)} bytes")
    print(f"Literal occurrences: {data.count(LEGACY.encode())}")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        print(f"XML parsing failed: {exc}")
        return 1

    hits = []
    tag_counts = collections.Counter()
    current_hits = []

    def walk(element, ancestry):
        path = "/".join((*ancestry, element.tag))
        for key, value in element.attrib.items():
            if LEGACY in value:
                hits.append((path, "@" + key, value[:240]))
                tag_counts[element.tag] += 1
            if CURRENT in value and LEGACY not in value:
                current_hits.append((path, "@" + key, value[:240]))
        if element.text and LEGACY in element.text:
            hits.append((path, "#text", element.text.strip()[:240]))
            tag_counts[element.tag] += 1
        if element.text and CURRENT in element.text and LEGACY not in element.text:
            current_hits.append((path, "#text", element.text.strip()[:240]))
        for child in element:
            walk(child, (*ancestry, element.tag))
    walk(root, ())

    print(f"XML references to legacy name: {len(hits)}")
    print("By XML tag:", dict(sorted(tag_counts.items())))
    for i, (path, where, value) in enumerate(hits, 1):
        print(f"{i:02d}. {path} {where}={value!r}")
    print(f"Independent references to new name: {len(current_hits)}")
    for path, where, value in current_hits[:30]:
        print(f"  current: {path} {where}={value!r}")

    print("\nInterpretation:")
    print("- A stored field reference is not proof of a runtime error.")
    print("- Field editor/alias/default/expression settings may become ineffective when the field is absent.")
    print("- Real QGIS and PostgreSQL behavior needs a project-open/integration test against a populated schema.")
    return 0 if hits else 2


if __name__ == "__main__":
    sys.exit(audit(sys.argv[1]))
