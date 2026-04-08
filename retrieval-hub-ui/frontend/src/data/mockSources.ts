import type { Source, Persona, AuditRecord } from '../types/source';

// Relative ISO timestamps, computed once at module load for deterministic
// display within a single session.
const NOW = new Date();
const hoursAgo = (h: number): string =>
  new Date(NOW.getTime() - h * 60 * 60 * 1000).toISOString();
const daysAgo = (d: number): string => hoursAgo(d * 24);

// ---------------------------------------------------------------------------
// Personas
// ---------------------------------------------------------------------------

export const PERSONAS: Persona[] = [
  {
    id: 'platform_admin',
    display_name: 'Platform Admin (admin.read)',
    identity_kind: 'human',
    identity_sub: 'user:admin.platform',
    identity_groups: ['platform-admins'],
    scopes: ['admin.read', 'sources.read', 'sources.write'],
    owner_of_teams: [],
  },
  {
    id: 'source_owner_clinical',
    display_name: 'Source Owner — clinical-informatics',
    identity_kind: 'human',
    identity_sub: 'user:alice.clinical',
    identity_groups: ['clinical-informatics', 'clinical-writers'],
    scopes: ['sources.read', 'sources.write'],
    owner_of_teams: ['clinical-informatics'],
  },
  {
    id: 'agent_developer',
    display_name: 'Agent Developer — research-agents',
    identity_kind: 'human',
    identity_sub: 'user:bob.devagent',
    identity_groups: ['agents', 'research-agents'],
    scopes: ['sources.read'],
    owner_of_teams: [],
  },
  {
    id: 'agent_developer_no_access',
    display_name: 'Agent Developer (no access)',
    identity_kind: 'agent',
    identity_sub: 'agent:spiffe://cluster.local/ns/demo/sa/generic-agent',
    identity_groups: ['agents'],
    scopes: ['sources.read'],
    owner_of_teams: [],
  },
];

// ---------------------------------------------------------------------------
// Sources
// ---------------------------------------------------------------------------

const rhProductDocsRecipeYaml = `version: 3
parser:
  kind: docling
  options:
    preserve_tables: true
    extract_figures: false
chunker:
  kind: semantic
  chunk_size_tokens: 512
  overlap_tokens: 64
embedding:
  model: nomic-embed-text-v1.5
  dimension: 768
  served_by: vllm
backend:
  kind: pgvector
  table: idx_rh_product_docs_v3
retrieval:
  default_pattern: vector_ann
  supported_patterns: [vector_ann, vector_with_filters]
`;

const vaClinicalRecipeYaml = `version: 4
parser:
  kind: docling+clinical
  options:
    preserve_section_hierarchy: true
    recognize_icd_codes: true
chunker:
  kind: clinical_section_aware
  chunk_size_tokens: 512
  overlap_tokens: 64
  respect_section_boundaries: true
embedding:
  model: nomic-embed-text-v1.5
  dimension: 768
  served_by: vllm
backend:
  kind: pgvector
  table: idx_va_cpg_v4
retrieval:
  default_pattern: vector_ann
  supported_patterns: [vector_ann, vector_with_filters]
`;

const wikipediaAiRecipeYaml = `version: 2
parser:
  kind: standard_document
chunker:
  kind: token_fixed
  chunk_size_tokens: 384
  overlap_tokens: 32
embedding:
  model: bge-small-en-v1.5
  dimension: 384
  served_by: vllm
backend:
  kind: pgvector
  table: idx_wiki_ai_v2
retrieval:
  default_pattern: vector_ann
  supported_patterns: [vector_ann]
`;

const rhCodeRecipeYaml = `version: 1
parser:
  kind: tree_sitter
  languages: [python, typescript, go]
chunker:
  kind: ast_symbol
  symbol_granularity: [function, class]
embedding:
  model: starcoder-embed-1b
  dimension: 1024
  served_by: vllm
backend:
  kind: pgvector
  table: idx_rh_ai_americas_code_v1
retrieval:
  default_pattern: vector_ann
  supported_patterns: [vector_ann, vector_with_filters]
  parameters:
    vector_with_filters:
      filter_schema_id: code_filter_v1
`;

const clinicalNotesStagingRecipeYaml = `version: 2
parser:
  kind: clinical
chunker:
  kind: clinical_section_aware
  chunk_size_tokens: 512
  overlap_tokens: 64
embedding:
  model: nomic-embed-text-v1.5
  dimension: 768
  served_by: vllm
backend:
  kind: pgvector
  table: idx_clinical_notes_staging_v2
retrieval:
  default_pattern: vector_ann
  supported_patterns: [vector_ann]
`;

const internalResearchDbRecipeYaml = `version: 1
schema_introspection:
  enabled: true
  database: research_analytics
chunker:
  kind: per_row
  text_columns: [description, methodology]
embedding:
  model: none
backend:
  kind: postgres
  database: research_analytics
  tables: 14
retrieval:
  default_pattern: structured_query
  supported_patterns: [structured_query, vector_ann]
  parameters:
    structured_query:
      dialect: text_to_sql
      max_rows: 200
`;

const openshiftKgRecipeYaml = `version: 2
parser:
  kind: custom_graph
chunker:
  kind: node_text
embedding:
  model: nomic-embed-text-v1.5
  dimension: 768
  served_by: vllm
backend:
  kind: apache_age
  graph: openshift_kg_v2
retrieval:
  default_pattern: graph_traverse_from_seed
  supported_patterns: [graph_traverse_from_seed, vector_ann]
  parameters:
    graph_traverse_from_seed:
      seed_top_k_default: 5
      traversal_depth_default: 2
      max_total_nodes_default: 50
`;

const clinicalTrialsIndexRecipeYaml = `version: 1
parser:
  kind: clinicaltrials_gov_api
chunker:
  kind: per_trial
embedding:
  model: nomic-embed-text-v1.5
  dimension: 768
  served_by: vllm
backend:
  kind: pgvector
  table: idx_clinical_trials_index_v1
retrieval:
  default_pattern: vector_ann
  supported_patterns: [vector_ann]
`;

