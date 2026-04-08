import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Breadcrumb,
  BreadcrumbItem,
  Button,
  Card,
  CardBody,
  CardTitle,
  Checkbox,
  EmptyState,
  EmptyStateBody,
  EmptyStateVariant,
  Form,
  FormGroup,
  Label,
  PageSection,
  Spinner,
  Stack,
  StackItem,
  TextArea,
  TextInput,
  Title,
} from '@patternfly/react-core';

import { MOCK_SOURCES } from '../data/mockSources';
import type { Source } from '../types/source';
import { formatScore } from '../utils/formatters';

interface MockHit {
  id: string;
  text: string;
  score: number;
  source_uri: string;
  physical_index_id: string;
  recipe_version: number;
}

export default function PlaygroundPage() {
  const { slug } = useParams<{ slug: string }>();
  const source = MOCK_SOURCES.find((s) => s.slug === slug);

  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState('10');
  const [useRewrite, setUseRewrite] = useState(
    source?.rewriter.enabled ?? false,
  );
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<MockHit[] | null>(null);
  const [rewrites, setRewrites] = useState<string[] | null>(null);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);

  if (!source) {
    return (
      <PageSection>
        <EmptyState variant={EmptyStateVariant.lg}>
          <Title headingLevel="h2">Source not found</Title>
          <EmptyStateBody>
            No source with slug <code>{slug}</code>.{' '}
            <Link to="/catalog">Back to catalog</Link>.
          </EmptyStateBody>
        </EmptyState>
      </PageSection>
    );
  }

  const runQuery = () => {
    if (!query.trim()) return;
    setRunning(true);
    setResults(null);
    setRewrites(null);
    setElapsedMs(null);
    setTimeout(() => {
      setResults(makeMockHits(source, parseInt(topK, 10) || 10));
      if (useRewrite && source.rewriter.enabled) {
        setRewrites(makeMockRewrites(source, query));
      }
      setElapsedMs(824);
      setRunning(false);
    }, 500);
  };

  return (
    <>
      <PageSection variant="light">
        <Breadcrumb>
          <BreadcrumbItem
            to="/catalog"
            render={() => <Link to="/catalog">Catalog</Link>}
          />
          <BreadcrumbItem
            to={`/sources/${source.slug}`}
            render={() => (
              <Link to={`/sources/${source.slug}`}>{source.name}</Link>
            )}
          />
          <BreadcrumbItem isActive>Playground</BreadcrumbItem>
        </Breadcrumb>
        <Title headingLevel="h1" style={{ marginTop: '1rem' }}>
          Playground — {source.name}
        </Title>
        <p
          style={{
            marginTop: '0.25rem',
            color: 'var(--pf-v5-global--Color--200)',
            fontSize: '0.9rem',
          }}
        >
          Issue a mock query against this source. Results are fabricated for
          the mockup; no real retrieval runs.
        </p>
      </PageSection>
      <PageSection>
        <Card>
          <CardTitle>Query</CardTitle>
          <CardBody>
            <Form>
              <FormGroup label="Query" fieldId="query" isRequired>
                <TextArea
                  id="query"
                  value={query}
                  onChange={(_e, v) => setQuery(v)}
                  rows={4}
                  placeholder="What are the first-line treatments for hypertension?"
                />
              </FormGroup>
              <FormGroup label="top_k" fieldId="top-k">
                <TextInput
                  id="top-k"
                  type="number"
                  value={topK}
                  onChange={(_e, v) => setTopK(v)}
                  style={{ maxWidth: '8rem' }}
                />
              </FormGroup>
              {source.rewriter.enabled && (
                <FormGroup fieldId="use-rewrite">
                  <Checkbox
                    id="use-rewrite"
                    label="Use rewriter"
                    isChecked={useRewrite}
                    onChange={(_e, checked) => setUseRewrite(checked)}
                  />
                </FormGroup>
              )}
              <Button
                variant="primary"
                onClick={runQuery}
                isDisabled={running || !query.trim()}
              >
                {running ? (
                  <>
                    <Spinner size="sm" /> Running…
                  </>
                ) : (
                  'Run query'
                )}
              </Button>
            </Form>
          </CardBody>
        </Card>
      </PageSection>
      {results && (
        <PageSection>
          <Stack hasGutter>
            {rewrites && (
              <StackItem>
                <Card>
                  <CardTitle>Rewrites used</CardTitle>
                  <CardBody>
                    <ol>
                      {rewrites.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ol>
                  </CardBody>
                </Card>
              </StackItem>
            )}
            <StackItem>
              <Card>
                <CardTitle>Results ({results.length})</CardTitle>
                <CardBody>
                  <Stack hasGutter>
                    {results.map((hit) => (
                      <StackItem key={hit.id}>
                        <Card isCompact isFlat isFullHeight>
                          <CardBody>
                            <div
                              style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                fontSize: '0.8rem',
                                color: 'var(--pf-v5-global--Color--200)',
                                marginBottom: '0.25rem',
                              }}
                            >
                              <span>
                                <Label isCompact color="blue">
                                  score {formatScore(hit.score)}
                                </Label>{' '}
                                <code>{hit.source_uri}</code>
                              </span>
                            </div>
                            <p style={{ margin: 0 }}>{hit.text}</p>
                            <div
                              style={{
                                fontSize: '0.7rem',
                                color:
                                  'var(--pf-v5-global--Color--200)',
                                marginTop: '0.5rem',
                                fontFamily:
                                  'var(--pf-v5-global--FontFamily--monospace)',
                              }}
                            >
                              {hit.physical_index_id} · recipe v
                              {hit.recipe_version}
                            </div>
                          </CardBody>
                        </Card>
                      </StackItem>
                    ))}
                  </Stack>
                  <div
                    style={{
                      marginTop: '1rem',
                      fontSize: '0.75rem',
                      color: 'var(--pf-v5-global--Color--200)',
                    }}
                  >
                    Served by retrieval-hub · {elapsedMs}ms (mocked)
                  </div>
                </CardBody>
              </Card>
            </StackItem>
          </Stack>
        </PageSection>
      )}
    </>
  );
}

