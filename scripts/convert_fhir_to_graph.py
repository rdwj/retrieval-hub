#!/usr/bin/env python3
"""Convert Synthea FHIR R4 JSON bundles to graph format (nodes.tsv + edges.tsv).

Reads all FHIR transaction bundles from an input directory, extracts resources
as graph nodes and inter-resource references as edges, then writes two TSV files
suitable for graph database ingestion.
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Name rendering per resource type
# ---------------------------------------------------------------------------

def _safe_get(obj, *keys, default=None):
    """Walk nested dicts/lists safely, returning *default* on any miss."""
    cur = obj
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, list) and isinstance(k, int) and k < len(cur):
            cur = cur[k]
        else:
            return default
        if cur is None:
            return default
    return cur


def _render_patient(r):
    name_obj = _safe_get(r, "name", 0, default={})
    family = name_obj.get("family", "")
    given = " ".join(name_obj.get("given", []))
    display = f"{family}, {given}".strip(", ") if family or given else r.get("id", "")[:8]
    props = {
        "gender": r.get("gender"),
        "birthDate": r.get("birthDate"),
    }
    return display, props


def _render_condition(r):
    display = _safe_get(r, "code", "coding", 0, "display", default="Condition")
    props = {
        "clinicalStatus": _safe_get(r, "clinicalStatus", "coding", 0, "code"),
        "onsetDateTime": r.get("onsetDateTime"),
        "snomedCode": _safe_get(r, "code", "coding", 0, "code"),
    }
    return display, props


def _render_medication_request(r):
    display = _safe_get(
        r, "medicationCodeableConcept", "coding", 0, "display",
        default="MedicationRequest",
    )
    props = {
        "status": r.get("status"),
        "intent": r.get("intent"),
        "authoredOn": r.get("authoredOn"),
    }
    return display, props


def _render_observation(r):
    code_display = _safe_get(r, "code", "coding", 0, "display", default="Observation")
    vq = r.get("valueQuantity")

    # Extract component values (e.g., systolic/diastolic BP)
    components = []
    for comp in r.get("component", []):
        comp_vq = comp.get("valueQuantity")
        if comp_vq and "value" in comp_vq:
            comp_name = _safe_get(comp, "code", "coding", 0, "display", default="")
            components.append({
                "name": comp_name,
                "value": comp_vq["value"],
                "unit": comp_vq.get("unit", ""),
            })

    if vq and "value" in vq:
        display = f"{code_display} = {vq['value']} {vq.get('unit', '')}"
    else:
        vc = _safe_get(r, "valueCodeableConcept", "coding", 0, "display")
        if vc:
            display = f"{code_display} = {vc}"
        elif components:
            # No top-level value but has components — include them in display
            comp_parts = ", ".join(
                f"{c['name']} {c['value']} {c['unit']}".strip()
                for c in components
            )
            display = f"{code_display}: {comp_parts}"
        else:
            display = code_display

    props = {
        "effectiveDateTime": r.get("effectiveDateTime"),
        "category": _safe_get(r, "category", 0, "coding", 0, "display"),
    }
    if components:
        props["components"] = components
    return display, props


def _render_encounter(r):
    display = _safe_get(r, "type", 0, "coding", 0, "display", default="Encounter")
    period = r.get("period", {})
    props = {
        "status": r.get("status"),
        "periodStart": period.get("start"),
        "periodEnd": period.get("end"),
        "classCode": _safe_get(r, "class", "code"),
    }
    return display, props


def _render_procedure(r):
    display = _safe_get(r, "code", "coding", 0, "display", default="Procedure")
    performed = r.get("performedDateTime") or _safe_get(r, "performedPeriod", "start")
    props = {
        "status": r.get("status"),
        "performedDateTime": performed,
    }
    return display, props


def _render_immunization(r):
    display = _safe_get(r, "vaccineCode", "coding", 0, "display", default="Immunization")
    props = {
        "status": r.get("status"),
        "occurrenceDateTime": r.get("occurrenceDateTime"),
    }
    return display, props


def _render_careplan(r):
    # Use the second category (the SNOMED one) if present, else first
    cats = r.get("category", [])
    display = None
    for cat in cats:
        d = _safe_get(cat, "coding", 0, "display")
        if d:
            display = d
    display = display or "CarePlan"
    props = {
        "status": r.get("status"),
        "periodStart": _safe_get(r, "period", "start"),
    }
    return display, props


def _render_diagnosticreport(r):
    display = _safe_get(r, "code", "coding", 0, "display", default="DiagnosticReport")
    props = {
        "status": r.get("status"),
        "effectiveDateTime": r.get("effectiveDateTime"),
    }
    return display, props


def _render_claim(r):
    display = _safe_get(r, "type", "coding", 0, "display", default="Claim")
    props = {
        "status": r.get("status"),
        "billablePeriodStart": _safe_get(r, "billablePeriod", "start"),
        "totalValue": _safe_get(r, "total", "value"),
    }
    return display, props


def _render_default(r):
    rt = r.get("resourceType", "Resource")
    rid = r.get("id", "unknown")[:8]
    display = f"{rt} {rid}"
    props = {}
    for field in ("status", "date", "created"):
        if field in r:
            props[field] = r[field]
    return display, props


RENDERERS = {
    "Patient": _render_patient,
    "Condition": _render_condition,
    "MedicationRequest": _render_medication_request,
    "Observation": _render_observation,
    "Encounter": _render_encounter,
    "Procedure": _render_procedure,
    "Immunization": _render_immunization,
    "CarePlan": _render_careplan,
    "DiagnosticReport": _render_diagnosticreport,
    "Claim": _render_claim,
}


# ---------------------------------------------------------------------------
# Edge extraction
# ---------------------------------------------------------------------------

# Map of (resource field path) -> relationship type.
# Paths are dot-separated; a trailing "[]" means iterate the list.
KNOWN_EDGE_FIELDS = {
    "subject": "HAS_SUBJECT",
    "encounter": "PART_OF_ENCOUNTER",
    "reasonReference[]": "REASON_FOR",
    "medicationReference": "PRESCRIBES",
    "performer[]": "PERFORMED_BY",
    "requester": "REQUESTED_BY",
    "beneficiary": "BENEFICIARY_OF",
    "payor[]": "PAID_BY",
    "patient": "HAS_PATIENT",
    "claim": "CLAIM_FOR",
    "careTeam[]": "HAS_CARE_TEAM",
    "addresses[]": "ADDRESSES_CONDITION",
    "result[]": "HAS_RESULT",
    "diagnosis[].diagnosisReference": "DIAGNOSED_WITH",
    "procedure[].procedureReference": "INCLUDES_PROCEDURE",
    "item[].encounter[]": "ITEM_ENCOUNTER",
    "insurance[].coverage": "COVERED_BY",
}


def _resolve_ref(ref_value):
    """Return entity_id if the reference is internal, else None."""
    if ref_value and ref_value.startswith("urn:uuid:"):
        return ref_value[len("urn:uuid:"):]
    return None


def _extract_ref_at_path(resource, path_parts):
    """Yield (reference_value, relationship_type) for a dotted path."""
    if not path_parts:
        # We should be at a reference object
        if isinstance(resource, dict) and "reference" in resource:
            yield resource["reference"]
        return

    head, rest = path_parts[0], path_parts[1:]
    is_list = head.endswith("[]")
    key = head.rstrip("[]")

    val = resource.get(key) if isinstance(resource, dict) else None
    if val is None:
        return
    if is_list:
        if isinstance(val, list):
            for item in val:
                yield from _extract_ref_at_path(item, rest)
    else:
        yield from _extract_ref_at_path(val, rest)


def _find_generic_refs(resource, known_top_keys):
    """Find reference fields not covered by KNOWN_EDGE_FIELDS."""
    refs = []

    def _walk(obj, path_parts):
        if isinstance(obj, dict):
            if "reference" in obj:
                # Check if this path is already handled
                top_key = path_parts[0] if path_parts else ""
                if top_key not in known_top_keys:
                    refs.append(obj["reference"])
            for k, v in obj.items():
                if k in ("meta", "text", "identifier", "extension", "contained"):
                    continue
                _walk(v, path_parts + [k])
        elif isinstance(obj, list):
            for item in obj:
                _walk(item, path_parts)

    _walk(resource, [])
    return refs


def extract_edges(entity_id, resource):
    """Extract all edges from a single resource. Returns list of edge tuples."""
    edges = []
    known_top_keys = set()
    for field_path in KNOWN_EDGE_FIELDS:
        top_key = field_path.split(".")[0].rstrip("[]")
        known_top_keys.add(top_key)

    for field_path, rel_type in KNOWN_EDGE_FIELDS.items():
        parts = field_path.split(".")
        for ref_val in _extract_ref_at_path(resource, parts):
            target_id = _resolve_ref(ref_val)
            if target_id:
                edges.append((entity_id, target_id, rel_type, {}))

    # Generic references for anything not in KNOWN_EDGE_FIELDS
    for ref_val in _find_generic_refs(resource, known_top_keys):
        target_id = _resolve_ref(ref_val)
        if target_id:
            edges.append((entity_id, target_id, "REFERENCES", {}))

    return edges


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process_bundles(input_dir):
    """Read all FHIR bundles and return nodes dict and edges list."""
    nodes = {}       # entity_id -> (entity_type, name, properties)
    edges = []       # list of (source_id, target_id, rel_type, properties)
    file_count = 0

    input_path = Path(input_dir)
    json_files = sorted(input_path.glob("*.json"))
    if not json_files:
        print(f"No JSON files found in {input_dir}", file=sys.stderr)
        sys.exit(1)

    for fpath in json_files:
        with open(fpath) as f:
            bundle = json.load(f)

        if bundle.get("resourceType") != "Bundle":
            print(f"  Skipping {fpath.name}: not a Bundle", file=sys.stderr)
            continue

        file_count += 1
        for entry in bundle.get("entry", []):
            full_url = entry.get("fullUrl", "")
            resource = entry.get("resource", {})
            resource_type = resource.get("resourceType")
            if not resource_type:
                continue

            entity_id = full_url.replace("urn:uuid:", "") if full_url.startswith("urn:uuid:") else resource.get("id", "")
            if not entity_id:
                continue

            # Render node (first occurrence wins)
            if entity_id not in nodes:
                renderer = RENDERERS.get(resource_type, _render_default)
                name, props = renderer(resource)
                # Strip None values from properties
                props = {k: v for k, v in props.items() if v is not None}
                nodes[entity_id] = (resource_type, name, props)

            # Extract edges
            edges.extend(extract_edges(entity_id, resource))

    print(f"Processed {file_count} bundles from {len(json_files)} files")
    return nodes, edges


def write_tsv(nodes, edges, output_dir):
    """Write nodes.tsv and edges.tsv to output_dir."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    nodes_file = out_path / "nodes.tsv"
    edges_file = out_path / "edges.tsv"

    # Write nodes
    with open(nodes_file, "w") as f:
        f.write("entity_id\tentity_type\tname\tproperties_json\n")
        for eid in sorted(nodes):
            etype, name, props = nodes[eid]
            props_json = json.dumps(props, ensure_ascii=False)
            # Escape tabs and newlines in name and props
            safe_name = name.replace("\t", " ").replace("\n", " ")
            f.write(f"{eid}\t{etype}\t{safe_name}\t{props_json}\n")

    # Deduplicate edges
    seen_edges = set()
    unique_edges = []
    for src, tgt, rel, props in edges:
        key = (src, tgt, rel)
        if key not in seen_edges:
            seen_edges.add(key)
            unique_edges.append((src, tgt, rel, props))

    # Filter edges to only include nodes we have
    node_ids = set(nodes.keys())
    valid_edges = [(s, t, r, p) for s, t, r, p in unique_edges if s in node_ids and t in node_ids]

    with open(edges_file, "w") as f:
        f.write("source_id\ttarget_id\trelationship_type\tproperties_json\n")
        for src, tgt, rel, props in sorted(valid_edges, key=lambda e: (e[2], e[0])):
            props_json = json.dumps(props, ensure_ascii=False)
            f.write(f"{src}\t{tgt}\t{rel}\t{props_json}\n")

    return nodes_file, edges_file, len(valid_edges), len(unique_edges) - len(valid_edges)


