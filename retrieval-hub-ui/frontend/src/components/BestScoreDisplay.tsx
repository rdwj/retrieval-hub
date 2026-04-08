import {
  Button,
  Popover,
  Stack,
  StackItem,
  Tooltip,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';

import type { Source } from '../types/source';
import { bestScore } from '../utils/accessCheck';
import { formatScore, formatSignedDelta } from '../utils/formatters';

interface BestScoreDisplayProps {
  source: Source;
}

export default function BestScoreDisplay({ source }: BestScoreDisplayProps) {
  const best = bestScore(source);
  if (!best) {
    return (
      <div style={{ minHeight: '3.5rem' }}>
        <span style={{ fontSize: '0.875rem', color: 'var(--pf-v5-global--Color--200)' }}>
          No eval runs yet
        </span>
      </div>
    );
  }

  const showLift = source.rewriter.enabled && best.rewrite_lift !== null;

  return (
    <Stack>
      <StackItem>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem' }}>
          <span
            style={{
              fontSize: '1.6rem',
              fontWeight: 700,
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {formatScore(best.value)}
          </span>
          <span
            style={{
              fontSize: '0.85rem',
              color: 'var(--pf-v5-global--Color--200)',
            }}
          >
            <Tooltip
              content={
                <>
                  <strong>Recall @ 5</strong>
                  <div>
                    The fraction of test queries where at least one relevant
                    document appears in the top 5 retrieved results. Higher is
                    better (1.0 = perfect recall).
                  </div>
                </>
              }
            >
              <span style={{ cursor: 'help', borderBottom: '1px dotted' }}>R@5</span>
            </Tooltip>{' '}
            · {best.llm}
          </span>
        </div>
      </StackItem>
      {showLift && (
        <StackItem>
          <span
            style={{
              fontSize: '0.85rem',
              color: 'var(--pf-v5-global--success-color--100)',
              fontWeight: 600,
            }}
          >
            {formatSignedDelta(best.rewrite_lift)} with rewriter
          </span>
        </StackItem>
      )}
      <StackItem>
        <Popover
          headerContent="All evaluated LLMs"
          bodyContent={
            <Table variant="compact" aria-label="All evaluated LLMs">
              <Thead>
                <Tr>
                  <Th>LLM</Th>
                  <Th>R@5</Th>
                  <Th>MRR</Th>
                  <Th>Rewrite lift</Th>
                  <Th>Backend</Th>
                </Tr>
              </Thead>
              <Tbody>
                {source.evals.map((e) => (
                  <Tr key={e.eval_run_id}>
                    <Td>{e.llm}</Td>
                    <Td>{formatScore(e.recall_at_5)}</Td>
                    <Td>{formatScore(e.mrr)}</Td>
                    <Td>
                      {e.rewrite_lift_at_5 === null
                        ? '—'
                        : formatSignedDelta(e.rewrite_lift_at_5)}
                    </Td>
                    <Td>{e.source_system}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          }
        >
          <Button variant="link" isInline style={{ fontSize: '0.8rem' }}>
            {best.llms_evaluated} LLM{best.llms_evaluated === 1 ? '' : 's'} evaluated
          </Button>
        </Popover>
      </StackItem>
    </Stack>
  );
}
