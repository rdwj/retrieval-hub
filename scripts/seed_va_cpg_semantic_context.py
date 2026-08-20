"""Seed the VA CPG source with semantic context.

Populates the ``semantic_context`` JSONB column on the VA CPG source record
with entity definitions (conditions, instruments, medications, therapies),
relationship hints between entities, clinical metric thresholds, domain
abbreviations, and a domain-context summary.  This semantic layer drives
the query-rewriter's domain understanding and lets other consumers reason
about clinical relationships.

The script is idempotent: it UPSERTs the context on the existing source if
one exists, or creates a minimal source record when run before ingestion.

Usage:

    # With local Postgres running on the standard dev port:
    python scripts/seed_va_cpg_semantic_context.py

    # Or with a custom catalog DB URL:
    python scripts/seed_va_cpg_semantic_context.py \\
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
    MetricDefinition,
    MetricThreshold,
    RefinementStrategy,
    RelationshipHint,
    SemanticContext,
)

logger = logging.getLogger("seed_va_cpg_semantic_context")

SOURCE_SLUG = "va-cpg-clinical-guidelines"
SOURCE_NAME = "VA/DoD Clinical Practice Guidelines"

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@localhost:5434/retrievalhub"


# ---------------------------------------------------------------------------
# Entity definitions
# ---------------------------------------------------------------------------

ENTITIES: list[EntityDefinition] = [
    # -- Conditions --
    EntityDefinition(
        name="PTSD",
        entity_type="condition",
        definition=(
            "Psychiatric disorder triggered by experiencing or witnessing traumatic "
            "events, characterized by intrusive memories, avoidance, negative mood "
            "changes, and hyperarousal per DSM-5-TR criteria."
        ),
        aliases=["post-traumatic stress disorder"],
        doc_titles=[
            "for the treatment of nightmares associated with PTSD",
        ],
    ),
    EntityDefinition(
        name="MDD",
        entity_type="condition",
        definition=(
            "Mood disorder characterized by persistent depressed mood or loss of "
            "interest, with functional impairment lasting at least two weeks."
        ),
        aliases=["major depressive disorder", "major depression", "clinical depression"],
        doc_titles=[
            "VA/DoD CLINICAL PRACTICE GUIDELINE FOR THE MANAGEMENT OF MAJOR DEPRESSIVE DISORDER",
        ],
    ),
    EntityDefinition(
        name="Type 2 Diabetes Mellitus",
        entity_type="condition",
        definition=(
            "Metabolic disorder characterized by insulin resistance and relative "
            "insulin deficiency, diagnosed by HbA1c >= 6.5% or fasting plasma "
            "glucose >= 126 mg/dL."
        ),
        aliases=["T2DM", "diabetes", "type 2 diabetes"],
        doc_titles=[
            "VA/DoD CLINICAL PRACTICE GUIDELINE FOR THE MANAGEMENT OF TYPE 2 DIABETES MELLITUS",
        ],
    ),
    EntityDefinition(
        name="Hypertension",
        entity_type="condition",
        definition=(
            "Sustained elevation of blood pressure above 130/90 mmHg in the "
            "primary care setting."
        ),
        aliases=["high blood pressure", "HTN"],
        doc_titles=[
            "VA/DoD CLINICAL PRACTICE GUIDELINE FOR THE DIAGNOSIS AND MANAGEMENT OF HYPERTENSION IN THE PRIMARY CARE SETTING",
        ],
    ),
    EntityDefinition(
        name="COPD",
        entity_type="condition",
        definition=(
            "Progressive inflammatory lung disease causing obstructed airflow, "
            "including emphysema and chronic bronchitis."
        ),
        aliases=["chronic obstructive pulmonary disease"],
        doc_titles=[
            "VA/DoD CLINICAL PRACTICE GUIDELINE FOR THE MANAGEMENT OF CHRONIC OBSTRUCTIVE PULMONARY DISEASE",
        ],
    ),
    EntityDefinition(
        name="Substance Use Disorder",
        entity_type="condition",
        definition=(
            "Recurrent use of alcohol or drugs causing clinically significant "
            "impairment, including health problems, disability, and failure to "
            "meet responsibilities."
        ),
        aliases=["SUD", "addiction"],
        doc_titles=[
            "VA/DoD CLINICAL PRACTICE GUIDELINE FOR THE MANAGEMENT OF SUBSTANCE USE DISORDERS",
        ],
    ),
    EntityDefinition(
        name="Alcohol Use Disorder",
        entity_type="condition",
        definition=(
            "Problematic pattern of alcohol use leading to clinically significant "
            "impairment or distress."
        ),
        aliases=["AUD"],
    ),
    EntityDefinition(
        name="Opioid Use Disorder",
        entity_type="condition",
        definition=(
            "Problematic pattern of opioid use leading to clinically significant "
            "impairment or distress."
        ),
        aliases=["OUD"],
    ),
    EntityDefinition(
        name="Chronic Low Back Pain",
        entity_type="condition",
        definition="Pain in the lumbar region persisting for 12 weeks or longer.",
        aliases=["LBP", "low back pain"],
        doc_titles=[
            "VA/DoD CLINICAL PRACTICE GUIDELINE FOR THE DIAGNOSI S AND TREATMENT OF LOW BACK PAIN",
        ],
    ),
    EntityDefinition(
        name="Mild Traumatic Brain Injury",
        entity_type="condition",
        definition=(
            "Traumatically induced physiological disruption of brain function "
            "with GCS 13-15 and loss of consciousness less than 30 minutes."
        ),
        aliases=["mTBI", "concussion"],
        doc_titles=[
            "VA/DoD CLINICAL PRACTICE GUIDELINE FOR THE MANAGEMENT AND REHABILITATION OF POST-ACUTE MILD TRAUMATIC BRAIN INJURY",
        ],
    ),
    EntityDefinition(
        name="Obesity",
        entity_type="condition",
        definition=(
            "Excess body fat accumulation, classified by BMI >= 30 kg/m2 "
            "(>= 25 for Asian Americans)."
        ),
        doc_titles=[
            "VA/DOD CLINICAL PRACTICE GUIDELINE FOR THE MANAGEMENT OF ADULT OVERWEIGHT AND OBESITY",
        ],
    ),
    EntityDefinition(
        name="Insomnia",
        entity_type="condition",
        definition=(
            "Persistent difficulty initiating or maintaining sleep despite "
            "adequate opportunity, with associated daytime impairment."
        ),
        aliases=["chronic insomnia disorder"],
        doc_titles=[
            "VA/DOD CLINICAL PRACTICE GUIDELINE FOR THE MANAGEMENT OF CHRONIC INSOMNIA DISORDER AND OBSTRUCTIVE SLEEP APNEA",
        ],
    ),
    # -- Screening instruments --
    EntityDefinition(
        name="PHQ-9",
        entity_type="screening_instrument",
        definition=(
            "9-item validated depression screening and severity measure, "
            "scores 0-27."
        ),
        aliases=["Patient Health Questionnaire"],
        attributes={
            "scoring": {
                "none": "0-4",
                "mild": "5-9",
                "moderate": "10-14",
                "moderately_severe": "15-19",
                "severe": "20-27",
            },
        },
    ),
    EntityDefinition(
        name="AUDIT-C",
        entity_type="screening_instrument",
        definition="3-item alcohol screening tool.",
        aliases=["Alcohol Use Disorders Identification Test"],
        attributes={"positive_screen": {"men": ">=4", "women": ">=3"}},
    ),
    EntityDefinition(
        name="PCL-5",
        entity_type="screening_instrument",
        definition="20-item self-report measure of PTSD symptom severity.",
        aliases=["PTSD Checklist for DSM-5"],
        attributes={"probable_ptsd_cutpoint": "31-33"},
    ),
    EntityDefinition(
        name="C-SSRS",
        entity_type="screening_instrument",
        definition=(
            "Structured interview for assessing suicidal ideation and behavior."
        ),
        aliases=["Columbia Suicide Severity Rating Scale"],
    ),
    EntityDefinition(
        name="GAD-7",
        entity_type="screening_instrument",
        definition=(
            "Validated screening tool for anxiety symptoms, scores 0-21."
        ),
        aliases=["Generalized Anxiety Disorder 7-item scale"],
    ),
    # -- Medication classes --
    EntityDefinition(
        name="SSRIs",
        entity_type="medication_class",
        definition=(
            "Antidepressant class including sertraline, paroxetine, fluoxetine; "
            "first-line for MDD and PTSD."
        ),
        aliases=["selective serotonin reuptake inhibitors", "SSRI"],
    ),
    EntityDefinition(
        name="ACE Inhibitors",
        entity_type="medication_class",
        definition=(
            "Antihypertensive class that blocks angiotensin-converting enzyme; "
            "first-line for hypertension, recommended against as monotherapy "
            "in Black patients."
        ),
        aliases=["ACEI", "ACEIs"],
    ),
    EntityDefinition(
        name="Statins",
        entity_type="medication_class",
        definition=(
            "HMG-CoA reductase inhibitors for LDL cholesterol reduction; "
            "classified by intensity (moderate: 30-50% LDL reduction, "
            "high: >50%)."
        ),
    ),
    EntityDefinition(
        name="Metformin",
        entity_type="medication_class",
        definition=(
            "Biguanide oral hypoglycemic; first-line pharmacotherapy for type 2 "
            "diabetes. Contraindicated if eGFR < 30."
        ),
    ),
    # -- Therapies --
    EntityDefinition(
        name="CPT",
        entity_type="therapy",
        definition=(
            "Structured PTSD psychotherapy addressing maladaptive beliefs about "
            "trauma; VA/DoD strongly recommended."
        ),
        aliases=["Cognitive Processing Therapy"],
    ),
    EntityDefinition(
        name="PE",
        entity_type="therapy",
        definition=(
            "PTSD psychotherapy involving repeated, detailed imagining and "
            "in-vivo exposure to trauma-related stimuli; VA/DoD strongly "
            "recommended."
        ),
        aliases=["Prolonged Exposure"],
    ),
    EntityDefinition(
        name="CBT",
        entity_type="therapy",
        definition=(
            "Structured psychotherapy addressing dysfunctional thoughts and "
            "behaviors; recommended for MDD, insomnia, chronic pain, and "
            "substance use disorders."
        ),
        aliases=["Cognitive Behavioral Therapy"],
    ),
    EntityDefinition(
        name="EMDR",
        entity_type="therapy",
        definition=(
            "PTSD psychotherapy using bilateral stimulation during trauma "
            "memory processing; VA/DoD strongly recommended."
        ),
        aliases=["Eye Movement Desensitization and Reprocessing"],
    ),
]


# ---------------------------------------------------------------------------
# Relationship hints
# ---------------------------------------------------------------------------

RELATIONSHIPS: list[RelationshipHint] = [
    # Comorbidities (bidirectional)
    RelationshipHint(
        source_entity="PTSD",
        target_entity="Substance Use Disorder",
        relationship_type="comorbidity",
        directionality="bidirectional",
        description="High co-occurrence; concurrent treatment recommended.",
    ),
    RelationshipHint(
        source_entity="PTSD",
        target_entity="MDD",
        relationship_type="comorbidity",
        directionality="bidirectional",
        description="Frequently co-occurring conditions.",
    ),
    RelationshipHint(
        source_entity="Type 2 Diabetes Mellitus",
        target_entity="Hypertension",
        relationship_type="comorbidity",
        directionality="bidirectional",
        description="Often co-managed; shared cardiovascular risk.",
    ),
    RelationshipHint(
        source_entity="Type 2 Diabetes Mellitus",
        target_entity="Obesity",
        relationship_type="comorbidity",
        directionality="bidirectional",
        description="Obesity is a primary risk factor for T2DM.",
    ),
    RelationshipHint(
        source_entity="Type 2 Diabetes Mellitus",
        target_entity="CKD",
        relationship_type="comorbidity",
        directionality="bidirectional",
        description="Diabetes is the leading cause of CKD.",
    ),
    # Risk factors (directed)
    RelationshipHint(
        source_entity="Hypertension",
        target_entity="Stroke",
        relationship_type="risk_factor",
        directionality="directed",
        description="Uncontrolled hypertension significantly increases stroke risk.",
    ),
    RelationshipHint(
        source_entity="Hypertension",
        target_entity="CKD",
        relationship_type="risk_factor",
        directionality="directed",
        description="Sustained hypertension damages renal vasculature.",
    ),
    # Screens-for (directed)
    RelationshipHint(
        source_entity="PHQ-9",
        target_entity="MDD",
        relationship_type="screens_for",
        directionality="directed",
        description="Primary screening and severity monitoring instrument for MDD.",
    ),
    RelationshipHint(
        source_entity="AUDIT-C",
        target_entity="Alcohol Use Disorder",
        relationship_type="screens_for",
        directionality="directed",
        description="Brief alcohol screening tool recommended in primary care.",
    ),
    RelationshipHint(
        source_entity="PCL-5",
        target_entity="PTSD",
        relationship_type="screens_for",
        directionality="directed",
        description="Self-report measure for PTSD symptom monitoring.",
    ),
    # Treats (directed)
    RelationshipHint(
        source_entity="SSRIs",
        target_entity="MDD",
        relationship_type="treats",
        directionality="directed",
        description="First-line pharmacotherapy for major depressive disorder.",
    ),
    RelationshipHint(
        source_entity="SSRIs",
        target_entity="PTSD",
        relationship_type="treats",
        directionality="directed",
        description=(
            "Sertraline and paroxetine are first-line pharmacotherapy for PTSD."
        ),
    ),
    # Contraindications (directed)
    RelationshipHint(
        source_entity="Benzodiazepines",
        target_entity="PTSD",
        relationship_type="contraindication",
        directionality="directed",
        description=(
            "VA/DoD recommends against benzodiazepines for PTSD treatment."
        ),
    ),
    RelationshipHint(
        source_entity="ACE Inhibitors",
        target_entity="Hypertension (Black patients)",
        relationship_type="contraindication",
        directionality="directed",
        description=(
            "Recommend against ACEI/ARB monotherapy in Black patients with "
            "hypertension."
        ),
    ),
    RelationshipHint(
        source_entity="Benzodiazepines",
        target_entity="Opioid therapy",
        relationship_type="contraindication",
        directionality="directed",
        description=(
            "Concurrent use of benzodiazepines and opioids is recommended "
            "against."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Metric definitions with thresholds
# ---------------------------------------------------------------------------

METRICS: list[MetricDefinition] = [
    MetricDefinition(
        name="Blood pressure target",
        metric_type="clinical_threshold",
        definition="Blood pressure management goals by population.",
        unit="mmHg",
        thresholds=[
            MetricThreshold(label="general goal", value="<130/90"),
            MetricThreshold(
                label="age 60+ goal", value="<150 SBP", context="systolic only"
            ),
            MetricThreshold(
                label="age 60+ with T2DM", value="<140 SBP",
                context="tighter target for diabetic patients",
            ),
            MetricThreshold(label="diagnostic threshold", value=">=130/90"),
        ],
    ),
    MetricDefinition(
        name="HbA1c target",
        metric_type="clinical_threshold",
        definition="Glycated hemoglobin targets for diabetes management.",
        unit="%",
        thresholds=[
            MetricThreshold(label="general", value="7.0-8.5"),
            MetricThreshold(label="no comorbidity", value="6.0-7.0"),
            MetricThreshold(
                label="marked comorbidity", value="<8.0-9.0",
                context="less aggressive target when comorbidity burden is high",
            ),
            MetricThreshold(label="prediabetes", value="5.7-6.4"),
            MetricThreshold(label="diagnostic", value=">=6.5"),
        ],
    ),
    MetricDefinition(
        name="PHQ-9 severity",
        metric_type="scoring_cutpoint",
        definition="Depression severity scoring bands and treatment response.",
        unit="score",
        thresholds=[
            MetricThreshold(label="none/minimal", value="0-4"),
            MetricThreshold(label="mild", value="5-9"),
            MetricThreshold(label="moderate", value="10-14"),
            MetricThreshold(label="moderately severe", value="15-19"),
            MetricThreshold(label="severe", value="20-27"),
            MetricThreshold(
                label="response", value=">=50% improvement",
                context="clinically meaningful treatment response",
            ),
            MetricThreshold(label="remission", value="<=4"),
        ],
    ),
    MetricDefinition(
        name="eGFR staging",
        metric_type="staging",
        definition="CKD staging by estimated glomerular filtration rate.",
        unit="mL/min/1.73m2",
        thresholds=[
            MetricThreshold(label="G1", value=">=90"),
            MetricThreshold(label="G2", value="60-89"),
            MetricThreshold(label="G3a", value="45-59"),
            MetricThreshold(label="G3b", value="30-44"),
            MetricThreshold(label="G4", value="15-29"),
            MetricThreshold(label="G5", value="<15"),
        ],
    ),
    MetricDefinition(
        name="BMI classification",
        metric_type="clinical_threshold",
        definition="Body mass index classification.",
        unit="kg/m2",
        thresholds=[
            MetricThreshold(label="underweight", value="<18.5"),
            MetricThreshold(label="normal", value="18.5-24.9"),
            MetricThreshold(label="overweight", value="25-29.9"),
            MetricThreshold(label="obese class I", value="30-34.9"),
            MetricThreshold(label="obese class II", value="35-39.9"),
            MetricThreshold(label="obese class III", value=">=40"),
        ],
    ),
    MetricDefinition(
        name="LDL-C targets",
        metric_type="clinical_threshold",
        definition="LDL cholesterol targets for cardiovascular risk management.",
        unit="mg/dL",
        thresholds=[
            MetricThreshold(label="desirable", value="<100"),
            MetricThreshold(label="high-risk goal", value="<70"),
            MetricThreshold(
                label="primary prevention statin indicated", value=">=190",
            ),
            MetricThreshold(label="borderline", value="130-159"),
        ],
    ),
    MetricDefinition(
        name="AUDIT-C positive screen",
        metric_type="scoring_cutpoint",
        definition="Alcohol screening cutpoints by sex.",
        unit="score",
        thresholds=[
            MetricThreshold(label="positive men", value=">=4"),
            MetricThreshold(label="positive women", value=">=3"),
        ],
    ),
    MetricDefinition(
        name="PCL-5 PTSD cutpoint",
        metric_type="scoring_cutpoint",
        definition="PTSD symptom severity cutpoints.",
        unit="score",
        thresholds=[
            MetricThreshold(label="probable PTSD", value="31-33"),
            MetricThreshold(label="subthreshold", value="25-30"),
        ],
    ),
    MetricDefinition(
        name="Statin intensity",
        metric_type="classification",
        definition="Statin therapy intensity by LDL reduction achieved.",
        thresholds=[
            MetricThreshold(
                label="moderate intensity", value="30-50% LDL reduction",
            ),
            MetricThreshold(
                label="high intensity", value=">50% LDL reduction",
            ),
        ],
    ),
    MetricDefinition(
        name="Weight loss goal",
        metric_type="clinical_threshold",
        definition="Clinically meaningful weight loss targets.",
        unit="% body weight",
        thresholds=[
            MetricThreshold(label="minimum meaningful", value=">=3%"),
            MetricThreshold(
                label="target for prediabetes benefit", value=">=5-7%",
            ),
        ],
    ),
    MetricDefinition(
        name="Aerobic exercise for hypertension",
        metric_type="clinical_threshold",
        definition="Minimum aerobic exercise for blood pressure reduction.",
        unit="minutes/week",
        thresholds=[
            MetricThreshold(label="recommended minimum", value="120"),
        ],
    ),
    MetricDefinition(
        name="PTSD treatment response timeframe",
        metric_type="clinical_threshold",
        definition="Expected timeframes for PTSD treatment response.",
        unit="weeks",
        thresholds=[
            MetricThreshold(label="psychotherapy", value="8-12 sessions"),
            MetricThreshold(label="pharmacotherapy trial", value="8-12 weeks"),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Abbreviations
# ---------------------------------------------------------------------------

ABBREVIATIONS: dict[str, str] = {
    "ACEI": "angiotensin-converting enzyme inhibitor",
    "ARB": "angiotensin II receptor blocker",
    "AUD": "alcohol use disorder",
    "AUDIT-C": "Alcohol Use Disorders Identification Test - Consumption",
    "BMI": "body mass index",
    "BP": "blood pressure",
    "CBT": "cognitive behavioral therapy",
    "CKD": "chronic kidney disease",
    "COPD": "chronic obstructive pulmonary disease",
    "CPG": "clinical practice guideline",
    "CPT": "cognitive processing therapy",
    "C-SSRS": "Columbia Suicide Severity Rating Scale",
    "CVD": "cardiovascular disease",
    "DBP": "diastolic blood pressure",
    "DSM-5": "Diagnostic and Statistical Manual of Mental Disorders, Fifth Edition",
    "eGFR": "estimated glomerular filtration rate",
    "EMDR": "eye movement desensitization and reprocessing",
    "FPG": "fasting plasma glucose",
    "GAD-7": "Generalized Anxiety Disorder 7-item scale",
    "GLP-1 RA": "glucagon-like peptide-1 receptor agonist",
    "HbA1c": "glycated hemoglobin",
    "HDL-C": "high-density lipoprotein cholesterol",
    "LDL-C": "low-density lipoprotein cholesterol",
    "MDD": "major depressive disorder",
    "mTBI": "mild traumatic brain injury",
    "OUD": "opioid use disorder",
    "PCL-5": "PTSD Checklist for DSM-5",
    "PE": "prolonged exposure therapy",
    "PHQ-9": "Patient Health Questionnaire-9",
    "PTSD": "post-traumatic stress disorder",
    "SBP": "systolic blood pressure",
    "SGLT-2": "sodium-glucose cotransporter-2 inhibitor",
    "SNRI": "serotonin-norepinephrine reuptake inhibitor",
    "SSRI": "selective serotonin reuptake inhibitor",
    "SUD": "substance use disorder",
    "T2DM": "type 2 diabetes mellitus",
    "TBI": "traumatic brain injury",
    "VA": "Department of Veterans Affairs",
    "DoD": "Department of Defense",
}


# ---------------------------------------------------------------------------
# Domain context
# ---------------------------------------------------------------------------

DOMAIN_CONTEXT = (
    "VA/DoD Clinical Practice Guidelines are evidence-based recommendations "
    "jointly developed by the Department of Veterans Affairs and Department of "
    "Defense. Each guideline follows a structured format with screening and "
    "diagnosis algorithms, treatment recommendations graded by evidence "
    "strength (Strong for, Weak for, Neither, Weak against, Strong against), "
    "and pharmacotherapy tables. The corpus covers chronic disease management, "
    "mental health, pain management, rehabilitation, and women's health."
)


# ---------------------------------------------------------------------------
# Build & validate the full context payload
# ---------------------------------------------------------------------------


def build_context() -> SemanticContext:
    """Construct and Pydantic-validate the complete SemanticContext payload."""
    return SemanticContext(
        entities=ENTITIES,
        relationships=RELATIONSHIPS,
        metrics=METRICS,
        abbreviations=ABBREVIATIONS,
        domain_context=DOMAIN_CONTEXT,
        refinement_strategies=[
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
            family=SourceFamily.CLINICAL_DOCUMENT,
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
        description="Seed VA CPG source with semantic context.",
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
    context = build_context()
    logger.info("semantic context payload validated successfully")

    # Persist.
    slug, was_created = seed_context(args.db_url, context)
    action = "created" if was_created else "updated"

    # Summary.
    print()
    print("=" * 64)
    print(f"VA CPG semantic context {action}")
    print("=" * 64)
    print(f"  Source slug           : {slug}")
    print(f"  Entities              : {len(context.entities)}")
    print(f"  Relationships         : {len(context.relationships)}")
    print(f"  Metrics               : {len(context.metrics)}")
    print(f"  Abbreviations         : {len(context.abbreviations)}")
    print(f"  Domain context length : {len(context.domain_context or '')} chars")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
