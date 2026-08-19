"""Seed the VA CPG source with query-rewriter metadata.

Populates the ``rewriter_metadata`` JSONB column on the VA CPG source record
with vocabulary mappings (lay -> canonical clinical terms), domain notes, and
sample query examples. This metadata drives the query-rewriter so that
lay clinical language is translated into precise terminology before retrieval.

The script is idempotent: it UPSERTs the metadata on the existing source if
one exists, or creates a minimal source record when run before ingestion.

Usage:

    # With local Postgres running on the standard dev port:
    python scripts/seed_va_cpg_rewriter_metadata.py

    # Or with a custom catalog DB URL:
    python scripts/seed_va_cpg_rewriter_metadata.py \\
        --db-url postgresql+psycopg://user:pass@host:port/db
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import select

from retrieval_hub.db.engine import create_db_engine, make_session_factory, session_scope
from retrieval_hub.models.enums import (
    AccessVisibility,
    LlmResolution,
    SourceFamily,
    SourceStatus,
)
from retrieval_hub.models.source import Source
from retrieval_hub.schemas.rewriter import RewriterMetadata, SampleQueryExample, VocabularyMapping

logger = logging.getLogger("seed_va_cpg_rewriter_metadata")

SOURCE_SLUG = "va-cpg-clinical-guidelines"
SOURCE_NAME = "VA/DoD Clinical Practice Guidelines"

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@localhost:5434/retrievalhub"


# ---------------------------------------------------------------------------
# Vocabulary mappings -- lay term -> canonical clinical term
# ---------------------------------------------------------------------------

VOCABULARY_MAPPINGS: list[VocabularyMapping] = [
    # Diabetes / Endocrine
    VocabularyMapping(lay_term="high blood sugar", canonical_term="hyperglycemia"),
    VocabularyMapping(lay_term="low blood sugar", canonical_term="hypoglycemia"),
    VocabularyMapping(lay_term="sugar diabetes", canonical_term="type 2 diabetes mellitus"),
    VocabularyMapping(lay_term="blood sugar test", canonical_term="hemoglobin A1c measurement"),
    VocabularyMapping(lay_term="insulin resistance", canonical_term="insulin resistance syndrome"),
    VocabularyMapping(
        lay_term="high blood sugar after eating", canonical_term="postprandial hyperglycemia"
    ),
    VocabularyMapping(
        lay_term="diabetic nerve pain", canonical_term="diabetic peripheral neuropathy"
    ),
    VocabularyMapping(lay_term="diabetic eye disease", canonical_term="diabetic retinopathy"),
    VocabularyMapping(lay_term="diabetic kidney disease", canonical_term="diabetic nephropathy"),
    # Cardiovascular / Hypertension
    VocabularyMapping(lay_term="high blood pressure", canonical_term="hypertension"),
    VocabularyMapping(
        lay_term="blood pressure medicine", canonical_term="antihypertensive therapy"
    ),
    VocabularyMapping(lay_term="heart attack", canonical_term="myocardial infarction"),
    VocabularyMapping(lay_term="stroke", canonical_term="cerebrovascular accident"),
    VocabularyMapping(lay_term="hardening of the arteries", canonical_term="atherosclerosis"),
    VocabularyMapping(lay_term="blood thinner", canonical_term="anticoagulant therapy"),
    VocabularyMapping(lay_term="chest pain", canonical_term="angina pectoris"),
    VocabularyMapping(lay_term="irregular heartbeat", canonical_term="cardiac arrhythmia"),
    VocabularyMapping(lay_term="heart failure", canonical_term="congestive heart failure"),
    VocabularyMapping(lay_term="high cholesterol", canonical_term="hyperlipidemia"),
    VocabularyMapping(lay_term="cholesterol medicine", canonical_term="statin therapy"),
    # Mental Health
    VocabularyMapping(lay_term="shell shock", canonical_term="post-traumatic stress disorder"),
    VocabularyMapping(lay_term="PTSD", canonical_term="post-traumatic stress disorder"),
    VocabularyMapping(lay_term="depression", canonical_term="major depressive disorder"),
    VocabularyMapping(lay_term="anxiety", canonical_term="generalized anxiety disorder"),
    VocabularyMapping(lay_term="trouble sleeping", canonical_term="insomnia disorder"),
    VocabularyMapping(lay_term="nightmares", canonical_term="trauma-related nightmares"),
    VocabularyMapping(lay_term="suicidal thoughts", canonical_term="suicidal ideation"),
    VocabularyMapping(lay_term="mood swings", canonical_term="mood dysregulation"),
    # Pain Management
    VocabularyMapping(lay_term="chronic pain", canonical_term="chronic pain syndrome"),
    VocabularyMapping(lay_term="back pain", canonical_term="chronic low back pain"),
    VocabularyMapping(lay_term="painkiller", canonical_term="opioid analgesic"),
    VocabularyMapping(lay_term="pain medicine", canonical_term="analgesic therapy"),
    VocabularyMapping(lay_term="nerve pain", canonical_term="neuropathic pain"),
    VocabularyMapping(lay_term="joint pain", canonical_term="arthralgia"),
    # Substance Use
    VocabularyMapping(lay_term="alcoholism", canonical_term="alcohol use disorder"),
    VocabularyMapping(lay_term="drug addiction", canonical_term="substance use disorder"),
    VocabularyMapping(lay_term="drinking problem", canonical_term="alcohol use disorder"),
    VocabularyMapping(lay_term="opioid addiction", canonical_term="opioid use disorder"),
    VocabularyMapping(
        lay_term="withdrawal symptoms", canonical_term="substance withdrawal syndrome"
    ),
    VocabularyMapping(lay_term="detox", canonical_term="medically managed withdrawal"),
    # General Medical
    VocabularyMapping(lay_term="kidney disease", canonical_term="chronic kidney disease"),
    VocabularyMapping(lay_term="liver disease", canonical_term="hepatic dysfunction"),
    VocabularyMapping(
        lay_term="lung disease", canonical_term="chronic obstructive pulmonary disease"
    ),
    VocabularyMapping(lay_term="overweight", canonical_term="obesity"),
    VocabularyMapping(lay_term="BMI", canonical_term="body mass index"),
    VocabularyMapping(lay_term="screening test", canonical_term="preventive health screening"),
    VocabularyMapping(lay_term="side effects", canonical_term="adverse drug reactions"),
    VocabularyMapping(lay_term="drug interactions", canonical_term="pharmacological interactions"),
    VocabularyMapping(lay_term="follow-up visit", canonical_term="clinical follow-up assessment"),
]


# ---------------------------------------------------------------------------
# Domain notes
# ---------------------------------------------------------------------------

DOMAIN_NOTES = (
    "The VA Clinical Practice Guidelines (CPGs) are evidence-based recommendations "
    "developed by the Department of Veterans Affairs and Department of Defense for "
    "the management of specific clinical conditions common in the veteran population. "
    "Guidelines cover diagnosis, treatment algorithms, screening protocols, and "
    "follow-up care. Content is structured around clinical questions and "
    "recommendation statements with evidence grades. Queries should use standard "
    "clinical terminology and reference guideline-specific concepts (recommendation "
    "strength, evidence quality, treatment algorithms) for best retrieval results. "
    "Key clinical domains include: diabetes mellitus, hypertension, dyslipidemia, "
    "PTSD, major depressive disorder, substance use disorders, chronic pain "
    "management, and tobacco cessation."
)


# ---------------------------------------------------------------------------
# Sample queries with good rewrites
# ---------------------------------------------------------------------------

SAMPLE_QUERIES: list[SampleQueryExample] = [
    SampleQueryExample(
        raw="high blood sugar after a meal",
        good_rewrites=[
            "postprandial hyperglycemia management guidelines",
            "glycemic control recommendations following meals VA CPG",
        ],
    ),
    SampleQueryExample(
        raw="what blood pressure medicine should I take",
        good_rewrites=[
            "antihypertensive therapy selection recommendations",
            "first-line pharmacotherapy for hypertension VA clinical practice guideline",
        ],
    ),
    SampleQueryExample(
        raw="how to treat PTSD nightmares",
        good_rewrites=[
            "trauma-related nightmare treatment recommendations PTSD",
            "pharmacotherapy and psychotherapy for PTSD sleep disturbance VA CPG",
        ],
    ),
    SampleQueryExample(
        raw="can I stop taking my cholesterol medicine",
        good_rewrites=[
            "statin therapy discontinuation criteria",
            "lipid-lowering therapy de-escalation recommendations VA CPG",
        ],
    ),
    SampleQueryExample(
        raw="back pain that won't go away",
        good_rewrites=[
            "chronic low back pain management algorithm",
            "non-pharmacological and pharmacological treatment chronic low back pain VA CPG",
        ],
    ),
    SampleQueryExample(
        raw="drinking too much alcohol",
        good_rewrites=[
            "alcohol use disorder screening and brief intervention",
            "pharmacotherapy for alcohol use disorder VA CPG recommendations",
        ],
    ),
    SampleQueryExample(
        raw="feeling depressed after deployment",
        good_rewrites=[
            "major depressive disorder screening post-deployment",
            "evidence-based treatment major depressive disorder veteran population VA CPG",
        ],
    ),
    SampleQueryExample(
        raw="pain medicine alternatives to opioids",
        good_rewrites=[
            "non-opioid analgesic alternatives chronic pain",
            "multimodal pain management non-pharmacological interventions VA CPG",
        ],
    ),
]


# ---------------------------------------------------------------------------
# Build & validate the full metadata payload
# ---------------------------------------------------------------------------


def build_metadata() -> RewriterMetadata:
    """Construct and Pydantic-validate the complete RewriterMetadata payload."""
    return RewriterMetadata(
        enabled=True,
        vocabulary_mappings=VOCABULARY_MAPPINGS,
        domain_notes=DOMAIN_NOTES,
        sample_queries=SAMPLE_QUERIES,
        schema_hints=None,
        prompt_override_id=None,
        llm_resolution=LlmResolution.DEFAULT,
        default_llm=None,
        max_rewrites=5,
    )


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------


def seed_metadata(db_url: str, metadata: RewriterMetadata) -> tuple[str, bool]:
    """Write metadata to the source, creating the source row if needed.

    Returns ``(source_slug, was_created)`` where ``was_created`` is True when
    a new Source row was inserted.
    """
    engine = create_db_engine(db_url)
    factory = make_session_factory(engine)
    payload = metadata.model_dump(mode="json")

    with session_scope(factory) as session:
        source = session.execute(
            select(Source).where(Source.slug == SOURCE_SLUG)
        ).scalar_one_or_none()

        if source is not None:
            logger.info("found existing source slug=%s id=%s", source.slug, source.id)
            source.rewriter_metadata = payload
            return source.slug, False

        logger.info("source slug=%s not found; creating minimal record", SOURCE_SLUG)
        source = Source(
            slug=SOURCE_SLUG,
            name=SOURCE_NAME,
            family=SourceFamily.CLINICAL_DOCUMENT,
            status=SourceStatus.DRAFT,
            visibility=AccessVisibility.PUBLIC,
            rewriter_metadata=payload,
        )
        session.add(source)
        return source.slug, True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed VA CPG source with query-rewriter metadata.",
    )
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help=f"SQLAlchemy URL for the catalog database. Default: {DEFAULT_DB_URL}",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    # Build and validate payload (fails fast on schema violations).
    metadata = build_metadata()
    logger.info("metadata payload validated successfully")

    # Persist.
    slug, was_created = seed_metadata(args.db_url, metadata)
    action = "created" if was_created else "updated"

    # Summary.
    print()
    print("=" * 64)
    print(f"VA CPG rewriter metadata {action}")
    print("=" * 64)
    print(f"  Source slug           : {slug}")
    print(f"  Vocabulary mappings   : {len(metadata.vocabulary_mappings)}")
    print(f"  Sample queries        : {len(metadata.sample_queries)}")
    print(f"  Domain notes length   : {len(metadata.domain_notes or '')} chars")
    print(f"  Enabled               : {metadata.enabled}")
    print(f"  Max rewrites          : {metadata.max_rewrites}")
    print(f"  LLM resolution        : {metadata.llm_resolution}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
