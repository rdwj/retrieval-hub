"""Seed the Tale of Two Cities source with semantic context.

Populates the ``semantic_context`` JSONB column on the Tale of Two Cities
source record with character entity definitions (with aliases for entity-arc
retrieval), relationship hints between characters, and a domain-context
summary.  This semantic layer drives the entity-arc refine strategy's alias
resolution and cross-reference following.

The script is idempotent: it UPSERTs the context on the existing source if
one exists, or creates a minimal source record when run before ingestion.

Usage:

    # With local Postgres running on the standard dev port:
    python scripts/seed_tale_of_two_cities_semantic_context.py

    # Or with a custom catalog DB URL:
    python scripts/seed_tale_of_two_cities_semantic_context.py \\
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
    SourceFamily,
    SourceStatus,
)
from retrieval_hub.models.source import Source
from retrieval_hub.schemas.semantic import (
    EntityDefinition,
    RefinementStrategy,
    RelationshipHint,
    SemanticContext,
)

logger = logging.getLogger("seed_tale_semantic_context")

SOURCE_SLUG = "tale-of-two-cities"
SOURCE_NAME = "A Tale of Two Cities"

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@localhost:5434/retrievalhub"


# ---------------------------------------------------------------------------
# Entity definitions
# ---------------------------------------------------------------------------

ENTITIES: list[EntityDefinition] = [
    EntityDefinition(
        name="Sydney Carton",
        entity_type="character",
        definition=(
            "A brilliant but dissolute English barrister who works as a legal "
            "jackal for C.J. Stryver. He bears a striking physical resemblance "
            "to Charles Darnay and is secretly in love with Lucie Manette. His "
            "character arc culminates in an act of supreme self-sacrifice."
        ),
        aliases=["Carton", "Sydney"],
        doc_titles=["A Tale of Two Cities"],
    ),
    EntityDefinition(
        name="Charles Darnay",
        entity_type="character",
        definition=(
            "A French aristocrat who renounces his family name (Evrémonde) "
            "and emigrates to England, where he works as a French tutor. He "
            "marries Lucie Manette and is repeatedly endangered by his "
            "aristocratic heritage during the Revolution."
        ),
        aliases=[
            "Darnay",
            "Charles",
            "Evrémonde",
            "Evremonde",
            "St. Evrémonde",
            "Charles St. Evrémonde",
        ],
        doc_titles=["A Tale of Two Cities"],
    ),
    EntityDefinition(
        name="Lucie Manette",
        entity_type="character",
        definition=(
            "The daughter of Doctor Manette, raised in England believing "
            "herself an orphan. She is the emotional center of the novel, "
            "described as a golden thread connecting the characters around "
            "her. She marries Charles Darnay."
        ),
        aliases=["Lucie", "Miss Manette", "Mrs. Darnay"],
        doc_titles=["A Tale of Two Cities"],
    ),
    EntityDefinition(
        name="Doctor Alexandre Manette",
        entity_type="character",
        definition=(
            "A physician imprisoned for 18 years in the Bastille by the "
            "Evrémonde family. After his release he reunites with his "
            "daughter Lucie but suffers recurring relapses into his prison "
            "identity as a shoemaker."
        ),
        aliases=["Doctor Manette", "the Doctor", "Dr. Manette"],
        doc_titles=["A Tale of Two Cities"],
    ),
    EntityDefinition(
        name="Madame Defarge",
        entity_type="character",
        definition=(
            "A cold and vengeful revolutionary who knits a register of those "
            "condemned to die. She is driven by a personal vendetta against "
            "the Evrémonde family, revealed late in the novel to stem from "
            "the murder of her family by the Evrémondes."
        ),
        aliases=["Defarge", "Thérèse Defarge"],
        doc_titles=["A Tale of Two Cities"],
    ),
    EntityDefinition(
        name="Monsieur Defarge",
        entity_type="character",
        definition=(
            "A wine-shop keeper in the Faubourg Saint-Antoine and former "
            "servant of Doctor Manette. He is a leader of the Revolution "
            "but retains some sympathy for the Manette family, putting him "
            "at odds with his wife's absolute vengeance."
        ),
        aliases=["Ernest Defarge"],
        doc_titles=["A Tale of Two Cities"],
    ),
    EntityDefinition(
        name="Jerry Cruncher",
        entity_type="character",
        definition=(
            "An odd-job man and messenger at Tellson's Bank who secretly "
            "works as a body snatcher (resurrection man) by night. He "
            "provides comic relief and his night work becomes plot-relevant "
            "in Book the Third."
        ),
        aliases=["Jerry", "Cruncher"],
        doc_titles=["A Tale of Two Cities"],
    ),
    EntityDefinition(
        name="Mr. Jarvis Lorry",
        entity_type="character",
        definition=(
            "An elderly bachelor and confidential clerk at Tellson's Bank "
            "who serves as a loyal friend and protector of the Manette "
            "family. He arranges Doctor Manette's return from France and "
            "later helps the family escape Paris."
        ),
        aliases=["Lorry", "Mr. Lorry", "Jarvis Lorry"],
        doc_titles=["A Tale of Two Cities"],
    ),
    EntityDefinition(
        name="Miss Pross",
        entity_type="character",
        definition=(
            "Lucie Manette's devoted English nurse and companion, fiercely "
            "protective. She confronts Madame Defarge in the novel's climax, "
            "a physical struggle that results in Madame Defarge's death."
        ),
        aliases=["Pross"],
        doc_titles=["A Tale of Two Cities"],
    ),
]


# ---------------------------------------------------------------------------
# Relationship hints
# ---------------------------------------------------------------------------

RELATIONSHIPS: list[RelationshipHint] = [
    RelationshipHint(
        source_entity="Sydney Carton",
        target_entity="Charles Darnay",
        relationship_type="doppelganger",
        description=(
            "Carton and Darnay bear a striking physical resemblance. This "
            "doubles motif drives the trial acquittal in Book the Second and "
            "enables Carton's final sacrifice in Book the Third."
        ),
        directionality="bidirectional",
    ),
    RelationshipHint(
        source_entity="Lucie Manette",
        target_entity="Charles Darnay",
        relationship_type="marriage",
        description="Lucie and Darnay marry at the end of Book the Second.",
        directionality="bidirectional",
    ),
    RelationshipHint(
        source_entity="Doctor Alexandre Manette",
        target_entity="Lucie Manette",
        relationship_type="parent_child",
        description=(
            "Doctor Manette is Lucie's father, imprisoned when she was an "
            "infant. Their reunion is the central event of Book the First."
        ),
        directionality="directed",
    ),
    RelationshipHint(
        source_entity="Charles Darnay",
        target_entity="Madame Defarge",
        relationship_type="antagonist",
        description=(
            "Madame Defarge seeks Darnay's death as an Evrémonde. Her "
            "vendetta is personal: the Evrémondes killed her family."
        ),
        directionality="bidirectional",
    ),
    RelationshipHint(
        source_entity="Sydney Carton",
        target_entity="Lucie Manette",
        relationship_type="unrequited_love",
        description=(
            "Carton loves Lucie but knows he is unworthy of her. His promise "
            "to do anything for her and those she loves motivates his final act."
        ),
        directionality="directed",
    ),
    RelationshipHint(
        source_entity="Mr. Jarvis Lorry",
        target_entity="Doctor Alexandre Manette",
        relationship_type="protector",
        description=(
            "Lorry arranges Manette's rescue from France, manages the "
            "family's affairs through Tellson's Bank, and remains their "
            "steadfast ally."
        ),
        directionality="directed",
    ),
    RelationshipHint(
        source_entity="Miss Pross",
        target_entity="Madame Defarge",
        relationship_type="antagonist",
        description=(
            "Miss Pross confronts Madame Defarge in the climax, preventing "
            "her from reaching Lucie. Their struggle results in Madame "
            "Defarge's death."
        ),
        directionality="bidirectional",
    ),
    RelationshipHint(
        source_entity="Monsieur Defarge",
        target_entity="Doctor Alexandre Manette",
        relationship_type="former_servant",
        description=(
            "Defarge was Doctor Manette's servant before the imprisonment "
            "and shelters him after his release from the Bastille."
        ),
        directionality="directed",
    ),
]


# ---------------------------------------------------------------------------
# Domain context
# ---------------------------------------------------------------------------

DOMAIN_CONTEXT = (
    "A Tale of Two Cities (1859) by Charles Dickens is structured in three "
    "books: 'Recalled to Life' (Doctor Manette's release from the Bastille), "
    "'The Golden Thread' (the Manette family's life in London and Darnay's "
    "trial), and 'The Track of a Storm' (the French Revolution and Carton's "
    "sacrifice). The narrative spans 1775-1793, moving between London and "
    "Paris. Key themes include resurrection and transformation, sacrifice, "
    "the violence of revolution, and the tension between personal loyalty "
    "and political justice."
)


# ---------------------------------------------------------------------------
# Build & validate the full context payload
# ---------------------------------------------------------------------------


def build_context() -> SemanticContext:
    """Construct and Pydantic-validate the complete SemanticContext payload."""
    return SemanticContext(
        entities=ENTITIES,
        relationships=RELATIONSHIPS,
        metrics=[],
        abbreviations={},
        domain_context=DOMAIN_CONTEXT,
        refinement_strategies=[
            RefinementStrategy(
                kind="entity_arc",
                window=20,
                enabled=True,
                max_context_tokens=4000,
                min_score=0.25,
            ),
            RefinementStrategy(
                kind="section",
                window=2,
                enabled=True,
                max_context_tokens=4000,
            ),
            RefinementStrategy(
                kind="cross_reference",
                window=5,
                enabled=True,
                max_context_tokens=4000,
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------


def seed_context(db_url: str, context: SemanticContext) -> tuple[str, bool]:
    """Write semantic context to the source, creating the source row if needed.

    Returns ``(source_slug, was_created)`` where ``was_created`` is True when
    a new Source row was inserted.
    """
    engine = create_db_engine(db_url)
    factory = make_session_factory(engine)
    payload = context.model_dump(mode="json")

    with session_scope(factory) as session:
        source = session.execute(
            select(Source).where(Source.slug == SOURCE_SLUG)
        ).scalar_one_or_none()

        if source is not None:
            logger.info("found existing source slug=%s id=%s", source.slug, source.id)
            source.semantic_context = payload
            return source.slug, False

        logger.info("source slug=%s not found; creating minimal record", SOURCE_SLUG)
        source = Source(
            slug=SOURCE_SLUG,
            name=SOURCE_NAME,
            family=SourceFamily.DOCUMENT,
            status=SourceStatus.DRAFT,
            visibility=AccessVisibility.PUBLIC,
            semantic_context=payload,
        )
        session.add(source)
        return source.slug, True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed Tale of Two Cities source with semantic context.",
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

    context = build_context()
    logger.info("semantic context payload validated successfully")

    slug, was_created = seed_context(args.db_url, context)
    action = "created" if was_created else "updated"

    print()
    print("=" * 64)
    print(f"Tale of Two Cities semantic context {action}")
    print("=" * 64)
    print(f"  Source slug           : {slug}")
    print(f"  Entities              : {len(context.entities)}")
    print(f"  Relationships         : {len(context.relationships)}")
    print(f"  Metrics               : {len(context.metrics)}")
    print(f"  Abbreviations         : {len(context.abbreviations)}")
    print(f"  Domain context length : {len(context.domain_context or '')} chars")
    print(f"  Refinement strategies : {[s.kind for s in context.refinement_strategies]}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