def print_stats(nodes, edge_count, dangling_count, nodes_file, edges_file):
    """Print summary statistics."""
    node_types = Counter()
    for etype, _, _ in nodes.values():
        node_types[etype] += 1

    print(f"\n{'='*60}")
    print("FHIR-to-Graph Conversion Summary")
    print(f"{'='*60}")
    print(f"\nTotal nodes: {len(nodes)}")
    print(f"Total edges: {edge_count}")
    if dangling_count:
        print(f"Dangling edges skipped (target not in graph): {dangling_count}")

    print("\nNodes by type:")
    for ntype, count in node_types.most_common():
        print(f"  {ntype:30s} {count:6d}")

    print("\nOutput files:")
    print(f"  {nodes_file}")
    print(f"  {edges_file}")


def main():
    default_input = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "..", "retrieval-hub-data-sources", "fhir-hypertension", "sources",
    )
    default_output = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "..", "retrieval-hub-data-sources", "fhir-hypertension", "graph",
    )

    parser = argparse.ArgumentParser(
        description="Convert Synthea FHIR R4 JSON bundles to graph TSV files",
    )
    parser.add_argument(
        "--input-dir", default=default_input,
        help="Directory containing FHIR JSON bundles (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir", default=default_output,
        help="Output directory for nodes.tsv and edges.tsv (default: %(default)s)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args()

    # Resolve paths
    input_dir = os.path.realpath(args.input_dir)
    output_dir = os.path.realpath(args.output_dir)

    if not os.path.isdir(input_dir):
        print(f"Input directory not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    # Idempotency check
    nodes_path = os.path.join(output_dir, "nodes.tsv")
    edges_path = os.path.join(output_dir, "edges.tsv")
    if os.path.exists(nodes_path) and os.path.exists(edges_path) and not args.force:
        print(f"Output files already exist at {output_dir}")
        print("Use --force to overwrite")
        sys.exit(0)

    print(f"Reading FHIR bundles from: {input_dir}")
    nodes, edges = process_bundles(input_dir)

    print(f"Writing graph files to: {output_dir}")
    nodes_file, edges_file, edge_count, dangling = write_tsv(nodes, edges, output_dir)

    print_stats(nodes, edge_count, dangling, nodes_file, edges_file)


if __name__ == "__main__":
    main()
