import type { Persona, Source, WriteMode, BestScoreProjection } from '../types/source';

/**
 * Can the persona query this source?
 *
 * Mirrors the intended `can_access` semantics from docs/catalog.md:
 * - Public sources: always accessible.
 * - Restricted sources: persona groups must intersect access.allowed_groups.
 * - Platform admins always see everything.
 * - Owners of the source's team see their owned sources.
 */
export function canAccess(persona: Persona, source: Source): boolean {
  if (persona.scopes.includes('admin.read')) return true;

  if (persona.owner_of_teams.includes(source.owner.team)) return true;

  if (source.access.visibility === 'public') return true;

  return persona.identity_groups.some((g) =>
    source.access.allowed_groups.includes(g),
  );
}

/**
 * Can the persona perform a write of the given mode against this source?
 * Requires: policy.allowed, scope, group intersection, and mode allowed.
 */
export function canWrite(
  persona: Persona,
  source: Source,
  mode: WriteMode,
): boolean {
  const policy = source.agent_write_policy;
  if (!policy.allowed) return false;
  if (!persona.scopes.includes(policy.scope_required)) return false;
  if (!policy.write_modes.includes(mode)) return false;
  if (policy.allowed_groups.length === 0) return true;
  return persona.identity_groups.some((g) => policy.allowed_groups.includes(g));
}

/**
 * Which sources should this persona see in the catalog grid by default?
 *
 * Hides sources in draft/retired/curated states for non-admins. Admins see
 * everything. Owners see owned sources in any status, plus published public
 * sources as the browse experience.
 */
export function visibleSourcesForCatalog(
  persona: Persona,
  sources: Source[],
): Source[] {
  const isAdmin = persona.scopes.includes('admin.read');
  return sources.filter((s) => {
    // Drafts and retired only visible to admins or the owning team.
    if (s.status !== 'published') {
      if (isAdmin) return true;
      if (persona.owner_of_teams.includes(s.owner.team)) return true;
      return false;
    }
    // Published: show even if access is restricted — detail page shows
    // the access-required banner when the user can't actually query.
    return true;
  });
}

/**
 * Source-owner admin view: sources this persona owns or maintains.
 */
export function ownedSources(persona: Persona, sources: Source[]): Source[] {
  return sources.filter((s) => persona.owner_of_teams.includes(s.owner.team));
}

/**
 * Compute the composite best-score projection for the grid card.
 * Returns null if there are no eval results yet.
 */
export function bestScore(source: Source): BestScoreProjection | null {
  if (source.evals.length === 0) return null;
  const best = source.evals.reduce((acc, cur) =>
    cur.recall_at_5 > acc.recall_at_5 ? cur : acc,
  );
  return {
    llm: best.llm,
    value: best.recall_at_5,
    mrr: best.mrr,
    rewrite_lift: best.rewrite_lift_at_5,
    llms_evaluated: source.evals.length,
  };
}

/**
 * Does the source currently have any health flags or a non-ok physical index?
 */
export function healthIsProblematic(source: Source): boolean {
  if (source.health_flags.length > 0) return true;
  const h = source.active_physical_index?.health;
  return h === 'degraded' || h === 'failed';
}

/**
 * Which sample prompt family should we copy by default?
 *
 * Without user preferences, return the first available sample prompt, or
 * fall back to the `generic` family if present.
 */
export function defaultSamplePromptText(source: Source): string | null {
  if (source.sample_prompts.length === 0) return null;
  const generic = source.sample_prompts.find(
    (p) => p.applies_to_llm_family === 'generic',
  );
  return (generic ?? source.sample_prompts[0]).text;
}
