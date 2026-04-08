// Types mirror the catalog data model from docs/catalog.md and
// docs/ui-card-data.md. This is a mock shape used by the stage-2 UI only.

export type SourceFamily =
  | 'document'
  | 'clinical_document'
  | 'code'
  | 'tabular'
  | 'graph'
  | 'external';

export type SourceStatus = 'draft' | 'curated' | 'published' | 'retired';

export type Visibility = 'public' | 'restricted';

export type RetrievalPattern =
  | 'vector_ann'
  | 'vector_with_filters'
  | 'graph_traverse_from_seed'
  | 'structured_query'
  | 'hybrid'
  | 'passthrough_external';

export type WriteMode = 'append' | 'upsert' | 'annotate';

export type PhysicalIndexHealth = 'ok' | 'degraded' | 'failed';

export type EvalSourceSystem = 'llamastack' | 'native' | 'imported';

export interface Owner {
  team: string;
  contacts: string[];
  maintainers: string[];
}

export interface Recipe {
  version: number;
  parser_kind: string;
  chunker_kind: string;
  chunker_summary: string;
  embedding_model: string;
  embedding_dimension: number;
  backend_kind: string;
  backend_location: string;
  raw_yaml: string;
}

export interface RecipeVersion {
  version: number;
  active_since: string; // ISO
  author: string;
  summary: string;
}

export interface RetrievalPatternConfig {
  pattern: RetrievalPattern;
  parameters: Record<string, string | number>;
}

export interface EvalResult {
  llm: string;
  recall_at_5: number;
  mrr: number;
  rewrite_lift_at_5: number | null;
  source_system: EvalSourceSystem;
  eval_run_id: string;
  mlflow_run_id: string | null;
  run_at: string;
}

export interface RewriterMetadata {
  enabled: boolean;
  shared_template_pointer?: string;
  shared_template_version?: number;
  vocabulary_mappings: Array<{
    lay_term: string;
    canonical_term: string;
    qualifiers?: string;
  }>;
  sample_queries: Array<{
    raw_query: string;
    good_rewrites: string[];
  }>;
  domain_notes: string;
  schema_hints: Record<string, unknown> | null;
  prompt_override_id: string | null;
  default_llm: string;
  llm_resolution: 'default' | 'caller_optional' | 'caller_required';
  max_rewrites: number;
  metadata_version: number;
}

export interface AgentWritePolicy {
  allowed: boolean;
  scope_required: string;
  allowed_groups: string[];
  write_modes: WriteMode[];
  write_validation: { schema_id: string; require_provenance: boolean } | null;
  recent_write_activity_summary?: string;
}

export interface SamplePrompt {
  applies_to_llm_family: string;
  role: 'system' | 'user';
  text: string;
}

export interface PhysicalIndex {
  id: string;
  recipe_version: number;
  backend_kind: string;
  location: string;
  built_at: string | null;
  document_count: number;
  health: PhysicalIndexHealth;
}

export interface IngestionRun {
  id: string;
  status: 'completed' | 'failed' | 'running';
  started_at: string;
  duration_seconds: number;
  document_count: number;
  triggered_by: string;
}

export interface Lineage {
  origin_kind:
    | 'web_crawl'
    | 'git_clone'
    | 'database_query'
    | 's3_sync'
    | 'file_upload'
    | 'external_api';
  origin_config: Record<string, unknown>;
  refresh_cadence: string;
  last_refresh_at: string | null;
  next_scheduled_refresh_at: string | null;
  ingestion_runs: IngestionRun[];
}

export interface AccessPolicy {
  visibility: Visibility;
  allowed_groups: string[];
}

export interface AuditRecord {
  occurred_at: string;
  action: string;
  actor_sub: string;
  source_slug: string;
  summary: string;
}

export interface Source {
  id: string;
  slug: string;
  name: string;
  family: SourceFamily;
  status: SourceStatus;
  owner: Owner;
  description_short: string;
  description_long: string;
  intended_use: string;
  out_of_scope_use: string;
  known_limitations: string;
  domain_tags: string[];
  languages: string[];
  citation_format: string | null;
  created_at: string;
  updated_at: string;
  recipe: Recipe;
  recipe_version_history: RecipeVersion[];
  retrieval_default_pattern: RetrievalPattern;
  retrieval_supported_patterns: RetrievalPatternConfig[];
  active_physical_index: PhysicalIndex | null;
  size_summary: string;
  chunk_count_total: number | null;
  evals: EvalResult[];
  latency_p50_ms: number;
  latency_p95_ms: number;
  cost_estimate_hint: string;
  rewriter: RewriterMetadata;
  agent_write_policy: AgentWritePolicy;
  sample_prompts: SamplePrompt[];
  lineage: Lineage;
  access: AccessPolicy;
  health_flags: Array<{ kind: string; detail: string }>;
}

// Persona types
export type PersonaId =
  | 'platform_admin'
  | 'source_owner_clinical'
  | 'agent_developer'
  | 'agent_developer_no_access';

export interface Persona {
  id: PersonaId;
  display_name: string;
  identity_kind: 'human' | 'agent';
  identity_sub: string;
  identity_groups: string[];
  scopes: string[];
  owner_of_teams: string[];
}

export interface BestScoreProjection {
  llm: string;
  value: number;
  mrr: number;
  rewrite_lift: number | null;
  llms_evaluated: number;
}
