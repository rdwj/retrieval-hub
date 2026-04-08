import { useNavigate } from 'react-router-dom';
import {
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  CardTitle,
  Flex,
  FlexItem,
  Label,
  Popover,
  Stack,
  StackItem,
  Tooltip,
} from '@patternfly/react-core';
import {
  ClockIcon,
  CubesIcon,
  LockIcon,
  OutlinedQuestionCircleIcon,
  UsersIcon,
} from '@patternfly/react-icons';

import type { Source, SourceFamily } from '../types/source';
import { familyDisplayName, formatNumber, relativeTime } from '../utils/formatters';
import BestScoreDisplay from './BestScoreDisplay';
import CapabilityIcons from './CapabilityIcons';
import DomainTags from './DomainTags';
import FamilyIcon from './FamilyIcon';

interface SourceCardProps {
  source: Source;
}

// Short tooltip text per family — explains what the family means for how you'd use it.
function familyTooltip(family: SourceFamily): string {
  switch (family) {
    case 'document':
      return 'Document source — text or text-extracted-from-binary content, chunked and embedded for semantic retrieval. Default pattern: vector search.';
    case 'clinical_document':
      return 'Clinical document source — a document source with domain-aware parsing and a rewriter that translates lay language into clinical vocabulary.';
    case 'code':
      return 'Code source — source code with AST-aware chunking and code-tuned embeddings. Retrieval preserves file path, symbol name, and surrounding context.';
    case 'tabular':
      return 'Tabular source — structured data with text-to-SQL and typed filter retrieval. Supports numerical filtering, aggregation, and reasoning over tables.';
    case 'graph':
      return 'Graph source — entities and relationships with traversal-based retrieval. Returns nodes plus their relationships as one response.';
    case 'external':
      return 'External source — a connection to a retrieval system retrieval-hub does not own. The adapter wraps the external system\'s native query API.';
    default:
      return '';
  }
}

// Small muted label used above each labeled row on the card.
function RowLabel({
  children,
  helpContent,
  helpHeader,
}: {
  children: React.ReactNode;
  helpContent?: React.ReactNode;
  helpHeader?: React.ReactNode;
}) {
  return (
    <div
      style={{
        fontSize: '0.7rem',
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
        color: 'var(--pf-v5-global--Color--200)',
        fontWeight: 600,
        marginBottom: '0.15rem',
        display: 'flex',
        alignItems: 'center',
        gap: '0.25rem',
      }}
    >
      {children}
      {helpContent && (
        <Popover headerContent={helpHeader} bodyContent={helpContent}>
          <Button
            variant="plain"
            aria-label="More info"
            style={{
              padding: 0,
              margin: 0,
              minHeight: 0,
              lineHeight: 1,
              color: 'var(--pf-v5-global--Color--300)',
            }}
            // Stop the click from bubbling up to the clickable card
            onClick={(e) => e.stopPropagation()}
          >
            <OutlinedQuestionCircleIcon style={{ fontSize: '0.8rem' }} />
          </Button>
        </Popover>
      )}
    </div>
  );
}