export const MOCK_SOURCES: Source[] = [
  // 1. Red Hat Product Documentation
  {
    id: 'src_01HXRHPRODDOCS',
    slug: 'rh-product-docs',
    name: 'Red Hat Product Documentation',
    family: 'document',
    status: 'published',
    owner: {
      team: 'platform-docs',
      contacts: ['alice.docs@example.com'],
      maintainers: ['bob.docs@example.com'],
    },
    description_short:
      'Public Red Hat product documentation, chunked and embedded for semantic retrieval. Covers OpenShift, RHEL, Ansible, and OpenShift AI.',
    description_long:
      'The canonical Red Hat product documentation corpus, sourced from docs.redhat.com and refreshed weekly. Includes OpenShift Container Platform, Red Hat Enterprise Linux, Ansible Automation Platform, OpenShift AI, and OpenShift Pipelines. Documents are parsed with Docling to preserve tables and code blocks, chunked semantically at ~512 tokens with 64-token overlap, and embedded with nomic-embed-text-v1.5.',
    intended_use:
      'For agents answering questions about Red Hat products and their documented configurations. Well-suited for technical support, documentation search, and product-capability discovery workflows.',
    out_of_scope_use:
      'Not a substitute for Red Hat Customer Portal knowledge base articles, which contain internal troubleshooting content. Not suitable for questions about internal Red Hat engineering roadmaps.',
    known_limitations:
      'Does not include internal knowledge base content. Older product versions may be under-represented if they are no longer linked from the main documentation index.',
    domain_tags: ['technical-docs', 'red-hat'],
    languages: ['en'],
    citation_format: 'Red Hat Documentation, {product} {version}, §{section} (accessed {date})',
    created_at: daysAgo(180),
    updated_at: hoursAgo(2),
    recipe: {
      version: 3,
      parser_kind: 'docling',
      chunker_kind: 'semantic',
      chunker_summary: '512 tok / 64 overlap',
      embedding_model: 'nomic-embed-text-v1.5',
      embedding_dimension: 768,
      backend_kind: 'pgvector',
      backend_location: 'idx_rh_product_docs_v3',
      raw_yaml: rhProductDocsRecipeYaml,
    },
    recipe_version_history: [
      {
        version: 3,
        active_since: daysAgo(45),
        author: 'user:alice.docs',
        summary: 'Switched to nomic-embed-text-v1.5 from bge-small-en-v1.5.',
      },
      {
        version: 2,
        active_since: daysAgo(120),
        author: 'user:alice.docs',
        summary: 'Increased chunk size from 384 to 512 tokens; added 64-token overlap.',
      },
      {
        version: 1,
        active_since: daysAgo(180),
        author: 'user:alice.docs',
        summary: 'Initial recipe.',
      },
    ],
    retrieval_default_pattern: 'vector_ann',
    retrieval_supported_patterns: [
      {
        pattern: 'vector_ann',
        parameters: { top_k_default: 10, top_k_max: 50 },
      },
      {
        pattern: 'vector_with_filters',
        parameters: { top_k_default: 10, top_k_max: 50, filter_schema_id: 'doc_filter_v1' },
      },
    ],
    active_physical_index: {
      id: 'pidx_01HXRHPRODDOCS_v3',
      recipe_version: 3,
      backend_kind: 'pgvector',
      location: 'idx_rh_product_docs_v3',
      built_at: hoursAgo(2),
      document_count: 184302,
      health: 'ok',
    },
    size_summary: '184,302 documents',
    chunk_count_total: 1842010,
    evals: [
      {
        llm: 'granite-3.3-8b-instruct',
        recall_at_5: 0.81,
        mrr: 0.74,
        rewrite_lift_at_5: 0.05,
        source_system: 'llamastack',
        eval_run_id: 'evr_rh_docs_granite_08',
        mlflow_run_id: 'mlfr_rh_docs_granite_08',
        run_at: daysAgo(1),
      },
      {
        llm: 'llama-3.3-70b-instruct',
        recall_at_5: 0.84,
        mrr: 0.78,
        rewrite_lift_at_5: 0.03,
        source_system: 'llamastack',
        eval_run_id: 'evr_rh_docs_llama_12',
        mlflow_run_id: 'mlfr_rh_docs_llama_12',
        run_at: daysAgo(1),
      },
      {
        llm: 'gpt-4o',
        recall_at_5: 0.86,
        mrr: 0.79,
        rewrite_lift_at_5: 0.02,
        source_system: 'imported',
        eval_run_id: 'evr_rh_docs_gpt4o_05',
        mlflow_run_id: null,
        run_at: daysAgo(2),
      },
    ],
    latency_p50_ms: 620,
    latency_p95_ms: 1480,
    cost_estimate_hint: '~0.9k tokens/query',
    rewriter: {
      enabled: true,
      shared_template_pointer: 'rh.rewriter.shared-core',
      shared_template_version: 7,
      vocabulary_mappings: [
        { lay_term: 'RHEL', canonical_term: 'Red Hat Enterprise Linux' },
        { lay_term: 'OCP', canonical_term: 'Red Hat OpenShift Container Platform' },
        { lay_term: 'OpenShift', canonical_term: 'Red Hat OpenShift Container Platform' },
        { lay_term: 'AAP', canonical_term: 'Red Hat Ansible Automation Platform' },
        { lay_term: 'Ansible', canonical_term: 'Red Hat Ansible Automation Platform' },
        { lay_term: 'RHOAI', canonical_term: 'Red Hat OpenShift AI' },
        { lay_term: 'operator hub', canonical_term: 'OperatorHub' },
        { lay_term: 'build pipeline', canonical_term: 'OpenShift Pipelines Tekton PipelineRun' },
      ],
      sample_queries: [
        {
          raw_query: 'how do I set up a build pipeline on OpenShift',
          good_rewrites: [
            'OpenShift Pipelines Tekton PipelineRun configuration',
            'Red Hat OpenShift Container Platform CI/CD pipeline setup',
          ],
        },
        {
          raw_query: 'how do I install RHEL',
          good_rewrites: [
            'Red Hat Enterprise Linux installation guide',
            'RHEL installer Anaconda kickstart',
          ],
        },
      ],
      domain_notes:
        'Red Hat product documentation. Prefer official product names (Red Hat Enterprise Linux, not "RHEL") in reformulated queries. Expand acronyms on first reference.',
      schema_hints: null,
      prompt_override_id: null,
      default_llm: 'granite-3.3-8b-instruct',
      llm_resolution: 'default',
      max_rewrites: 5,
      metadata_version: 4,
    },
    agent_write_policy: {
      allowed: false,
      scope_required: 'sources.write',
      allowed_groups: [],
      write_modes: [],
      write_validation: null,
    },
    sample_prompts: [
      {
        applies_to_llm_family: 'granite-3-*',
        role: 'system',
        text: `You are answering questions about Red Hat products using retrieved documentation.

When responding:
- Cite the doc title and section for every factual claim.
- Prefer official product names: "Red Hat Enterprise Linux" not "RHEL".
- If the retrieved context does not answer the question, say so and suggest a related doc.`,
      },
      {
        applies_to_llm_family: 'llama-3.3-*',
        role: 'system',
        text: `You are a Red Hat product documentation assistant. Use the retrieved chunks to answer accurately and cite sources.

Guidelines:
- Always cite the product name, doc title, and section.
- If retrieved context is insufficient, acknowledge the gap.
- Prefer canonical product names.`,
      },
      {
        applies_to_llm_family: 'gpt-4o',
        role: 'system',
        text: `You are a Red Hat documentation expert. Answer questions strictly from the retrieved context and cite every factual claim by (product, doc title, section).`,
      },
      {
        applies_to_llm_family: 'generic',
        role: 'system',
        text: `Answer questions about Red Hat products using only the retrieved documentation. Cite doc title and section. Use official product names.`,
      },
    ],
    lineage: {
      origin_kind: 'web_crawl',
      origin_config: {
        roots: ['https://docs.redhat.com/en/documentation/'],
        allow_patterns: ['*.html'],
        respect_robots_txt: true,
      },
      refresh_cadence: 'weekly',
      last_refresh_at: hoursAgo(2),
      next_scheduled_refresh_at: daysAgo(-5),
      ingestion_runs: [
        {
          id: 'run_01HXRHPRODDOCS_latest',
          status: 'completed',
          started_at: hoursAgo(3),
          duration_seconds: 2140,
          document_count: 184302,
          triggered_by: 'scheduler:refresh-cron',
        },
        {
          id: 'run_01HXRHPRODDOCS_prev',
          status: 'completed',
          started_at: daysAgo(7),
          duration_seconds: 2098,
          document_count: 183920,
          triggered_by: 'scheduler:refresh-cron',
        },
        {
          id: 'run_01HXRHPRODDOCS_prev2',
          status: 'completed',
          started_at: daysAgo(14),
          duration_seconds: 2210,
          document_count: 183480,
          triggered_by: 'scheduler:refresh-cron',
        },
      ],
    },
    access: {
      visibility: 'public',
      allowed_groups: [],
    },
    health_flags: [],
  },

  // 2. VA Clinical Practice Guidelines — the hero rewriter example
  {
    id: 'src_01HXVACLINICAL',
    slug: 'va-clinical-guidelines',
    name: 'VA Clinical Practice Guidelines',
    family: 'clinical_document',
    status: 'published',
    owner: {
      team: 'clinical-informatics',
      contacts: ['alice.clinical@example.com', 'bob.clinical@example.com'],
      maintainers: ['carla.clinical@example.com'],
    },
    description_short:
      'VA/DoD clinical practice guidelines, chunked and embedded for clinical-vocabulary semantic retrieval.',
    description_long: `VA/DoD Clinical Practice Guidelines corpus, covering the full public catalog of guidelines published by the U.S. Department of Veterans Affairs and Department of Defense.

The corpus includes guidelines for type 2 diabetes mellitus, hypertension, major depressive disorder, post-traumatic stress disorder, substance use disorders, chronic pain, low back pain, osteoarthritis, chronic kidney disease, heart failure, atrial fibrillation, asthma, COPD, headache, dyslipidemia, and approximately 40 additional conditions.

Documents are parsed with a clinical-aware parser that preserves section hierarchy (Recommendations, Evidence Review, Algorithm, Implementation Guidance), and chunked with a clinical section-aware chunker that respects those boundaries. The rewriter is the hero feature of this source — extensive vocabulary mappings translate lay-language patient phrasings into the clinical vocabulary used in the guidelines themselves.`,
    intended_use:
      'For agents answering clinical-guideline questions. The rewriter translates lay-language questions into clinical-vocabulary queries, dramatically improving recall on patient-phrased questions.',
    out_of_scope_use:
      'Individual patient-specific medical advice. The guidelines describe population-level evidence and recommendations, not personalized treatment plans. Not a substitute for a licensed clinician.',
    known_limitations:
      'Corpus does not include non-VA guidelines (no NICE, no WHO, no USPSTF). The rewriter is essential for lay-language queries; disabling it drops recall by approximately 0.22 on patient-phrased questions. Coverage of rare conditions is limited.',
    domain_tags: ['clinical', 'regulated'],
    languages: ['en'],
    citation_format: 'VA/DoD Clinical Practice Guideline for the Management of {condition} ({year}), §{section}',
    created_at: daysAgo(220),
    updated_at: hoursAgo(2),
    recipe: {
      version: 4,
      parser_kind: 'docling+clinical',
      chunker_kind: 'clinical_section_aware',
      chunker_summary: '512 tok / 64 overlap, section-aware',
      embedding_model: 'nomic-embed-text-v1.5',
      embedding_dimension: 768,
      backend_kind: 'pgvector',
      backend_location: 'idx_va_cpg_v4',
      raw_yaml: vaClinicalRecipeYaml,
    },
    recipe_version_history: [
      {
        version: 4,
        active_since: daysAgo(30),
        author: 'user:alice.clinical',
        summary: 'Added clinical_section_aware chunker; preserves Recommendations / Evidence Review boundaries.',
      },
      {
        version: 3,
        active_since: daysAgo(90),
        author: 'user:alice.clinical',
        summary: 'Bumped embedding model to nomic-embed-text-v1.5.',
      },
      {
        version: 2,
        active_since: daysAgo(160),
        author: 'user:alice.clinical',
        summary: 'Added clinical-aware parser (docling+clinical).',
      },
      {
        version: 1,
        active_since: daysAgo(220),
        author: 'user:alice.clinical',
        summary: 'Initial recipe.',
      },
    ],
    retrieval_default_pattern: 'vector_ann',
    retrieval_supported_patterns: [
      {
        pattern: 'vector_ann',
        parameters: { top_k_default: 10, top_k_max: 50 },
      },
      {
        pattern: 'vector_with_filters',
        parameters: { top_k_default: 10, top_k_max: 50, filter_schema_id: 'clinical_filter_v1' },
      },
    ],
    active_physical_index: {
      id: 'pidx_01HXVACLINICAL_v4',
      recipe_version: 4,
      backend_kind: 'pgvector',
      location: 'idx_va_cpg_v4',
      built_at: hoursAgo(2),
      document_count: 18402,
      health: 'ok',
    },
    size_summary: '18,402 documents',
    chunk_count_total: 214820,
    evals: [
      {
        llm: 'granite-3.3-8b-instruct',
        recall_at_5: 0.74,
        mrr: 0.68,
        rewrite_lift_at_5: 0.27,
        source_system: 'llamastack',
        eval_run_id: 'evr_va_cpg_granite_19',
        mlflow_run_id: 'mlfr_va_cpg_granite_19',
        run_at: hoursAgo(18),
      },
      {
        llm: 'llama-3.3-70b-instruct',
        recall_at_5: 0.78,
        mrr: 0.71,
        rewrite_lift_at_5: 0.22,
        source_system: 'llamastack',
        eval_run_id: 'evr_va_cpg_llama_14',
        mlflow_run_id: 'mlfr_va_cpg_llama_14',
        run_at: hoursAgo(18),
      },
      {
        llm: 'gpt-4o',
        recall_at_5: 0.79,
        mrr: 0.74,
        rewrite_lift_at_5: 0.18,
        source_system: 'imported',
        eval_run_id: 'evr_va_cpg_gpt4o_09',
        mlflow_run_id: null,
        run_at: daysAgo(2),
      },
    ],
    latency_p50_ms: 820,
    latency_p95_ms: 1820,
    cost_estimate_hint: '~1.2k tokens/query',
    rewriter: {
      enabled: true,
      shared_template_pointer: 'rh.rewriter.shared-core',
      shared_template_version: 7,
      vocabulary_mappings: [
        { lay_term: 'high blood sugar', canonical_term: 'hyperglycemia' },
        { lay_term: 'low blood sugar', canonical_term: 'hypoglycemia' },
        { lay_term: 'high blood pressure', canonical_term: 'hypertension' },
        { lay_term: 'low blood pressure', canonical_term: 'hypotension' },
        { lay_term: 'sugar diabetes', canonical_term: 'diabetes mellitus' },
        { lay_term: 'type 2 diabetes', canonical_term: 'type 2 diabetes mellitus', qualifiers: 'T2DM' },
        { lay_term: 'heart attack', canonical_term: 'myocardial infarction' },
        { lay_term: 'stroke', canonical_term: 'cerebrovascular accident' },
        { lay_term: 'mini stroke', canonical_term: 'transient ischemic attack' },
        { lay_term: 'depression', canonical_term: 'major depressive disorder' },
        { lay_term: 'PTSD', canonical_term: 'post-traumatic stress disorder' },
        { lay_term: 'anxiety', canonical_term: 'generalized anxiety disorder' },
        { lay_term: 'alcoholism', canonical_term: 'alcohol use disorder' },
        { lay_term: 'drug addiction', canonical_term: 'substance use disorder' },
        { lay_term: 'chronic pain', canonical_term: 'chronic noncancer pain' },
        { lay_term: 'back pain', canonical_term: 'low back pain' },
        { lay_term: 'arthritis', canonical_term: 'osteoarthritis' },
        { lay_term: 'kidney disease', canonical_term: 'chronic kidney disease', qualifiers: 'CKD' },
        { lay_term: 'heart failure', canonical_term: 'heart failure', qualifiers: 'HFrEF, HFpEF' },
        { lay_term: 'irregular heartbeat', canonical_term: 'atrial fibrillation' },
        { lay_term: 'high cholesterol', canonical_term: 'hyperlipidemia' },
        { lay_term: 'asthma attack', canonical_term: 'asthma exacerbation' },
        { lay_term: 'emphysema', canonical_term: 'chronic obstructive pulmonary disease' },
        { lay_term: 'COPD', canonical_term: 'chronic obstructive pulmonary disease' },
        { lay_term: 'migraine', canonical_term: 'migraine headache' },
        { lay_term: 'trouble sleeping', canonical_term: 'insomnia' },
        { lay_term: 'feeling down', canonical_term: 'depressed mood' },
        { lay_term: 'hearing voices', canonical_term: 'auditory hallucinations' },
        { lay_term: 'shortness of breath', canonical_term: 'dyspnea' },
        { lay_term: 'chest pain', canonical_term: 'chest pain', qualifiers: 'angina vs noncardiac' },
        { lay_term: 'weight loss', canonical_term: 'unintentional weight loss' },
        { lay_term: 'tired all the time', canonical_term: 'fatigue' },
        { lay_term: 'fever', canonical_term: 'pyrexia' },
        { lay_term: 'water pills', canonical_term: 'diuretics' },
        { lay_term: 'blood thinners', canonical_term: 'anticoagulants' },
        { lay_term: 'sugar pills', canonical_term: 'oral hypoglycemic agents' },
        { lay_term: 'blood pressure pills', canonical_term: 'antihypertensive agents' },
        { lay_term: 'cholesterol pills', canonical_term: 'statins' },
        { lay_term: 'painkillers', canonical_term: 'analgesics' },
        { lay_term: 'opioids', canonical_term: 'opioid analgesics' },
        { lay_term: 'antidepressants', canonical_term: 'antidepressant pharmacotherapy' },
        { lay_term: 'SSRIs', canonical_term: 'selective serotonin reuptake inhibitors' },
        { lay_term: 'therapy', canonical_term: 'psychotherapy' },
        { lay_term: 'talk therapy', canonical_term: 'cognitive behavioral therapy' },
        { lay_term: 'CBT', canonical_term: 'cognitive behavioral therapy' },
        { lay_term: 'blood test', canonical_term: 'serum laboratory evaluation' },
        { lay_term: 'A1C', canonical_term: 'hemoglobin A1c' },
        { lay_term: 'EKG', canonical_term: 'electrocardiogram' },
        { lay_term: 'CT scan', canonical_term: 'computed tomography' },
        { lay_term: 'MRI', canonical_term: 'magnetic resonance imaging' },
        { lay_term: 'x-ray', canonical_term: 'radiograph' },
        { lay_term: 'ultrasound', canonical_term: 'sonography' },
        { lay_term: 'sleep apnea', canonical_term: 'obstructive sleep apnea' },
      ],
      sample_queries: [
        {
          raw_query: 'how should I screen a veteran for diabetes',
          good_rewrites: [
            'VA/DoD guideline screening type 2 diabetes mellitus hemoglobin A1c fasting plasma glucose',
            'diabetes mellitus screening criteria VA/DoD recommendations',
          ],
        },
        {
          raw_query: 'what is the first line treatment for high blood pressure',
          good_rewrites: [
            'VA/DoD guideline first-line antihypertensive pharmacotherapy hypertension',
            'hypertension initial management thiazide ACE inhibitor calcium channel blocker',
          ],
        },
        {
          raw_query: 'how do I manage chronic low back pain',
          good_rewrites: [
            'VA/DoD guideline chronic low back pain non-pharmacologic pharmacologic management',
            'chronic low back pain cognitive behavioral therapy exercise therapy NSAIDs',
          ],
        },
        {
          raw_query: 'what is the recommended therapy for PTSD',
          good_rewrites: [
            'VA/DoD guideline post-traumatic stress disorder trauma-focused psychotherapy',
            'PTSD prolonged exposure cognitive processing therapy EMDR',
          ],
        },
        {
          raw_query: 'when should I start statins for high cholesterol',
          good_rewrites: [
            'VA/DoD guideline statin initiation hyperlipidemia atherosclerotic cardiovascular disease risk',
            'dyslipidemia management statin therapy ASCVD risk calculator',
          ],
        },
        {
          raw_query: 'how to treat alcoholism',
          good_rewrites: [
            'VA/DoD guideline alcohol use disorder pharmacotherapy naltrexone acamprosate',
            'alcohol use disorder behavioral interventions motivational interviewing',
          ],
        },
        {
          raw_query: 'what medications treat depression',
          good_rewrites: [
            'VA/DoD guideline major depressive disorder antidepressant pharmacotherapy SSRIs SNRIs',
            'major depressive disorder first-line pharmacotherapy sertraline fluoxetine',
          ],
        },
        {
          raw_query: 'how to screen for osteoporosis',
          good_rewrites: [
            'VA/DoD guideline osteoporosis screening DXA bone mineral density',
            'osteoporosis fracture risk assessment FRAX',
          ],
        },
        {
          raw_query: 'treatment for opioid addiction',
          good_rewrites: [
            'VA/DoD guideline opioid use disorder medication-assisted treatment buprenorphine methadone',
            'opioid use disorder harm reduction naloxone',
          ],
        },
        {
          raw_query: 'how to manage heart failure',
          good_rewrites: [
            'VA/DoD guideline heart failure reduced ejection fraction guideline-directed medical therapy',
            'heart failure ACE inhibitor ARNI beta blocker SGLT2 inhibitor',
          ],
        },
        {
          raw_query: 'asthma exacerbation treatment',
          good_rewrites: [
            'VA/DoD guideline asthma exacerbation short-acting beta agonist systemic corticosteroids',
            'asthma exacerbation emergency management oxygen SABA',
          ],
        },
        {
          raw_query: 'when to start dialysis',
          good_rewrites: [
            'VA/DoD guideline chronic kidney disease renal replacement therapy initiation',
            'end-stage renal disease dialysis indications GFR',
          ],
        },
      ],
      domain_notes: `This source covers VA/DoD clinical practice guidelines. Queries against this source should be reformulated into clinical vocabulary:

- Lay terms for conditions should be expanded to canonical clinical terminology ("high blood sugar" → "hyperglycemia", "heart attack" → "myocardial infarction").
- Patient-phrased questions should be reformulated to reflect the structure of the guidelines (Recommendations, Evidence Review, Management).
- Medication classes should be named by their clinical class (e.g., "water pills" → "diuretics", "blood thinners" → "anticoagulants").
- Diagnostic tests should use their clinical names (e.g., "blood test" → "serum laboratory evaluation", "A1C" → "hemoglobin A1c").
- Always preserve the "VA/DoD" scope marker in rewrites to keep retrieval focused on this corpus.`,
      schema_hints: null,
      prompt_override_id: null,
      default_llm: 'granite-3.3-8b-instruct',
      llm_resolution: 'default',
      max_rewrites: 5,
      metadata_version: 9,
    },
    agent_write_policy: {
      allowed: false,
      scope_required: 'sources.write',
      allowed_groups: [],
      write_modes: [],
      write_validation: null,
    },
    sample_prompts: [
      {
        applies_to_llm_family: 'granite-3-*',
        role: 'system',
        text: `You are answering clinical questions using VA/DoD Clinical Practice Guidelines.

Strict guidance:
- Only use retrieved context; if a fact is not in the retrieved chunks, say so.
- Cite the guideline condition, year, and section for every recommendation.
- Do NOT provide individualized medical advice; answer at the population/guideline level.
- Use clinical terminology but offer a brief lay-language explanation.`,
      },
      {
        applies_to_llm_family: 'llama-3.3-*',
        role: 'system',
        text: `You are a VA/DoD Clinical Practice Guideline assistant. Answer strictly from the retrieved guideline chunks.

Rules:
- Cite (guideline title, year, section) for every recommendation.
- Do not give individual medical advice.
- Flag any question that is out of scope for the VA/DoD guideline corpus.`,
      },
      {
        applies_to_llm_family: 'gpt-4o',
        role: 'system',
        text: `You are a clinical guidelines expert for VA/DoD practice guidelines. Use only retrieved context; cite guideline, year, section. Never give individualized patient advice. If the question is not addressed by the retrieved context, say so explicitly.`,
      },
    ],
    lineage: {
      origin_kind: 'web_crawl',
      origin_config: {
        roots: ['https://www.healthquality.va.gov/guidelines/'],
        respect_robots_txt: true,
        include_pdfs: true,
      },
      refresh_cadence: 'weekly',
      last_refresh_at: hoursAgo(2),
      next_scheduled_refresh_at: daysAgo(-5),
      ingestion_runs: [
        {
          id: 'run_01HXVACLINICAL_latest',
          status: 'completed',
          started_at: hoursAgo(3),
          duration_seconds: 612,
          document_count: 18402,
          triggered_by: 'scheduler:refresh-cron',
        },
        {
          id: 'run_01HXVACLINICAL_prev',
          status: 'completed',
          started_at: daysAgo(7),
          duration_seconds: 598,
          document_count: 18385,
          triggered_by: 'scheduler:refresh-cron',
        },
      ],
    },
    access: {
      visibility: 'public',
      allowed_groups: [],
    },
    health_flags: [],
  },

  // 3. Wikipedia AI Subset
  {
    id: 'src_01HXWIKIAI',
    slug: 'wikipedia-ai',
    name: 'Wikipedia AI Subset',
    family: 'document',
    status: 'published',
    owner: {
      team: 'platform-docs',
      contacts: ['wiki-curator@example.com'],
      maintainers: [],
    },
    description_short:
      'Curated Wikipedia articles about AI, machine learning, and related topics.',
    description_long:
      'A curated slice of Wikipedia covering artificial intelligence, machine learning, natural language processing, computer vision, statistics, and closely related subjects. Refreshed daily from Wikipedia dumps.',
    intended_use:
      'Broad general knowledge for agents handling diverse questions about AI concepts, historical context, and foundational definitions.',
    out_of_scope_use:
      'Not authoritative for cutting-edge research results (Wikipedia lags primary sources). Not a substitute for domain-specific sources.',
    known_limitations:
      'Rewriter is not enabled; general-knowledge text does not benefit meaningfully from vocabulary translation. Reflects the English Wikipedia community\'s coverage gaps.',
    domain_tags: ['general-knowledge', 'curated'],
    languages: ['en'],
    citation_format: 'Wikipedia contributors, "{article}", Wikipedia, The Free Encyclopedia (accessed {date})',
    created_at: daysAgo(90),
    updated_at: hoursAgo(6),
    recipe: {
      version: 2,
      parser_kind: 'standard_document',
      chunker_kind: 'token_fixed',
      chunker_summary: '384 tok / 32 overlap',
      embedding_model: 'bge-small-en-v1.5',
      embedding_dimension: 384,
      backend_kind: 'pgvector',
      backend_location: 'idx_wiki_ai_v2',
      raw_yaml: wikipediaAiRecipeYaml,
    },
    recipe_version_history: [
      {
        version: 2,
        active_since: daysAgo(20),
        author: 'user:wiki.curator',
        summary: 'Reduced chunk size to 384 for better granularity on short articles.',
      },
      {
        version: 1,
        active_since: daysAgo(90),
        author: 'user:wiki.curator',
        summary: 'Initial recipe.',
      },
    ],
    retrieval_default_pattern: 'vector_ann',
    retrieval_supported_patterns: [
      {
        pattern: 'vector_ann',
        parameters: { top_k_default: 10, top_k_max: 50 },
      },
    ],
    active_physical_index: {
      id: 'pidx_01HXWIKIAI_v2',
      recipe_version: 2,
      backend_kind: 'pgvector',
      location: 'idx_wiki_ai_v2',
      built_at: hoursAgo(6),
      document_count: 52841,
      health: 'ok',
    },
    size_summary: '52,841 articles',
    chunk_count_total: 380188,
    evals: [
      {
        llm: 'granite-3.3-8b-instruct',
        recall_at_5: 0.68,
        mrr: 0.6,
        rewrite_lift_at_5: null,
        source_system: 'native',
        eval_run_id: 'evr_wiki_ai_granite_03',
        mlflow_run_id: null,
        run_at: daysAgo(2),
      },
      {
        llm: 'gpt-4o',
        recall_at_5: 0.75,
        mrr: 0.69,
        rewrite_lift_at_5: null,
        source_system: 'native',
        eval_run_id: 'evr_wiki_ai_gpt4o_02',
        mlflow_run_id: null,
        run_at: daysAgo(2),
      },
    ],
    latency_p50_ms: 340,
    latency_p95_ms: 720,
    cost_estimate_hint: '~0.6k tokens/query',
    rewriter: {
      enabled: false,
      vocabulary_mappings: [],
      sample_queries: [],
      domain_notes: '',
      schema_hints: null,
      prompt_override_id: null,
      default_llm: 'granite-3.3-8b-instruct',
      llm_resolution: 'default',
      max_rewrites: 0,
      metadata_version: 1,
    },
    agent_write_policy: {
      allowed: false,
      scope_required: 'sources.write',
      allowed_groups: [],
      write_modes: [],
      write_validation: null,
    },
    sample_prompts: [
      {
        applies_to_llm_family: 'granite-3-*',
        role: 'system',
        text: 'You are answering general-knowledge questions about AI using retrieved Wikipedia articles. Cite article titles. If the retrieved context is insufficient, say so.',
      },
      {
        applies_to_llm_family: 'gpt-4o',
        role: 'system',
        text: 'You are a general AI knowledge assistant using Wikipedia as the source. Cite article titles. Acknowledge Wikipedia\'s recency limitations.',
      },
    ],
    lineage: {
      origin_kind: 'web_crawl',
      origin_config: {
        source: 'wikipedia_dump',
        language: 'en',
        curation: 'topic_filter:ai_ml_nlp_cv_stats',
      },
      refresh_cadence: 'daily',
      last_refresh_at: hoursAgo(6),
      next_scheduled_refresh_at: hoursAgo(-18),
      ingestion_runs: [
        {
          id: 'run_01HXWIKIAI_latest',
          status: 'completed',
          started_at: hoursAgo(7),
          duration_seconds: 1820,
          document_count: 52841,
          triggered_by: 'scheduler:refresh-cron',
        },
      ],
    },
    access: {
      visibility: 'public',
      allowed_groups: [],
    },
    health_flags: [],
  },

  // 4. Red Hat AI Americas — Public Code Repos
  {
    id: 'src_01HXRHAICODE',
    slug: 'rh-ai-americas-code',
    name: 'Red Hat AI Americas — Public Code Repos',
    family: 'code',
    status: 'published',
    owner: {
      team: 'ai-americas',
      contacts: ['ai-americas@example.com'],
      maintainers: ['code-curator@example.com'],
    },
    description_short:
      'Source code from Red Hat AI Americas public repositories on GitHub. AST-aware chunking preserves function and class boundaries.',
    description_long:
      'All public repositories under the Red Hat AI Americas organization on GitHub. Code is parsed with tree-sitter and chunked at the function/class level so retrieval results are syntactically coherent symbols, not arbitrary text slices.',
    intended_use:
      'For agents answering questions about Red Hat AI Americas code patterns, examples, and utilities. Useful for "how do we usually do X" style queries against our internal conventions.',
    out_of_scope_use:
      'Not a substitute for reading the README of a project before using it. Does not capture verbal conventions that aren\'t in the code.',
    known_limitations:
      'Rewriter is not enabled because code queries do not benefit from vocabulary translation. Binary assets and generated files are excluded.',
    domain_tags: ['python', 'typescript', 'ai-americas'],
    languages: ['en'],
    citation_format: '{repo}/{path}:{symbol} (commit {sha})',
    created_at: daysAgo(120),
    updated_at: daysAgo(4),
    recipe: {
      version: 1,
      parser_kind: 'tree_sitter',
      chunker_kind: 'ast_symbol',
      chunker_summary: 'AST-aware, function/class-level',
      embedding_model: 'starcoder-embed-1b',
      embedding_dimension: 1024,
      backend_kind: 'pgvector',
      backend_location: 'idx_rh_ai_americas_code_v1',
      raw_yaml: rhCodeRecipeYaml,
    },
    recipe_version_history: [
      {
        version: 1,
        active_since: daysAgo(120),
        author: 'user:code.curator',
        summary: 'Initial recipe.',
      },
    ],
    retrieval_default_pattern: 'vector_ann',
    retrieval_supported_patterns: [
      {
        pattern: 'vector_ann',
        parameters: { top_k_default: 10, top_k_max: 50 },
      },
      {
        pattern: 'vector_with_filters',
        parameters: { top_k_default: 10, top_k_max: 50, filter_schema_id: 'code_filter_v1' },
      },
    ],
    active_physical_index: {
      id: 'pidx_01HXRHAICODE_v1',
      recipe_version: 1,
      backend_kind: 'pgvector',
      location: 'idx_rh_ai_americas_code_v1',
      built_at: daysAgo(4),
      document_count: 8234,
      health: 'degraded',
    },
    size_summary: '8,234 files · 42,109 symbols',
    chunk_count_total: 42109,
    evals: [
      {
        llm: 'granite-3.3-8b-instruct',
        recall_at_5: 0.71,
        mrr: 0.64,
        rewrite_lift_at_5: null,
        source_system: 'native',
        eval_run_id: 'evr_rh_code_granite_04',
        mlflow_run_id: null,
        run_at: daysAgo(5),
      },
      {
        llm: 'gpt-4o',
        recall_at_5: 0.76,
        mrr: 0.69,
        rewrite_lift_at_5: null,
        source_system: 'native',
        eval_run_id: 'evr_rh_code_gpt4o_03',
        mlflow_run_id: null,
        run_at: daysAgo(5),
      },
    ],
    latency_p50_ms: 480,
    latency_p95_ms: 1120,
    cost_estimate_hint: '~0.8k tokens/query',
    rewriter: {
      enabled: false,
      vocabulary_mappings: [],
      sample_queries: [],
      domain_notes: 'Code queries are typically well-formed; rewriter does not currently add value.',
      schema_hints: null,
      prompt_override_id: null,
      default_llm: 'granite-3.3-8b-instruct',
      llm_resolution: 'default',
      max_rewrites: 0,
      metadata_version: 1,
    },
    agent_write_policy: {
      allowed: false,
      scope_required: 'sources.write',
      allowed_groups: [],
      write_modes: [],
      write_validation: null,
    },
    sample_prompts: [
      {
        applies_to_llm_family: 'granite-3-*',
        role: 'system',
        text: 'You answer questions about Red Hat AI Americas code examples and patterns. Cite file paths and symbol names. Prefer showing working code over prose.',
      },
      {
        applies_to_llm_family: 'gpt-4o',
        role: 'system',
        text: 'You are a code-examples assistant for Red Hat AI Americas. Always include the file path and function/class name when citing. Prefer runnable snippets.',
      },
    ],
    lineage: {
      origin_kind: 'git_clone',
      origin_config: {
        github_org: 'redhat-ai-americas',
        visibility: 'public',
        exclude: ['dist/', 'build/', 'node_modules/'],
      },
      refresh_cadence: 'on_demand',
      last_refresh_at: daysAgo(4),
      next_scheduled_refresh_at: null,
      ingestion_runs: [
        {
          id: 'run_01HXRHAICODE_latest',
          status: 'completed',
          started_at: daysAgo(4),
          duration_seconds: 412,
          document_count: 8234,
          triggered_by: 'user:code.curator',
        },
      ],
    },
    access: {
      visibility: 'public',
      allowed_groups: [],
    },
    health_flags: [
      {
        kind: 'degraded_index',
        detail:
          'Active physical index has reported degraded health since 2 days ago. Recommended action: rebuild from current HEAD of all tracked repos.',
      },
    ],
  },

  // 5. Clinical Notes Staging — restricted + agent writable
  {
    id: 'src_01HXCLINSTAGE',
    slug: 'clinical-notes-staging',
    name: 'Clinical Notes Staging',
    family: 'clinical_document',
    status: 'published',
    owner: {
      team: 'clinical-informatics',
      contacts: ['alice.clinical@example.com'],
      maintainers: ['carla.clinical@example.com'],
    },
    description_short:
      'Staging area for clinical notes under review. Agent-writable for automated note enrichment workflows.',
    description_long:
      'This source holds clinical notes that are under review or enrichment. Agents in the `clinical-writers` group can append new notes or annotate existing ones under a validation schema. The staging corpus is not intended as a primary query surface for agent developers; it exists to support human-in-the-loop enrichment workflows and supervised retrieval experiments.',
    intended_use:
      'Staging surface for agents doing clinical note enrichment. Writes are append-only or annotation; no destructive edits.',
    out_of_scope_use:
      'Not a production clinical query surface. Do not use for agent responses to end users; use the published clinical guideline corpus instead.',
    known_limitations:
      'Refresh cadence is daily but actual freshness depends on the upstream review queue. Contents may be incomplete or in-progress.',
    domain_tags: ['clinical', 'staging'],
    languages: ['en'],
    citation_format: null,
    created_at: daysAgo(60),
    updated_at: hoursAgo(12),
    recipe: {
      version: 2,
      parser_kind: 'clinical',
      chunker_kind: 'clinical_section_aware',
      chunker_summary: '512 tok / 64 overlap, section-aware',
      embedding_model: 'nomic-embed-text-v1.5',
      embedding_dimension: 768,
      backend_kind: 'pgvector',
      backend_location: 'idx_clinical_notes_staging_v2',
      raw_yaml: clinicalNotesStagingRecipeYaml,
    },
    recipe_version_history: [
      {
        version: 2,
        active_since: daysAgo(20),
        author: 'user:alice.clinical',
        summary: 'Added clinical_section_aware chunker.',
      },
      {
        version: 1,
        active_since: daysAgo(60),
        author: 'user:alice.clinical',
        summary: 'Initial recipe.',
      },
    ],
    retrieval_default_pattern: 'vector_ann',
    retrieval_supported_patterns: [
      {
        pattern: 'vector_ann',
        parameters: { top_k_default: 10, top_k_max: 50 },
      },
    ],
    active_physical_index: {
      id: 'pidx_01HXCLINSTAGE_v2',
      recipe_version: 2,
      backend_kind: 'pgvector',
      location: 'idx_clinical_notes_staging_v2',
      built_at: hoursAgo(12),
      document_count: 2184,
      health: 'ok',
    },
    size_summary: '2,184 notes',
    chunk_count_total: 14920,
    evals: [
      {
        llm: 'granite-3.3-8b-instruct',
        recall_at_5: 0.69,
        mrr: 0.62,
        rewrite_lift_at_5: 0.18,
        source_system: 'llamastack',
        eval_run_id: 'evr_clin_staging_granite_02',
        mlflow_run_id: 'mlfr_clin_staging_granite_02',
        run_at: daysAgo(1),
      },
    ],
    latency_p50_ms: 540,
    latency_p95_ms: 1220,
    cost_estimate_hint: '~1.0k tokens/query',
    rewriter: {
      enabled: true,
      shared_template_pointer: 'rh.rewriter.shared-core',
      shared_template_version: 7,
      vocabulary_mappings: [
        { lay_term: 'high blood sugar', canonical_term: 'hyperglycemia' },
        { lay_term: 'high blood pressure', canonical_term: 'hypertension' },
        { lay_term: 'heart attack', canonical_term: 'myocardial infarction' },
        { lay_term: 'stroke', canonical_term: 'cerebrovascular accident' },
        { lay_term: 'depression', canonical_term: 'major depressive disorder' },
        { lay_term: 'chronic pain', canonical_term: 'chronic noncancer pain' },
        { lay_term: 'anxiety', canonical_term: 'generalized anxiety disorder' },
        { lay_term: 'PTSD', canonical_term: 'post-traumatic stress disorder' },
        { lay_term: 'alcoholism', canonical_term: 'alcohol use disorder' },
        { lay_term: 'back pain', canonical_term: 'low back pain' },
        { lay_term: 'kidney disease', canonical_term: 'chronic kidney disease' },
        { lay_term: 'heart failure', canonical_term: 'heart failure' },
        { lay_term: 'irregular heartbeat', canonical_term: 'atrial fibrillation' },
        { lay_term: 'blood thinners', canonical_term: 'anticoagulants' },
        { lay_term: 'water pills', canonical_term: 'diuretics' },
        { lay_term: 'painkillers', canonical_term: 'analgesics' },
        { lay_term: 'statins', canonical_term: 'HMG-CoA reductase inhibitors' },
        { lay_term: 'therapy', canonical_term: 'psychotherapy' },
        { lay_term: 'CBT', canonical_term: 'cognitive behavioral therapy' },
        { lay_term: 'A1C', canonical_term: 'hemoglobin A1c' },
        { lay_term: 'EKG', canonical_term: 'electrocardiogram' },
        { lay_term: 'MRI', canonical_term: 'magnetic resonance imaging' },
        { lay_term: 'CT', canonical_term: 'computed tomography' },
        { lay_term: 'sleep apnea', canonical_term: 'obstructive sleep apnea' },
        { lay_term: 'opioids', canonical_term: 'opioid analgesics' },
      ],
      sample_queries: [
        {
          raw_query: 'notes about a patient with high blood sugar',
          good_rewrites: [
            'clinical notes mentioning hyperglycemia',
            'notes documenting type 2 diabetes mellitus hyperglycemia',
          ],
        },
        {
          raw_query: 'PTSD treatment notes',
          good_rewrites: [
            'clinical notes documenting post-traumatic stress disorder pharmacotherapy psychotherapy',
          ],
        },
      ],
      domain_notes:
        'Staging clinical notes corpus. Reformulate lay language to clinical vocabulary before retrieval. Notes may include abbreviations; expand them in rewrites.',
      schema_hints: null,
      prompt_override_id: null,
      default_llm: 'granite-3.3-8b-instruct',
      llm_resolution: 'default',
      max_rewrites: 5,
      metadata_version: 3,
    },
    agent_write_policy: {
      allowed: true,
      scope_required: 'sources.write',
      allowed_groups: ['clinical-writers'],
      write_modes: ['append', 'annotate'],
      write_validation: {
        schema_id: 'clinical_note_v1',
        require_provenance: true,
      },
      recent_write_activity_summary: '23 writes in last 7 days from 4 identities',
    },
    sample_prompts: [
      {
        applies_to_llm_family: 'granite-3-*',
        role: 'system',
        text: 'You are an assistant operating over a staging corpus of clinical notes under human review. Cite note ids and sections. Use clinical terminology.',
      },
    ],
    lineage: {
      origin_kind: 'file_upload',
      origin_config: {
        staging_bucket: 'clinical-notes-staging',
        review_queue: 'clinical-informatics-queue',
      },
      refresh_cadence: 'daily',
      last_refresh_at: hoursAgo(12),
      next_scheduled_refresh_at: hoursAgo(-12),
      ingestion_runs: [
        {
          id: 'run_01HXCLINSTAGE_latest',
          status: 'completed',
          started_at: hoursAgo(13),
          duration_seconds: 184,
          document_count: 2184,
          triggered_by: 'scheduler:refresh-cron',
        },
      ],
    },
    access: {
      visibility: 'restricted',
      allowed_groups: ['clinical-agents', 'clinical-writers'],
    },
    health_flags: [
      {
        kind: 'stale_refresh',
        detail:
          'Last refresh was 12 hours ago, but cadence is daily. Refresh is still within tolerance but approaching the stale threshold.',
      },
    ],
  },

  // 6. Internal Research Database — tabular, restricted
  {
    id: 'src_01HXRESDB',
    slug: 'internal-research-db',
    name: 'Internal Research Database',
    family: 'tabular',
    status: 'published',
    owner: {
      team: 'research-analytics',
      contacts: ['research-analytics@example.com'],
      maintainers: [],
    },
    description_short:
      'Structured internal research dataset with experiment metadata, outcomes, and references.',
    description_long:
      'A Postgres-backed structured dataset of internal research experiments. Supports text-to-SQL retrieval for structured queries and vector ANN over the `description` column for semantic lookup.',
    intended_use:
      'For agents and analysts running structured queries against research experiment outcomes. Supports both typed filter queries and narrow natural-language-to-SQL workflows.',
    out_of_scope_use:
      'Not suitable for long-form retrieval — the dataset is tabular. Not a substitute for a published research paper.',
    known_limitations:
      'Text-to-SQL is constrained to a safe subset of the schema. Cross-table joins beyond the declared schema may not be supported.',
    domain_tags: ['research', 'internal'],
    languages: ['en'],
    citation_format: 'Internal Research DB, table {table}, row id {id}',
    created_at: daysAgo(200),
    updated_at: daysAgo(1),
    recipe: {
      version: 1,
      parser_kind: 'schema_introspection',
      chunker_kind: 'per_row',
      chunker_summary: 'per row on description column',
      embedding_model: 'nomic-embed-text-v1.5',
      embedding_dimension: 768,
      backend_kind: 'postgres',
      backend_location: 'research_analytics',
      raw_yaml: internalResearchDbRecipeYaml,
    },
    recipe_version_history: [
      {
        version: 1,
        active_since: daysAgo(200),
        author: 'user:research.admin',
        summary: 'Initial recipe.',
      },
    ],
    retrieval_default_pattern: 'structured_query',
    retrieval_supported_patterns: [
      {
        pattern: 'structured_query',
        parameters: { dialect: 'text_to_sql', max_rows: 200 },
      },
      {
        pattern: 'vector_ann',
        parameters: { top_k_default: 10, top_k_max: 50, column: 'description' },
      },
    ],
    active_physical_index: {
      id: 'pidx_01HXRESDB_v1',
      recipe_version: 1,
      backend_kind: 'postgres',
      location: 'research_analytics',
      built_at: daysAgo(1),
      document_count: 180412,
      health: 'ok',
    },
    size_summary: '180,412 rows · 14 tables',
    chunk_count_total: null,
    evals: [
      {
        llm: 'granite-3.3-8b-instruct',
        recall_at_5: 0.62,
        mrr: 0.55,
        rewrite_lift_at_5: null,
        source_system: 'native',
        eval_run_id: 'evr_resdb_granite_01',
        mlflow_run_id: null,
        run_at: daysAgo(3),
      },
      {
        llm: 'gpt-4o',
        recall_at_5: 0.71,
        mrr: 0.63,
        rewrite_lift_at_5: null,
        source_system: 'native',
        eval_run_id: 'evr_resdb_gpt4o_01',
        mlflow_run_id: null,
        run_at: daysAgo(3),
      },
    ],
    latency_p50_ms: 310,
    latency_p95_ms: 780,
    cost_estimate_hint: '~0.5k tokens/query',
    rewriter: {
      enabled: false,
      vocabulary_mappings: [],
      sample_queries: [],
      domain_notes: '',
      schema_hints: null,
      prompt_override_id: null,
      default_llm: 'granite-3.3-8b-instruct',
      llm_resolution: 'default',
      max_rewrites: 0,
      metadata_version: 1,
    },
    agent_write_policy: {
      allowed: false,
      scope_required: 'sources.write',
      allowed_groups: [],
      write_modes: [],
      write_validation: null,
    },
    sample_prompts: [
      {
        applies_to_llm_family: 'granite-3-*',
        role: 'system',
        text: 'You operate over an internal research tabular dataset. Formulate structured queries when the user asks for aggregates or filters. Cite table and row id.',
      },
      {
        applies_to_llm_family: 'gpt-4o',
        role: 'system',
        text: 'You answer questions over the internal research database. Use structured_query for filter/aggregate questions and vector_ann for semantic lookup. Always cite the table.',
      },
    ],
    lineage: {
      origin_kind: 'database_query',
      origin_config: {
        database: 'research_analytics',
        replica: 'warehouse-read',
      },
      refresh_cadence: 'daily',
      last_refresh_at: daysAgo(1),
      next_scheduled_refresh_at: hoursAgo(-24),
      ingestion_runs: [
        {
          id: 'run_01HXRESDB_latest',
          status: 'completed',
          started_at: daysAgo(1),
          duration_seconds: 2400,
          document_count: 180412,
          triggered_by: 'scheduler:refresh-cron',
        },
      ],
    },
    access: {
      visibility: 'restricted',
      allowed_groups: ['research-analysts', 'research-writers'],
    },
    health_flags: [],
  },

  // 7. OpenShift Knowledge Graph
  {
    id: 'src_01HXOPENSHIFTKG',
    slug: 'openshift-kg',
    name: 'OpenShift Knowledge Graph',
    family: 'graph',
    status: 'published',
    owner: {
      team: 'platform-docs',
      contacts: ['platform-docs@example.com'],
      maintainers: [],
    },
    description_short:
      'Knowledge graph of OpenShift concepts, components, and their relationships. Supports graph traversal queries.',
    description_long:
      'A knowledge graph built from the OpenShift documentation and architecture reference, capturing concepts (nodes) and their relationships (edges: depends_on, configured_by, part_of, etc.). Retrieval is hybrid: vector ANN finds entry nodes, then graph traversal walks two levels deep by default.',
    intended_use:
      'For agents answering questions about how OpenShift concepts relate. Useful for "what depends on X" or "how is Y configured" queries that benefit from relationship traversal.',
    out_of_scope_use:
      'Not a substitute for the full Red Hat product documentation corpus for detailed text content.',
    known_limitations:
      'Edge taxonomy is hand-curated and may be incomplete. Rewriter is not enabled.',
    domain_tags: ['openshift', 'infrastructure'],
    languages: ['en'],
    citation_format: 'OpenShift KG node {node_id}',
    created_at: daysAgo(160),
    updated_at: daysAgo(2),
    recipe: {
      version: 2,
      parser_kind: 'custom_graph',
      chunker_kind: 'node_text',
      chunker_summary: 'per-node text',
      embedding_model: 'nomic-embed-text-v1.5',
      embedding_dimension: 768,
      backend_kind: 'apache_age',
      backend_location: 'openshift_kg_v2',
      raw_yaml: openshiftKgRecipeYaml,
    },
    recipe_version_history: [
      {
        version: 2,
        active_since: daysAgo(30),
        author: 'user:graph.curator',
        summary: 'Added 8 new relationship types.',
      },
      {
        version: 1,
        active_since: daysAgo(160),
        author: 'user:graph.curator',
        summary: 'Initial recipe.',
      },
    ],
    retrieval_default_pattern: 'graph_traverse_from_seed',
    retrieval_supported_patterns: [
      {
        pattern: 'graph_traverse_from_seed',
        parameters: {
          seed_top_k_default: 5,
          traversal_depth_default: 2,
          max_total_nodes_default: 50,
        },
      },
      {
        pattern: 'vector_ann',
        parameters: { top_k_default: 10, top_k_max: 50 },
      },
    ],
    active_physical_index: {
      id: 'pidx_01HXOPENSHIFTKG_v2',
      recipe_version: 2,
      backend_kind: 'apache_age',
      location: 'openshift_kg_v2',
      built_at: daysAgo(2),
      document_count: 4821,
      health: 'ok',
    },
    size_summary: '4,821 nodes · 38,102 edges',
    chunk_count_total: 4821,
    evals: [
      {
        llm: 'gpt-4o',
        recall_at_5: 0.77,
        mrr: 0.7,
        rewrite_lift_at_5: null,
        source_system: 'native',
        eval_run_id: 'evr_os_kg_gpt4o_01',
        mlflow_run_id: null,
        run_at: daysAgo(3),
      },
    ],
    latency_p50_ms: 720,
    latency_p95_ms: 1640,
    cost_estimate_hint: '~1.0k tokens/query',
    rewriter: {
      enabled: false,
      vocabulary_mappings: [],
      sample_queries: [],
      domain_notes: '',
      schema_hints: null,
      prompt_override_id: null,
      default_llm: 'granite-3.3-8b-instruct',
      llm_resolution: 'default',
      max_rewrites: 0,
      metadata_version: 1,
    },
    agent_write_policy: {
      allowed: false,
      scope_required: 'sources.write',
      allowed_groups: [],
      write_modes: [],
      write_validation: null,
    },
    sample_prompts: [
      {
        applies_to_llm_family: 'gpt-4o',
        role: 'system',
        text: 'You answer OpenShift architecture questions using a knowledge graph. Results include related nodes via graph traversal; use the relationships to explain how concepts connect.',
      },
    ],
    lineage: {
      origin_kind: 'web_crawl',
      origin_config: {
        seed: 'https://docs.redhat.com/en/documentation/openshift_container_platform/',
        extract_entities: true,
        extract_relationships: true,
      },
      refresh_cadence: 'weekly',
      last_refresh_at: daysAgo(2),
      next_scheduled_refresh_at: daysAgo(-5),
      ingestion_runs: [
        {
          id: 'run_01HXOPENSHIFTKG_latest',
          status: 'completed',
          started_at: daysAgo(2),
          duration_seconds: 1820,
          document_count: 4821,
          triggered_by: 'scheduler:refresh-cron',
        },
      ],
    },
    access: {
      visibility: 'public',
      allowed_groups: [],
    },
    health_flags: [],
  },

  // 8. Clinical Trials Index — DRAFT
  {
    id: 'src_01HXCLINTRIALS',
    slug: 'clinical-trials-index',
    name: 'Clinical Trials Index',
    family: 'clinical_document',
    status: 'draft',
    owner: {
      team: 'clinical-informatics',
      contacts: ['alice.clinical@example.com'],
      maintainers: [],
    },
    description_short:
      '[DRAFT] Index of active clinical trials from ClinicalTrials.gov.',
    description_long:
      'Planned index of active clinical trials. Currently in draft state; no physical index has been built yet.',
    intended_use: '(Draft — intended use to be written.)',
    out_of_scope_use: '(Draft.)',
    known_limitations: '(Draft — no index yet.)',
    domain_tags: ['clinical', 'trials'],
    languages: ['en'],
    citation_format: null,
    created_at: daysAgo(14),
    updated_at: daysAgo(5),
    recipe: {
      version: 1,
      parser_kind: 'clinicaltrials_gov_api',
      chunker_kind: 'per_trial',
      chunker_summary: 'one chunk per trial',
      embedding_model: 'nomic-embed-text-v1.5',
      embedding_dimension: 768,
      backend_kind: 'pgvector',
      backend_location: 'idx_clinical_trials_index_v1',
      raw_yaml: clinicalTrialsIndexRecipeYaml,
    },
    recipe_version_history: [
      {
        version: 1,
        active_since: daysAgo(14),
        author: 'user:alice.clinical',
        summary: 'Initial recipe (draft).',
      },
    ],
    retrieval_default_pattern: 'vector_ann',
    retrieval_supported_patterns: [
      {
        pattern: 'vector_ann',
        parameters: { top_k_default: 10, top_k_max: 50 },
      },
    ],
    active_physical_index: null,
    size_summary: '(no index yet)',
    chunk_count_total: null,
    evals: [],
    latency_p50_ms: 0,
    latency_p95_ms: 0,
    cost_estimate_hint: '—',
    rewriter: {
      enabled: false,
      vocabulary_mappings: [],
      sample_queries: [],
      domain_notes: '',
      schema_hints: null,
      prompt_override_id: null,
      default_llm: 'granite-3.3-8b-instruct',
      llm_resolution: 'default',
      max_rewrites: 0,
      metadata_version: 1,
    },
    agent_write_policy: {
      allowed: false,
      scope_required: 'sources.write',
      allowed_groups: [],
      write_modes: [],
      write_validation: null,
    },
    sample_prompts: [],
    lineage: {
      origin_kind: 'external_api',
      origin_config: {
        api: 'clinicaltrials.gov',
        filter: 'active trials only',
      },
      refresh_cadence: 'daily',
      last_refresh_at: null,
      next_scheduled_refresh_at: null,
      ingestion_runs: [],
    },
    access: {
      visibility: 'restricted',
      allowed_groups: ['clinical-informatics'],
    },
    health_flags: [],
  },
];

