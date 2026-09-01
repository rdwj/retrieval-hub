"""Tests for the graph chunker module.

Verifies TSV/SIF parsing, entity renderers, and the top-level
``chunk_graph_data`` function.  All tests use inline data or
``tmp_path`` fixtures -- no external file dependencies.
"""

from __future__ import annotations

import json
import textwrap

import pytest

from retrieval_hub.ingestion.chunking.graph import (
    GraphEdge,
    GraphNode,
    _strict_isa_neighbors,
    chunk_graph_data,
    parse_graph_edges,
    parse_graph_nodes,
    render_default_entity,
    render_fhir_entity,
    render_hetionet_entity,
    render_snomed_entity,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_tsv(path, content: str) -> None:
    """Write inline TSV *content* to *path*, stripping leading indent."""
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def _node_lookup(nodes: list[GraphNode]) -> dict[str, GraphNode]:
    return {n.entity_id: n for n in nodes}


# ---------------------------------------------------------------------------
# parse_graph_nodes
# ---------------------------------------------------------------------------


def test_parse_graph_nodes(tmp_path) -> None:
    tsv = tmp_path / "nodes.tsv"
    _write_tsv(
        tsv,
        """\
        entity_id\tentity_type\tname\tproperties_json
        n1\tCompound\tAspirin\t{"drugbank_id": "DB00945"}
        n2\tDisease\tMigraine\t{"doid": "6364"}
        """,
    )

    nodes = parse_graph_nodes(tsv)

    assert len(nodes) == 2
    assert nodes[0].entity_id == "n1"
    assert nodes[0].entity_type == "Compound"
    assert nodes[0].name == "Aspirin"
    assert nodes[0].properties == {"drugbank_id": "DB00945"}
    assert nodes[1].entity_id == "n2"
    assert nodes[1].entity_type == "Disease"
    assert nodes[1].name == "Migraine"
    assert nodes[1].properties == {"doid": "6364"}


@pytest.mark.parametrize(
    "props_value",
    [
        "",           # empty string
        "   ",        # whitespace only
    ],
    ids=["empty", "whitespace"],
)
def test_parse_graph_nodes_missing_properties(tmp_path, props_value) -> None:
    tsv = tmp_path / "nodes.tsv"
    tsv.write_text(
        f"entity_id\tentity_type\tname\tproperties_json\n"
        f"n1\tGene\tTP53\t{props_value}\n",
        encoding="utf-8",
    )

    nodes = parse_graph_nodes(tsv)

    assert len(nodes) == 1
    assert nodes[0].entity_id == "n1"
    assert nodes[0].name == "TP53"
    assert nodes[0].properties == {}


def test_parse_graph_nodes_bad_json(tmp_path) -> None:
    """Malformed JSON in properties_json defaults to empty dict."""
    tsv = tmp_path / "nodes.tsv"
    _write_tsv(
        tsv,
        """\
        entity_id\tentity_type\tname\tproperties_json
        n1\tGene\tTP53\t{broken json
        """,
    )

    nodes = parse_graph_nodes(tsv)

    assert len(nodes) == 1
    assert nodes[0].properties == {}


# ---------------------------------------------------------------------------
# parse_graph_edges (4-column TSV)
# ---------------------------------------------------------------------------


def test_parse_graph_edges(tmp_path) -> None:
    tsv = tmp_path / "edges.tsv"
    _write_tsv(
        tsv,
        """\
        source_id\ttarget_id\trelationship_type\tproperties_json
        n1\tn2\tCtD\t{"source": "drugbank"}
        n2\tn3\tDaG\t{}
        n3\tn4\tGpBP\t
        n4\tn1\tAeG\t{"score": 0.95}
        """,
    )

    edges = parse_graph_edges(tsv)

    assert len(edges) == 4
    assert edges[0].source_id == "n1"
    assert edges[0].target_id == "n2"
    assert edges[0].relationship_type == "CtD"
    assert edges[0].properties == {"source": "drugbank"}
    assert edges[2].properties == {}  # empty string -> empty dict
    assert edges[3].properties == {"score": 0.95}


# ---------------------------------------------------------------------------
# parse_graph_edges (3-column SIF)
# ---------------------------------------------------------------------------


def test_parse_graph_edges_sif_format(tmp_path) -> None:
    sif = tmp_path / "edges.tsv"
    _write_tsv(
        sif,
        """\
        source\tmetaedge\ttarget
        Compound::DB00945\tCtD\tDisease::DOID:6364
        Gene::1234\tGpBP\tBiological Process::GO:0006915
        Disease::DOID:6364\tDlA\tAnatomy::UBERON:0000955
        """,
    )

    edges = parse_graph_edges(sif)

    assert len(edges) == 3
    assert edges[0].source_id == "Compound::DB00945"
    assert edges[0].target_id == "Disease::DOID:6364"
    assert edges[0].relationship_type == "CtD"
    assert edges[0].properties == {}  # SIF has no properties
    assert edges[2].relationship_type == "DlA"


# ---------------------------------------------------------------------------
# render_default_entity
# ---------------------------------------------------------------------------


def test_render_default_entity() -> None:
    node = GraphNode(
        entity_id="n1",
        entity_type="Concept",
        name="Apoptosis",
        properties={"ontology": "GO", "go_id": "GO:0006915"},
    )
    neighbor = GraphNode(entity_id="n2", entity_type="Gene", name="TP53")
    edge = GraphEdge(source_id="n1", target_id="n2", relationship_type="involves")
    lookup = _node_lookup([node, neighbor])

    text = render_default_entity(node, [edge], lookup)

    assert "Concept: Apoptosis." in text
    assert "ontology=GO" in text
    assert "go_id=GO:0006915" in text
    assert "Connected to: TP53." in text


def test_render_default_entity_no_edges() -> None:
    node = GraphNode(entity_id="n1", entity_type="Thing", name="Solo")
    text = render_default_entity(node, [], _node_lookup([node]))
    assert "Thing: Solo." in text
    assert "Connected to" not in text


# ---------------------------------------------------------------------------
# render_fhir_entity
# ---------------------------------------------------------------------------


def test_render_fhir_entity_patient() -> None:
    patient = GraphNode(
        entity_id="p1",
        entity_type="Patient",
        name="Jane Doe",
        properties={"gender": "female", "birthDate": "1985-03-12"},
    )
    cond = GraphNode(entity_id="c1", entity_type="Condition", name="Hypertension")
    med = GraphNode(entity_id="m1", entity_type="MedicationRequest", name="Lisinopril")
    edges = [
        GraphEdge(source_id="p1", target_id="c1", relationship_type="HAS_CONDITION"),
        GraphEdge(source_id="p1", target_id="m1", relationship_type="HAS_MEDICATION"),
    ]
    lookup = _node_lookup([patient, cond, med])

    text = render_fhir_entity(patient, edges, lookup)

    assert "Patient: Jane Doe." in text
    assert "Gender: female." in text
    assert "Birth date: 1985-03-12." in text
    assert "Conditions: Hypertension." in text
    assert "Medications: Lisinopril." in text


def test_render_fhir_entity_condition() -> None:
    node = GraphNode(
        entity_id="c1",
        entity_type="Condition",
        name="Diabetes",
        properties={"code": "44054006", "clinicalStatus": "active", "onsetDateTime": "2020-01-15"},
    )
    text = render_fhir_entity(node, [], _node_lookup([node]))
    assert "Condition: Diabetes (SNOMED: 44054006)." in text
    assert "Status: active." in text
    assert "Onset: 2020-01-15." in text


# ---------------------------------------------------------------------------
# render_hetionet_entity
# ---------------------------------------------------------------------------


def test_render_hetionet_entity_disease() -> None:
    disease = GraphNode(entity_id="d1", entity_type="Disease", name="Asthma")
    compound = GraphNode(entity_id="c1", entity_type="Compound", name="Budesonide")
    gene = GraphNode(entity_id="g1", entity_type="Gene", name="IL13")
    anatomy = GraphNode(entity_id="a1", entity_type="Anatomy", name="Lung")
    edges = [
        GraphEdge(source_id="c1", target_id="d1", relationship_type="CtD"),
        GraphEdge(source_id="d1", target_id="g1", relationship_type="DaG"),
        GraphEdge(source_id="d1", target_id="a1", relationship_type="DlA"),
    ]
    lookup = _node_lookup([disease, compound, gene, anatomy])

    text = render_hetionet_entity(disease, edges, lookup)

    assert "Disease: Asthma." in text
    assert "Treated by: Budesonide." in text
    assert "Associated genes: IL13." in text
    assert "Affected anatomy: Lung." in text


def test_render_hetionet_entity_compound() -> None:
    compound = GraphNode(entity_id="c1", entity_type="Compound", name="Metformin")
    disease = GraphNode(entity_id="d1", entity_type="Disease", name="Diabetes")
    edges = [
        GraphEdge(source_id="c1", target_id="d1", relationship_type="CtD"),
    ]
    lookup = _node_lookup([compound, disease])

    text = render_hetionet_entity(compound, edges, lookup)

    assert "Compound: Metformin." in text
    assert "Treats: Diabetes." in text


# ---------------------------------------------------------------------------
# chunk_graph_data
# ---------------------------------------------------------------------------


def test_chunk_graph_data(tmp_path) -> None:
    _write_tsv(
        tmp_path / "nodes.tsv",
        """\
        entity_id\tentity_type\tname\tproperties_json
        n1\tCompound\tAspirin\t{"drugbank": "DB00945"}
        n2\tDisease\tMigraine\t{"doid": "6364"}
        """,
    )
    _write_tsv(
        tmp_path / "edges.tsv",
        """\
        source_id\ttarget_id\trelationship_type\tproperties_json
        n1\tn2\tCtD\t{}
        """,
    )

    chunks, nodes, edges = chunk_graph_data(
        tmp_path, source_slug="test-graph",
    )

    assert len(chunks) == 2
    assert len(nodes) == 2
    assert len(edges) == 1

    # doc_title is the entity_id (bridge key to Memgraph).
    assert chunks[0].doc_title == "n1"
    assert chunks[1].doc_title == "n2"

    # doc_section is the entity_type.
    assert chunks[0].doc_section == "Compound"
    assert chunks[1].doc_section == "Disease"

    # doc_url follows the graph:// scheme.
    assert chunks[0].doc_url == "graph://test-graph/n1"

    # chunk_index is sequential.
    assert chunks[0].chunk_index == 0
    assert chunks[1].chunk_index == 1

    # Text should mention the entity name.
    assert "Aspirin" in chunks[0].text
    assert "Migraine" in chunks[1].text

    # Token counts should be positive.
    assert all(c.token_count > 0 for c in chunks)


def test_chunk_graph_data_token_truncation(tmp_path) -> None:
    # Build a node whose rendered text will be very long (exceeds chunk_tokens).
    big_props = {f"key_{i}": f"value_{i}_{'x' * 50}" for i in range(100)}
    _write_tsv(
        tmp_path / "nodes.tsv",
        f"entity_id\tentity_type\tname\tproperties_json\n"
        f"big\tBigType\tBigEntity\t{json.dumps(big_props)}\n",
    )
    _write_tsv(
        tmp_path / "edges.tsv",
        """\
        source_id\ttarget_id\trelationship_type\tproperties_json
        """,
    )

    chunks, _, _ = chunk_graph_data(
        tmp_path, source_slug="trunc-test", chunk_tokens=32,
    )

    assert len(chunks) == 1
    # The rendered text was truncated to at most 32 tokens.
    assert chunks[0].token_count <= 32


def test_chunk_graph_data_missing_nodes_file(tmp_path) -> None:
    """chunk_graph_data raises FileNotFoundError when nodes.tsv is absent."""
    _write_tsv(
        tmp_path / "edges.tsv",
        """\
        source_id\ttarget_id\trelationship_type\tproperties_json
        """,
    )
    with pytest.raises(FileNotFoundError, match="nodes.tsv"):
        chunk_graph_data(tmp_path, source_slug="missing")


def test_chunk_graph_data_missing_edges_file(tmp_path) -> None:
    """chunk_graph_data raises FileNotFoundError when no edges file exists."""
    _write_tsv(
        tmp_path / "nodes.tsv",
        """\
        entity_id\tentity_type\tname\tproperties_json
        n1\tThing\tFoo\t{}
        """,
    )
    with pytest.raises(FileNotFoundError, match="edges"):
        chunk_graph_data(tmp_path, source_slug="missing")


def test_chunk_graph_data_unknown_renderer(tmp_path) -> None:
    """chunk_graph_data rejects an unknown renderer name."""
    _write_tsv(
        tmp_path / "nodes.tsv",
        """\
        entity_id\tentity_type\tname\tproperties_json
        n1\tThing\tFoo\t{}
        """,
    )
    _write_tsv(
        tmp_path / "edges.tsv",
        """\
        source_id\ttarget_id\trelationship_type\tproperties_json
        """,
    )
    with pytest.raises(ValueError, match="Unknown renderer"):
        chunk_graph_data(tmp_path, source_slug="bad", renderer="nonexistent")


def test_chunk_graph_data_sif_edges(tmp_path) -> None:
    """chunk_graph_data auto-detects edges.sif when edges.tsv is missing."""
    _write_tsv(
        tmp_path / "nodes.tsv",
        """\
        entity_id\tentity_type\tname\tproperties_json
        Compound::DB00945\tCompound\tAspirin\t{}
        Disease::DOID:6364\tDisease\tMigraine\t{}
        """,
    )
    _write_tsv(
        tmp_path / "edges.sif",
        """\
        source\tmetaedge\ttarget
        Compound::DB00945\tCtD\tDisease::DOID:6364
        """,
    )

    chunks, nodes, edges = chunk_graph_data(
        tmp_path, source_slug="hetio-test",
    )

    assert len(chunks) == 2
    assert len(edges) == 1
    assert edges[0].relationship_type == "CtD"


# ---------------------------------------------------------------------------
# render_snomed_entity
# ---------------------------------------------------------------------------


def test_render_snomed_entity_disorder() -> None:
    disorder = GraphNode(
        entity_id="59621000",
        entity_type="Disorder",
        name="Essential hypertension",
        properties={
            "fsn": "Essential hypertension (disorder)",
            "definition": "A disorder characterized by elevated systemic arterial blood pressure.",
            "semantic_tag": "disorder",
        },
    )
    site = GraphNode(
        entity_id="51840005",
        entity_type="Body Structure",
        name="Systemic circulatory system structure",
    )
    parent = GraphNode(
        entity_id="38341003",
        entity_type="Disorder",
        name="Hypertensive disorder",
    )
    child = GraphNode(
        entity_id="1201005",
        entity_type="Disorder",
        name="Benign essential hypertension",
    )
    edges = [
        GraphEdge(source_id="59621000", target_id="51840005", relationship_type="FINDING_SITE"),
        GraphEdge(source_id="59621000", target_id="38341003", relationship_type="IS_A"),
        GraphEdge(source_id="1201005", target_id="59621000", relationship_type="IS_A"),
    ]
    lookup = _node_lookup([disorder, site, parent, child])

    text = render_snomed_entity(disorder, edges, lookup)

    assert "Clinical disorder: Essential hypertension." in text
    assert "elevated systemic arterial blood pressure" in text
    assert "Finding site: Systemic circulatory system structure." in text
    assert "Parent concepts: Hypertensive disorder." in text
    assert "Subtypes: Benign essential hypertension." in text
    # Parent and subtype labels must not be confused
    assert "Parent concepts: Benign essential hypertension" not in text
    assert "Subtypes: Hypertensive disorder" not in text


def test_strict_isa_neighbors_direction() -> None:
    """_strict_isa_neighbors correctly separates parents from children."""
    node = GraphNode(entity_id="A", entity_type="Disorder", name="A")
    parent = GraphNode(entity_id="P", entity_type="Disorder", name="Parent")
    child = GraphNode(entity_id="C", entity_type="Disorder", name="Child")
    edges = [
        GraphEdge(source_id="A", target_id="P", relationship_type="IS_A"),
        GraphEdge(source_id="C", target_id="A", relationship_type="IS_A"),
        GraphEdge(source_id="A", target_id="X", relationship_type="FINDING_SITE"),
    ]
    lookup = _node_lookup([node, parent, child])

    parents = _strict_isa_neighbors(node, edges, lookup, direction="parents")
    children = _strict_isa_neighbors(node, edges, lookup, direction="children")

    assert parents == ["Parent"]
    assert children == ["Child"]


def test_render_snomed_entity_disorder_no_definition() -> None:
    disorder = GraphNode(
        entity_id="1201005",
        entity_type="Disorder",
        name="Benign essential hypertension",
        properties={
            "fsn": "Benign essential hypertension (disorder)",
            "definition": "",
            "semantic_tag": "disorder",
        },
    )
    text = render_snomed_entity(disorder, [], _node_lookup([disorder]))

    assert "Clinical disorder: Benign essential hypertension." in text
    assert "elevated" not in text  # no definition text leaked


def test_render_snomed_entity_body_structure() -> None:
    structure = GraphNode(
        entity_id="51840005",
        entity_type="Body Structure",
        name="Systemic circulatory system structure",
        properties={
            "fsn": "Systemic circulatory system structure (body structure)",
            "definition": "",
            "semantic_tag": "body structure",
        },
    )
    parent = GraphNode(
        entity_id="113257007",
        entity_type="Body Structure",
        name="Structure of cardiovascular system",
    )
    edges = [
        GraphEdge(source_id="51840005", target_id="113257007", relationship_type="IS_A"),
    ]
    lookup = _node_lookup([structure, parent])

    text = render_snomed_entity(structure, edges, lookup)

    assert "Anatomical structure: Systemic circulatory system structure." in text
    assert "Part of: Structure of cardiovascular system." in text


def test_render_snomed_entity_observable() -> None:
    obs = GraphNode(
        entity_id="75367002",
        entity_type="Observable Entity",
        name="Blood pressure",
        properties={
            "fsn": "Blood pressure (observable entity)",
            "definition": "The pressure of blood within the arteries.",
            "semantic_tag": "observable entity",
        },
    )
    text = render_snomed_entity(obs, [], _node_lookup([obs]))

    assert "Observable entity: Blood pressure." in text
    assert "pressure of blood within the arteries" in text


def test_render_snomed_entity_finding() -> None:
    finding = GraphNode(
        entity_id="24184005",
        entity_type="Finding",
        name="Blood pressure above reference range",
        properties={
            "fsn": "Blood pressure above reference range (finding)",
            "definition": "",
            "semantic_tag": "finding",
        },
    )
    site = GraphNode(
        entity_id="51840005",
        entity_type="Body Structure",
        name="Systemic circulatory system structure",
    )
    edges = [
        GraphEdge(source_id="24184005", target_id="51840005", relationship_type="FINDING_SITE"),
    ]
    lookup = _node_lookup([finding, site])

    text = render_snomed_entity(finding, edges, lookup)

    assert "Clinical finding: Blood pressure above reference range." in text
    assert "Finding site: Systemic circulatory system structure." in text


def test_render_snomed_entity_fallback() -> None:
    node = GraphNode(
        entity_id="12345",
        entity_type="Morphologic Abnormality",
        name="Arteriosclerosis",
        properties={
            "fsn": "Arteriosclerosis (morphologic abnormality)",
            "definition": "Thickening and hardening of arterial walls.",
            "semantic_tag": "morphologic abnormality",
        },
    )
    text = render_snomed_entity(node, [], _node_lookup([node]))

    assert "Morphologic Abnormality: Arteriosclerosis." in text
    assert "Thickening and hardening" in text


def test_chunk_graph_data_snomed_renderer(tmp_path) -> None:
    _write_tsv(
        tmp_path / "nodes.tsv",
        """\
        entity_id\tentity_type\tname\tproperties_json
        59621000\tDisorder\tEssential hypertension\t{"fsn": "Essential hypertension (disorder)", "definition": "Elevated BP.", "semantic_tag": "disorder"}
        51840005\tBody Structure\tSystemic circulatory system\t{"fsn": "Systemic circulatory system (body structure)", "definition": "", "semantic_tag": "body structure"}
        """,
    )
    _write_tsv(
        tmp_path / "edges.tsv",
        """\
        source_id\ttarget_id\trelationship_type\tproperties_json
        59621000\t51840005\tFINDING_SITE\t{}
        """,
    )

    chunks, nodes, edges = chunk_graph_data(
        tmp_path, source_slug="snomed-test", renderer="snomed",
    )

    assert len(chunks) == 2
    assert "Clinical disorder: Essential hypertension." in chunks[0].text
    assert "Elevated BP." in chunks[0].text
    assert "Finding site: Systemic circulatory system." in chunks[0].text
    assert "Anatomical structure: Systemic circulatory system." in chunks[1].text