export default function SourceCard({ source }: SourceCardProps) {
  const navigate = useNavigate();

  const statusColor: 'blue' | 'green' | 'orange' | 'grey' =
    source.status === 'published'
      ? 'green'
      : source.status === 'draft'
        ? 'orange'
        : source.status === 'curated'
          ? 'blue'
          : 'grey';

  return (
    <Card
      isClickable
      isCompact
      onClick={() => navigate(`/sources/${source.slug}`)}
      style={{ height: '100%' }}
    >
      <CardHeader>
        <Flex
          alignItems={{ default: 'alignItemsCenter' }}
          spaceItems={{ default: 'spaceItemsSm' }}
          flexWrap={{ default: 'wrap' }}
        >
          <FlexItem>
            <FamilyIcon family={source.family} size="lg" />
          </FlexItem>
          <FlexItem flex={{ default: 'flex_1' }}>
            <CardTitle style={{ fontSize: '1.05rem', lineHeight: 1.2 }}>
              {source.name}
            </CardTitle>
          </FlexItem>
        </Flex>
        <Flex
          style={{ marginTop: '0.4rem' }}
          spaceItems={{ default: 'spaceItemsXs' }}
          flexWrap={{ default: 'wrap' }}
        >
          <FlexItem>
            <Tooltip content={familyTooltip(source.family)}>
              <Label isCompact color="grey">
                {familyDisplayName(source.family)}
              </Label>
            </Tooltip>
          </FlexItem>
          <FlexItem>
            <Tooltip
              content={
                source.status === 'published'
                  ? 'Published — visible to agents, listed in the catalog, has at least one eval run.'
                  : source.status === 'draft'
                    ? 'Draft — source exists in the catalog but has no physical index yet. Not visible to agents.'
                    : source.status === 'curated'
                      ? 'Curated — has a physical index and the owner is iterating. Not yet agent-visible.'
                      : 'Retired — no longer maintained. Hidden from default catalog views.'
              }
            >
              <Label isCompact color={statusColor}>
                {source.status}
              </Label>
            </Tooltip>
          </FlexItem>
          <FlexItem>
            <Tooltip
              content={
                source.access.visibility === 'public'
                  ? 'Public — any authenticated caller can query this source.'
                  : 'Restricted — access is limited to specific identity groups. See the Access tab.'
              }
            >
              <Label
                isCompact
                color={source.access.visibility === 'public' ? 'blue' : 'orange'}
                icon={source.access.visibility === 'restricted' ? <LockIcon /> : undefined}
              >
                {source.access.visibility}
              </Label>
            </Tooltip>
          </FlexItem>
        </Flex>
      </CardHeader>
      <CardBody>
        <Stack hasGutter>
          <StackItem>
            <p
              style={{
                display: '-webkit-box',
                WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
                fontSize: '0.875rem',
                margin: 0,
                color: 'var(--pf-v5-global--Color--100)',
                minHeight: '2.5em',
              }}
            >
              {source.description_short}
            </p>
          </StackItem>
          <StackItem>
            <DomainTags
              tags={source.domain_tags}
              filterAgainst={{
                family: source.family,
                status: source.status,
                visibility: source.access.visibility,
              }}
            />
          </StackItem>
          <StackItem>
            <RowLabel
              helpHeader="Best eval score"
              helpContent={
                <div style={{ maxWidth: '26rem' }}>
                  <p>
                    The highest <strong>Recall@5</strong> score across every LLM
                    this source has been evaluated against. Click{' '}
                    <em>"N LLMs evaluated"</em> below to see the full per-LLM table.
                  </p>
                  <p>
                    <strong>Recall@5</strong> is the fraction of test queries
                    where at least one relevant document appears in the top 5
                    retrieved results. Higher is better (1.0 = perfect).
                  </p>
                  <p style={{ marginBottom: 0 }}>
                    If the rewriter is enabled, the lift delta (
                    <code>+0.XX with rewriter</code>) shows how much the rewriter
                    improved Recall@5 on the best LLM.
                  </p>
                </div>
              }
            >
              Best eval score
            </RowLabel>
            <BestScoreDisplay source={source} />
          </StackItem>
          <StackItem>
            <RowLabel
              helpHeader="Recipe"
              helpContent={
                <div style={{ maxWidth: '26rem' }}>
                  <p>
                    A <strong>recipe</strong> is the specification of how this
                    source was built: the parser that extracted content, the
                    chunker that split it into retrievable units, the embedding
                    model that vectorized it (if any), and the storage backend
                    where the index lives.
                  </p>
                  <p style={{ marginBottom: 0 }}>
                    Recipes are versioned. Changing a recipe creates a new
                    version and a new physical index, so sources can A/B recipe
                    versions via eval scores. See the Recipe tab for the full
                    YAML and version history.
                  </p>
                </div>
              }
            >
              Recipe
            </RowLabel>
            <div
              style={{
                fontSize: '0.8rem',
                color: 'var(--pf-v5-global--Color--200)',
                lineHeight: 1.4,
              }}
            >
              <Tooltip content="Embedding model: the model used to vectorize source content so similarity search can find related documents. Different embedding models have different dimensionalities and semantic strengths.">
                <span
                  style={{
                    fontFamily: 'var(--pf-v5-global--FontFamily--monospace)',
                    cursor: 'help',
                    borderBottom: '1px dotted var(--pf-v5-global--Color--300)',
                  }}
                >
                  {source.recipe.embedding_model}
                </span>
              </Tooltip>
              <div>
                <Tooltip content="Chunking strategy: how this source is split into retrievable units. Varies by family — documents use token or semantic boundaries; tabular sources use per-row chunking; code sources use AST-aware symbol chunking.">
                  <span
                    style={{
                      cursor: 'help',
                      borderBottom: '1px dotted var(--pf-v5-global--Color--300)',
                    }}
                  >
                    {source.recipe.chunker_summary}
                  </span>
                </Tooltip>
                {' · '}
                <Tooltip content="Storage backend: where the indexed data lives. `pgvector` adds vector search to Postgres; `postgres` is plain SQL tables for tabular sources; `apache_age` is a graph store; others are backend-specific.">
                  <span
                    style={{
                      cursor: 'help',
                      borderBottom: '1px dotted var(--pf-v5-global--Color--300)',
                    }}
                  >
                    {source.recipe.backend_kind}
                  </span>
                </Tooltip>
              </div>
            </div>
          </StackItem>
          <StackItem>
            <RowLabel>Size</RowLabel>
            <Tooltip content="The total amount of content in this source, in family-appropriate units (documents, rows, symbols, nodes).">
              <span
                style={{
                  fontSize: '0.8rem',
                  color: 'var(--pf-v5-global--Color--200)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  cursor: 'help',
                }}
              >
                <CubesIcon /> {source.size_summary}
              </span>
            </Tooltip>
          </StackItem>
          <StackItem>
            <RowLabel>Updated</RowLabel>
            <Tooltip
              content={`Last refreshed from the source's origin. Refresh cadence: ${source.lineage.refresh_cadence}.`}
            >
              <span
                style={{
                  fontSize: '0.8rem',
                  color: 'var(--pf-v5-global--Color--200)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  cursor: 'help',
                }}
              >
                <ClockIcon /> Refreshed {relativeTime(source.lineage.last_refresh_at)}
              </span>
            </Tooltip>
          </StackItem>
          <StackItem>
            <RowLabel
              helpHeader="Supported retrieval patterns"
              helpContent={
                <div style={{ maxWidth: '26rem' }}>
                  <p>
                    Retrieval patterns are the named query shapes this source's
                    adapter can answer. Hover each pill for a description.
                  </p>
                  <p style={{ marginBottom: 0 }}>
                    Agents don't have to pick a pattern — the default pattern
                    runs automatically. Advanced agents can request a specific
                    pattern and pass pattern-specific parameters. See the
                    Retrieval tab on the detail page for parameters and defaults.
                  </p>
                </div>
              }
            >
              Supports
            </RowLabel>
            <CapabilityIcons source={source} />
          </StackItem>
        </Stack>
      </CardBody>
      <CardFooter>
        <span style={{ fontSize: '0.75rem', color: 'var(--pf-v5-global--Color--200)' }}>
          <UsersIcon /> Owned by {source.owner.team} ·{' '}
          {formatNumber(source.recipe.version)
            ? `recipe v${source.recipe.version}`
            : ''}
        </span>
      </CardFooter>
    </Card>
  );
}