function makeMockHits(source: Source, topK: number): MockHit[] {
  const count = Math.min(topK, 5);
  const pidx = source.active_physical_index?.id ?? 'pidx_mock';
  const recipe = source.recipe.version;
  const lines = [
    'Retrieved chunk 1: the relevant excerpt would appear here, highlighting the most important passage matching the query.',
    'Retrieved chunk 2: a second passage, typically from a different document, discussing a related angle on the question.',
    'Retrieved chunk 3: a supporting snippet with concrete details, numbers, or procedural guidance.',
    'Retrieved chunk 4: a contextual passage that provides background for interpretation.',
    'Retrieved chunk 5: a final excerpt rounding out the top-5 recall set.',
  ];
  return Array.from({ length: count }, (_, i) => ({
    id: `hit_${i + 1}`,
    text: lines[i] ?? 'Retrieved chunk.',
    score: Number((0.92 - i * 0.07).toFixed(3)),
    source_uri: `${source.slug}://doc_${1000 + i}`,
    physical_index_id: pidx,
    recipe_version: recipe,
  }));
}

function makeMockRewrites(source: Source, rawQuery: string): string[] {
  // Apply up to 3 mock rewrites using the source's vocabulary mappings.
  const mappings = source.rewriter.vocabulary_mappings;
  if (mappings.length === 0) return [rawQuery];
  const applied: string[] = [];
  let current = rawQuery;
  for (const m of mappings) {
    if (current.toLowerCase().includes(m.lay_term.toLowerCase())) {
      current = current.replace(
        new RegExp(m.lay_term, 'ig'),
        m.canonical_term,
      );
      applied.push(current);
      if (applied.length >= 3) break;
    }
  }
  if (applied.length === 0) {
    return [
      `${rawQuery} (rewritten with ${source.family} domain context)`,
      `${rawQuery} [domain-aware reformulation]`,
    ];
  }
  return applied;
}
