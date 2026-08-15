import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Breadcrumb,
  BreadcrumbItem,
  Bullseye,
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

import { useSource } from '../hooks/useSource';
import { formatScore } from '../utils/formatters';

interface PlaygroundHit {
  text: string;
  score: number;
  doc_title: string;
  doc_url: string;
  doc_section: string | null;
}

interface PlaygroundResult {
  hits: PlaygroundHit[];
  answer: string;
  usage_rules: Record<string, unknown> | null;
  elapsed_ms: number;
  model: string;
}

export default function PlaygroundPage() {
  const { slug } = useParams<{ slug: string }>();
  const { data: source, loading } = useSource(slug!);

  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState('10');
  const [useRewrite, setUseRewrite] = useState(
    source?.rewriter?.enabled ?? false,
  );
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<PlaygroundResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (loading) {
    return (
      <PageSection>
        <Bullseye style={{ minHeight: '16rem' }}>
          <Spinner size="xl" aria-label="Loading source" />
        </Bullseye>
      </PageSection>
    );
  }

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

  const runQuery = async () => {
    if (!query.trim()) return;
    setRunning(true);
    setResult(null);
    setError(null);
    try {
      const resp = await fetch('/api/playground/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query,
          source_slug: source.slug,
          top_k: parseInt(topK, 10) || 5,
        }),
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(`API error ${resp.status}: ${detail}`);
      }
      setResult(await resp.json());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
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
          Query this source with real retrieval and LLM-generated answers.
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
              {source.rewriter?.enabled && (
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
      {error && (
        <PageSection>
          <Card>
            <CardBody>
              <p style={{ color: 'var(--pf-v5-global--danger-color--100)' }}>
                {error}
              </p>
            </CardBody>
          </Card>
        </PageSection>
      )}
      {result && (
        <PageSection>
          <Stack hasGutter>
            <StackItem>
              <Card>
                <CardTitle>Answer</CardTitle>
                <CardBody>
                  <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                    {result.answer}
                  </div>
                  <div
                    style={{
                      marginTop: '1rem',
                      fontSize: '0.75rem',
                      color: 'var(--pf-v5-global--Color--200)',
                    }}
                  >
                    Generated by {result.model} · {result.elapsed_ms}ms
                  </div>
                </CardBody>
              </Card>
            </StackItem>
            <StackItem>
              <Card>
                <CardTitle>Retrieved chunks ({result.hits.length})</CardTitle>
                <CardBody>
                  <Stack hasGutter>
                    {result.hits.map((hit, i) => (
                      <StackItem key={i}>
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
                                {hit.doc_title}
                                {hit.doc_section && ` — ${hit.doc_section}`}
                              </span>
                            </div>
                            <p style={{ margin: 0, fontSize: '0.85rem' }}>
                              {hit.text.slice(0, 400)}
                              {hit.text.length > 400 && '…'}
                            </p>
                            {hit.doc_url && (
                              <div
                                style={{
                                  fontSize: '0.7rem',
                                  color: 'var(--pf-v5-global--Color--200)',
                                  marginTop: '0.5rem',
                                }}
                              >
                                <a href={hit.doc_url} target="_blank" rel="noreferrer">
                                  Source document
                                </a>
                              </div>
                            )}
                          </CardBody>
                        </Card>
                      </StackItem>
                    ))}
                  </Stack>
                </CardBody>
              </Card>
            </StackItem>
          </Stack>
        </PageSection>
      )}
    </>
  );
}
