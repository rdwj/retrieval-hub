"""Register synthetic data sources for Phase 6 scale experiments.

Phase 4 tested agent source selection at 3 sources. Phase 6 tests at
larger scales (10, 20, 50 sources). This script registers synthetic
sources that appear in list_sources with realistic descriptions but
have no physical index (no pgvector table, no embeddings).

The eval harness measures which sources the agent SELECTS (attempts to
query), not retrieval quality, so these sources need realistic metadata
only.

Usage:

    # Register 10 synthetic sources (default)
    python scripts/register_synthetic_sources.py --count 10

    # Register 50 for a full-scale experiment
    python scripts/register_synthetic_sources.py --count 50

    # List currently registered synthetic sources
    python scripts/register_synthetic_sources.py --list

    # Remove all synthetic sources after an experiment
    python scripts/register_synthetic_sources.py --teardown
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from retrieval_hub.db import create_db_engine, make_session_factory, session_scope
from retrieval_hub.models import Source
from retrieval_hub.models.enums import SourceFamily, SourceStatus

DEFAULT_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
)

SYNTHETIC_PREFIX = "synthetic-"

# ---------------------------------------------------------------------------
# Synthetic source pool (50+ entries)
#
# Each entry: (slug_suffix, name, description_short)
#
# Descriptions follow the Phase 4 pattern:
#   "[count] [document type] from [organization] covering [topic], [topic],
#    and [topic]."
#
# The first three entries are deliberate "confusers" that overlap with real
# sources (VA CPG, PubMed hypertension, aircraft maintenance) to test agent
# discrimination.
# ---------------------------------------------------------------------------

SYNTHETIC_SOURCES: list[tuple[str, str, str]] = [
    # --- Confusers (overlap with real sources) ---
    (
        "who-clinical-guidelines",
        "WHO Clinical Practice Guidelines Collection",
        "87 clinical practice guidelines from the World Health Organization "
        "covering chronic disease management, infectious disease, and "
        "preventive care.",
    ),
    (
        "cardiology-research",
        "Cardiology and Vascular Research Papers",
        "2,400 peer-reviewed research papers from major cardiology journals "
        "covering hypertension treatment, cardiovascular risk factors, and "
        "antihypertensive pharmacology.",
    ),
    (
        "general-aviation-maintenance",
        "General Aviation Maintenance Directives",
        "1,800 airworthiness directives and service bulletins from the FAA "
        "covering general aviation maintenance procedures, inspection "
        "intervals, and parts replacement.",
    ),
    # --- Legal ---
    (
        "contract-templates",
        "Enterprise Contract Template Library",
        "340 contract templates from a Fortune 500 legal department covering "
        "vendor agreements, NDAs, and service-level commitments.",
    ),
    (
        "case-law-employment",
        "Federal Employment Case Law Digest",
        "5,200 federal court opinions covering workplace discrimination, "
        "wrongful termination, and wage-and-hour disputes.",
    ),
    (
        "regulatory-compliance-banking",
        "Banking Regulatory Compliance Manual",
        "128 regulatory guidance documents from the OCC and FDIC covering "
        "anti-money laundering, consumer protection, and capital adequacy.",
    ),
    # --- Financial ---
    (
        "sec-filings",
        "SEC 10-K and 10-Q Filings Archive",
        "12,000 annual and quarterly filings from S&P 500 companies covering "
        "financial statements, risk factors, and management discussion.",
    ),
    (
        "earnings-call-transcripts",
        "Quarterly Earnings Call Transcripts",
        "8,500 earnings call transcripts from publicly traded companies "
        "covering revenue guidance, market outlook, and analyst Q&A.",
    ),
    (
        "credit-risk-assessments",
        "Commercial Credit Risk Assessment Reports",
        "960 credit risk assessments from a major rating agency covering "
        "corporate bond ratings, default probability, and recovery analysis.",
    ),
    # --- Engineering ---
    (
        "iso-safety-standards",
        "ISO Machinery Safety Standards Collection",
        "74 ISO safety standards covering machine guarding, electrical "
        "safety, and risk assessment methodology.",
    ),
    (
        "structural-test-reports",
        "Bridge and Tunnel Structural Test Reports",
        "2,100 structural integrity test reports from state DOTs covering "
        "load capacity, corrosion assessment, and seismic resilience.",
    ),
    (
        "semiconductor-design-specs",
        "Semiconductor Process Design Specifications",
        "450 process design specifications from a chip foundry covering "
        "lithography parameters, yield optimization, and defect analysis.",
    ),
    # --- Environmental ---
    (
        "eia-assessments",
        "Environmental Impact Assessment Archive",
        "680 environmental impact assessments from federal agencies covering "
        "wetland protection, endangered species, and air quality modeling.",
    ),
    (
        "water-quality-monitoring",
        "Municipal Water Quality Monitoring Reports",
        "3,200 water quality reports from metropolitan utilities covering "
        "contaminant levels, treatment efficacy, and EPA compliance.",
    ),
    (
        "epa-enforcement-actions",
        "EPA Enforcement Actions Database",
        "1,900 enforcement action records from the EPA covering Clean Air "
        "Act violations, Superfund sites, and consent decree terms.",
    ),
    # --- HR / Policy ---
    (
        "employee-handbook",
        "Multi-State Employee Handbook Collection",
        "52 employee handbooks from a national employer covering PTO "
        "policies, remote work guidelines, and workplace conduct.",
    ),
    (
        "benefits-plan-documents",
        "Group Benefits Plan Documents",
        "180 benefits plan documents from a large HR provider covering "
        "health insurance, retirement plans, and disability coverage.",
    ),
    (
        "dei-training-materials",
        "Diversity and Inclusion Training Curriculum",
        "95 training modules from an HR consultancy covering unconscious "
        "bias, inclusive leadership, and accessibility compliance.",
    ),
    # --- IT / Security ---
    (
        "cve-vulnerability-reports",
        "CVE Vulnerability Analysis Reports",
        "6,800 vulnerability analysis reports from a CERT team covering "
        "exploitation techniques, patch guidance, and CVSS scoring.",
    ),
    (
        "incident-response-logs",
        "Security Incident Response Logs",
        "1,400 incident response records from a SOC team covering "
        "ransomware events, phishing campaigns, and insider threats.",
    ),
    (
        "infosec-policies",
        "Enterprise Information Security Policies",
        "65 security policy documents from a CISO office covering access "
        "control, data classification, and encryption standards.",
    ),
    # --- Research ---
    (
        "materials-science-papers",
        "Advanced Materials Science Research Papers",
        "3,100 peer-reviewed papers from ACS and Nature journals covering "
        "polymer composites, nanomaterials, and metal alloy properties.",
    ),
    (
        "nsf-grant-proposals",
        "NSF Grant Proposal Archive",
        "720 funded grant proposals from NSF CISE covering machine learning "
        "methods, human-computer interaction, and distributed systems.",
    ),
    (
        "lab-notebook-chemistry",
        "Organic Chemistry Lab Notebooks",
        "2,600 digitized lab notebook entries from a pharmaceutical R&D "
        "group covering synthesis routes, yield data, and spectral analysis.",
    ),
    # --- Supply Chain ---
    (
        "supplier-audit-reports",
        "Tier-1 Supplier Audit Reports",
        "840 supplier audit reports from an automotive OEM covering quality "
        "management systems, environmental compliance, and labor practices.",
    ),
    (
        "procurement-specifications",
        "Military Procurement Specifications",
        "1,500 procurement specifications from the Defense Logistics Agency "
        "covering material requirements, testing protocols, and packaging.",
    ),
    (
        "logistics-optimization",
        "Global Logistics Optimization Studies",
        "210 logistics studies from a freight company covering route "
        "optimization, warehouse layout, and last-mile delivery costs.",
    ),
    # --- Customer Support ---
    (
        "product-faqs",
        "Consumer Electronics Product FAQs",
        "4,200 FAQ entries from a consumer electronics manufacturer covering "
        "device setup, connectivity troubleshooting, and warranty claims.",
    ),
    (
        "troubleshooting-guides",
        "Industrial Equipment Troubleshooting Guides",
        "560 troubleshooting guides from a machinery vendor covering "
        "hydraulic failures, electrical faults, and calibration procedures.",
    ),
    (
        "product-manuals",
        "Medical Device Product Manuals",
        "320 product manuals from a medical device company covering "
        "installation, operation, and maintenance of diagnostic equipment.",
    ),
    # --- Manufacturing ---
    (
        "quality-control-records",
        "Pharmaceutical Quality Control Records",
        "7,500 batch quality control records from a GMP facility covering "
        "dissolution testing, impurity analysis, and sterility assurance.",
    ),
    (
        "process-specifications",
        "Automotive Assembly Process Specifications",
        "430 process specifications from an assembly plant covering weld "
        "parameters, paint application, and torque specifications.",
    ),
    (
        "equipment-maintenance-manuals",
        "CNC Equipment Maintenance Manuals",
        "180 maintenance manuals from CNC machine manufacturers covering "
        "preventive maintenance schedules, spindle service, and coolant "
        "management.",
    ),
    # --- Real Estate ---
    (
        "property-assessments",
        "Commercial Property Assessment Reports",
        "2,800 property assessment reports from county assessors covering "
        "market valuation, structural condition, and zoning compliance.",
    ),
    (
        "lease-agreements",
        "Commercial Lease Agreement Archive",
        "1,100 commercial lease agreements from a REIT covering rent "
        "escalation clauses, tenant improvement allowances, and CAM charges.",
    ),
    (
        "zoning-ordinances",
        "Municipal Zoning Ordinance Database",
        "380 zoning ordinance documents from mid-size US cities covering "
        "land use classifications, setback requirements, and variance "
        "procedures.",
    ),
    # --- Education ---
    (
        "stem-curricula",
        "K-12 STEM Curriculum Frameworks",
        "210 curriculum framework documents from state education departments "
        "covering math standards, science progression, and CS integration.",
    ),
    (
        "accreditation-reports",
        "Higher Education Accreditation Reports",
        "640 accreditation self-study reports from regional accreditors "
        "covering institutional effectiveness, student outcomes, and "
        "financial viability.",
    ),
    (
        "student-outcomes-data",
        "Community College Student Outcomes Data",
        "1,500 outcomes reports from community colleges covering completion "
        "rates, transfer success, and workforce placement.",
    ),
    # --- Healthcare (non-clinical, distinct from VA CPG) ---
    (
        "hospital-quality-metrics",
        "Hospital Quality and Safety Metrics Reports",
        "3,400 quality reports from CMS Hospital Compare covering "
        "readmission rates, patient satisfaction, and infection benchmarks.",
    ),
    (
        "jcaho-accreditation",
        "Joint Commission Accreditation Standards",
        "92 accreditation standards from the Joint Commission covering "
        "patient rights, medication management, and infection prevention.",
    ),
    (
        "patient-safety-incidents",
        "Patient Safety Event Reports",
        "5,600 de-identified patient safety event reports from a hospital "
        "system covering medication errors, falls, and surgical "
        "complications.",
    ),
    # --- Transportation ---
    (
        "fleet-maintenance-records",
        "Municipal Transit Fleet Maintenance Records",
        "9,200 maintenance records from a metro transit authority covering "
        "engine overhaul intervals, brake system inspections, and fleet "
        "lifecycle planning.",
    ),
    (
        "route-optimization-studies",
        "Freight Route Optimization Analyses",
        "310 route optimization analyses from a trucking company covering "
        "fuel efficiency modeling, driver scheduling, and toll-cost "
        "minimization.",
    ),
    (
        "dot-safety-inspections",
        "DOT Commercial Vehicle Safety Inspections",
        "4,800 commercial vehicle inspection reports from state DOT offices "
        "covering brake compliance, hours-of-service violations, and "
        "hazmat transport.",
    ),
    # --- Energy ---
    (
        "grid-operations-reports",
        "Regional Grid Operations Reports",
        "1,200 grid operations reports from an ISO covering load forecasting, "
        "congestion pricing, and frequency regulation.",
    ),
    (
        "renewable-energy-assessments",
        "Wind and Solar Resource Assessments",
        "460 renewable resource assessments from NREL covering wind speed "
        "profiles, solar irradiance maps, and capacity factor projections.",
    ),
    (
        "ferc-regulatory-filings",
        "FERC Regulatory Filings Archive",
        "2,300 regulatory filings from FERC covering rate cases, pipeline "
        "certifications, and market manipulation investigations.",
    ),
    # --- Additional domains for variety ---
    (
        "insurance-claims",
        "Commercial Insurance Claims Database",
        "8,900 commercial insurance claims from a specialty carrier covering "
        "property damage assessments, liability determinations, and "
        "subrogation outcomes.",
    ),
    (
        "patent-filings",
        "US Patent Application Filings",
        "15,000 patent applications from the USPTO covering biotechnology "
        "inventions, software patents, and mechanical engineering "
        "innovations.",
    ),
    (
        "food-safety-inspections",
        "FDA Food Safety Inspection Reports",
        "3,700 food safety inspection reports from the FDA covering HACCP "
        "compliance, facility sanitation, and corrective action records.",
    ),
    (
        "disaster-response-plans",
        "State Emergency Management Plans",
        "150 disaster response plans from state emergency agencies covering "
        "hurricane evacuation, wildfire response, and pandemic preparedness.",
    ),
    (
        "trade-compliance-docs",
        "International Trade Compliance Documents",
        "520 trade compliance documents from a customs brokerage covering "
        "tariff classifications, export control regulations, and sanctions "
        "screening.",
    ),
]


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def register_sources(db_url: str, count: int) -> int:
    """Register the first `count` synthetic sources. Returns exit code."""
    if count > len(SYNTHETIC_SOURCES):
        print(
            f"error: requested {count} sources but only "
            f"{len(SYNTHETIC_SOURCES)} are defined in the pool",
            file=sys.stderr,
        )
        return 1

    pool = SYNTHETIC_SOURCES[:count]
    engine = create_db_engine(db_url)
    factory = make_session_factory(engine)

    registered = 0
    skipped = 0

    with session_scope(factory) as session:
        for suffix, name, desc in pool:
            slug = f"{SYNTHETIC_PREFIX}{suffix}"

            existing = session.execute(
                select(Source).where(Source.slug == slug)
            ).scalar_one_or_none()

            if existing is not None:
                skipped += 1
                continue

            source = Source(
                slug=slug,
                name=name,
                description_short=desc,
                description_long=None,
                family=SourceFamily.DOCUMENT,
                status=SourceStatus.CURATED,
                active_physical_index_id=None,
                recipe_version_id=None,
                owner_team="synthetic-eval",
                created_by="script:register_synthetic_sources",
            )
            session.add(source)
            registered += 1

    print(f"Registered {registered} synthetic source(s).")
    if skipped:
        print(f"Skipped {skipped} already-existing source(s).")
    print(f"Total synthetic pool size: {len(SYNTHETIC_SOURCES)}")
    return 0


def list_sources(db_url: str) -> int:
    """List all currently registered synthetic sources."""
    engine = create_db_engine(db_url)
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        sources = (
            session.execute(
                select(Source)
                .where(Source.slug.startswith(SYNTHETIC_PREFIX))
                .order_by(Source.slug)
            )
            .scalars()
            .all()
        )

        if not sources:
            print("No synthetic sources registered.")
            return 0

        print(f"{'Slug':<45} {'Status':<10} Name")
        print("-" * 95)
        for s in sources:
            print(f"{s.slug:<45} {s.status:<10} {s.name}")
        print(f"\n{len(sources)} synthetic source(s) total.")

    return 0


def teardown(db_url: str) -> int:
    """Remove all synthetic sources."""
    engine = create_db_engine(db_url)
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        sources = (
            session.execute(
                select(Source).where(Source.slug.startswith(SYNTHETIC_PREFIX))
            )
            .scalars()
            .all()
        )

        if not sources:
            print("No synthetic sources to remove.")
            return 0

        count = len(sources)
        for s in sources:
            session.delete(s)

        print(f"Removed {count} synthetic source(s).")

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Register synthetic data sources for Phase 6 scale experiments. "
            "Sources appear in list_sources but have no physical index."
        ),
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--count",
        type=int,
        metavar="N",
        help="Register the first N synthetic sources from the pool.",
    )
    group.add_argument(
        "--teardown",
        action="store_true",
        help="Remove all synthetic sources (slug prefix 'synthetic-').",
    )
    group.add_argument(
        "--list",
        action="store_true",
        dest="list_sources",
        help="List currently registered synthetic sources.",
    )

    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help=f"Catalog database URL (default: {DEFAULT_DB_URL})",
    )

    args = parser.parse_args()

    if args.list_sources:
        return list_sources(args.db_url)
    elif args.teardown:
        return teardown(args.db_url)
    else:
        return register_sources(args.db_url, args.count)


if __name__ == "__main__":
    sys.exit(main())
