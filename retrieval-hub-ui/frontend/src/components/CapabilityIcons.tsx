import { Flex, FlexItem, Tooltip } from '@patternfly/react-core';
import {
  ArrowRightIcon,
  ConnectedIcon,
  FilterIcon,
  MagicIcon,
  PencilAltIcon,
  ProjectDiagramIcon,
  SearchIcon,
  TableIcon,
} from '@patternfly/react-icons';
import type { RetrievalPattern, Source } from '../types/source';
import { patternDisplayName } from '../utils/formatters';

interface CapabilityIconsProps {
  source: Source;
}

function patternIcon(pattern: RetrievalPattern) {
  switch (pattern) {
    case 'vector_ann':
      return <SearchIcon />;
    case 'vector_with_filters':
      return <FilterIcon />;
    case 'graph_traverse_from_seed':
      return <ProjectDiagramIcon />;
    case 'structured_query':
      return <TableIcon />;
    case 'hybrid':
      return <ConnectedIcon />;
    case 'passthrough_external':
      return <ArrowRightIcon />;
    default:
      return <SearchIcon />;
  }
}

function patternDescription(pattern: RetrievalPattern): React.ReactNode {
  switch (pattern) {
    case 'vector_ann':
      return (
        <>
          <strong>Vector search (ANN)</strong>
          <div>
            Semantic similarity search using approximate nearest neighbors over
            an embedding index. Best for "find documents like this question" workflows.
          </div>
        </>
      );
    case 'vector_with_filters':
      return (
        <>
          <strong>Vector search with filters</strong>
          <div>
            Vector ANN combined with structured filters (date range, document
            type, language, etc.). Best when you need semantic similarity within
            a specific slice of the corpus.
          </div>
        </>
      );
    case 'graph_traverse_from_seed':
      return (
        <>
          <strong>Graph traversal from seed</strong>
          <div>
            Vector search finds entry nodes, then graph traversal walks the graph
            N levels deep and returns chunks plus their relationships as one
            response. Best for knowledge-graph questions where relationships matter.
          </div>
        </>
      );
    case 'structured_query':
      return (
        <>
          <strong>Structured query (text-to-SQL)</strong>
          <div>
            Typed filter queries and text-to-SQL against a structured schema.
            Best for numerical filtering, aggregations, and reasoning over tables.
          </div>
        </>
      );
    case 'hybrid':
      return (
        <>
          <strong>Hybrid retrieval</strong>
          <div>
            Composition of two or more patterns with an explicit merge/rerank
            policy. Used when a single pattern is insufficient.
          </div>
        </>
      );
    case 'passthrough_external':
      return (
        <>
          <strong>External passthrough</strong>
          <div>
            The query is forwarded to an external retrieval system using its
            native API and projected into retrieval-hub's result shape.
          </div>
        </>
      );
    default:
      return <span>{patternDisplayName(pattern)}</span>;
  }
}

export default function CapabilityIcons({ source }: CapabilityIconsProps) {
  return (
    <Flex spaceItems={{ default: 'spaceItemsSm' }} flexWrap={{ default: 'wrap' }}>
      {source.rewriter?.enabled && (
        <FlexItem>
          <Tooltip
            content={
              <>
                <strong>Query rewriter enabled</strong>
                <div>
                  This source has a per-source rewriter that translates raw user
                  questions into corpus-vocabulary queries before retrieval. See
                  the Rewriter tab for vocabulary mappings and sample queries.
                </div>
              </>
            }
          >
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.25rem',
                padding: '2px 6px',
                borderRadius: '4px',
                background: 'var(--pf-v5-global--palette--purple-50)',
                color: 'var(--pf-v5-global--palette--purple-700)',
                fontSize: '0.75rem',
                fontWeight: 600,
                cursor: 'help',
              }}
            >
              <MagicIcon /> rewriter
            </span>
          </Tooltip>
        </FlexItem>
      )}
      {source.agent_write_policy.allowed && (
        <FlexItem>
          <Tooltip
            content={
              <>
                <strong>Agent writes allowed</strong>
                <div>
                  Agents with the right scope can write to this source. Modes:{' '}
                  {source.agent_write_policy.write_modes.join(', ')}.
                </div>
              </>
            }
          >
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.25rem',
                padding: '2px 6px',
                borderRadius: '4px',
                background: 'var(--pf-v5-global--palette--orange-50)',
                color: 'var(--pf-v5-global--palette--orange-700)',
                fontSize: '0.75rem',
                fontWeight: 600,
                cursor: 'help',
              }}
            >
              <PencilAltIcon /> writable
            </span>
          </Tooltip>
        </FlexItem>
      )}
      {(source.retrieval_supported_patterns ?? []).slice(0, 3).map((p) => (
        <FlexItem key={p.pattern}>
          <Tooltip content={patternDescription(p.pattern)}>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.25rem',
                padding: '2px 6px',
                borderRadius: '4px',
                background: 'var(--pf-v5-global--BackgroundColor--200)',
                color: 'var(--pf-v5-global--Color--100)',
                fontSize: '0.75rem',
                cursor: 'help',
              }}
            >
              {patternIcon(p.pattern)} {patternDisplayName(p.pattern)}
            </span>
          </Tooltip>
        </FlexItem>
      ))}
    </Flex>
  );
}