// ---------------------------------------------------------------------------
// Recent catalog changes audit feed (for the admin page)
// ---------------------------------------------------------------------------

export const MOCK_AUDIT_RECORDS: AuditRecord[] = [
  {
    occurred_at: hoursAgo(2),
    action: 'source.refresh.completed',
    actor_sub: 'scheduler:refresh-cron',
    source_slug: 'rh-product-docs',
    summary: 'Refresh run completed: 184,302 documents (+382 since last run).',
  },
  {
    occurred_at: hoursAgo(2),
    action: 'source.refresh.completed',
    actor_sub: 'scheduler:refresh-cron',
    source_slug: 'va-clinical-guidelines',
    summary: 'Refresh run completed: 18,402 documents (+17).',
  },
  {
    occurred_at: hoursAgo(6),
    action: 'source.refresh.completed',
    actor_sub: 'scheduler:refresh-cron',
    source_slug: 'wikipedia-ai',
    summary: 'Daily refresh completed.',
  },
  {
    occurred_at: hoursAgo(12),
    action: 'source.write.append',
    actor_sub: 'agent:spiffe://cluster.local/ns/clinical/sa/note-enricher',
    source_slug: 'clinical-notes-staging',
    summary: '3 notes appended via append mode.',
  },
  {
    occurred_at: daysAgo(1),
    action: 'source.recipe.bump',
    actor_sub: 'user:alice.docs',
    source_slug: 'rh-product-docs',
    summary: 'Recipe v2 → v3 (embedding model upgrade).',
  },
  {
    occurred_at: daysAgo(2),
    action: 'source.rewriter_metadata.edit',
    actor_sub: 'user:alice.clinical',
    source_slug: 'va-clinical-guidelines',
    summary: 'Added 4 vocabulary mappings (dyspnea, pyrexia, CT, MRI).',
  },
  {
    occurred_at: daysAgo(4),
    action: 'source.index.health_change',
    actor_sub: 'system:health_checker',
    source_slug: 'rh-ai-americas-code',
    summary: 'Active physical index transitioned ok → degraded.',
  },
  {
    occurred_at: daysAgo(5),
    action: 'source.publish',
    actor_sub: 'user:alice.clinical',
    source_slug: 'clinical-notes-staging',
    summary: 'Published after review. Agent writes enabled for clinical-writers.',
  },
];
