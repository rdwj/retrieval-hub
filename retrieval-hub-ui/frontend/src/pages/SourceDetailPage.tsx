import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Breadcrumb,
  BreadcrumbItem,
  Button,
  Card,
  CardBody,
  CardTitle,
  CodeBlock,
  CodeBlockCode,
  DataList,
  DataListCell,
  DataListItem,
  DataListItemCells,
  DataListItemRow,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  EmptyState,
  EmptyStateBody,
  EmptyStateVariant,
  Flex,
  FlexItem,
  Form,
  FormGroup,
  Label,
  LabelGroup,
  PageSection,
  Stack,
  StackItem,
  Tab,
  TabTitleText,
  Tabs,
  TextInput,
  Title,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';

import AccessRequiredBanner from '../components/AccessRequiredBanner';
import ActionBar from '../components/ActionBar';
import DomainTags from '../components/DomainTags';
import FamilyIcon from '../components/FamilyIcon';
import { usePersona } from '../context/PersonaContext';
import { MOCK_SOURCES } from '../data/mockSources';
import { bestScore, canAccess } from '../utils/accessCheck';
import {
  absoluteTime,
  familyDisplayName,
  formatLatencyHint,
  formatNumber,
  formatScore,
  formatSignedDelta,
  relativeTime,
} from '../utils/formatters';
import type { EvalResult, Source } from '../types/source';

export default function SourceDetailPage() {
  const { slug } = useParams<{ slug: string }>();
  const { persona } = usePersona();
  const [activeTab, setActiveTab] = useState<string | number>('overview');

  const source = MOCK_SOURCES.find((s) => s.slug === slug);

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

  const canQuery = canAccess(persona, source);

  return (
    <>
      <PageSection variant="light">
        <Breadcrumb>
          <BreadcrumbItem to="/catalog" render={() => <Link to="/catalog">Catalog</Link>} />
          <BreadcrumbItem isActive>{source.name}</BreadcrumbItem>
        </Breadcrumb>
        <div style={{ marginTop: '1rem' }}>
          <Flex
            spaceItems={{ default: 'spaceItemsSm' }}
            alignItems={{ default: 'alignItemsCenter' }}
          >
            <FlexItem>
              <FamilyIcon family={source.family} size="lg" />
            </FlexItem>
            <FlexItem>
              <Title headingLevel="h1">{source.name}</Title>
            </FlexItem>
          </Flex>
          <div
            style={{
              fontFamily: 'var(--pf-v5-global--FontFamily--monospace)',
              fontSize: '0.85rem',
              color: 'var(--pf-v5-global--Color--200)',
              marginTop: '0.25rem',
            }}
          >
            {source.slug}
          </div>
          <Flex
            style={{ marginTop: '0.5rem' }}
            spaceItems={{ default: 'spaceItemsSm' }}
            flexWrap={{ default: 'wrap' }}
          >
            <FlexItem>
              <Label color="grey">{familyDisplayName(source.family)}</Label>
            </FlexItem>
            <FlexItem>
              <Label color={source.status === 'published' ? 'green' : 'orange'}>
                {source.status}
              </Label>
            </FlexItem>
            <FlexItem>
              <Label
                color={
                  source.access.visibility === 'public' ? 'blue' : 'orange'
                }
              >
                {source.access.visibility}
              </Label>
            </FlexItem>
            <FlexItem>
              <span style={{ fontSize: '0.85rem' }}>
                Owned by <strong>{source.owner.team}</strong>
              </span>
            </FlexItem>
            <FlexItem>
              <span style={{ fontSize: '0.85rem' }}>
                {source.size_summary}
              </span>
            </FlexItem>
            <FlexItem>
              <span style={{ fontSize: '0.85rem' }}>
                Refreshed {relativeTime(source.lineage.last_refresh_at)}
              </span>
            </FlexItem>
          </Flex>
        </div>
      </PageSection>
      <PageSection>
        {!canQuery && (
          <AccessRequiredBanner source={source} persona={persona} />
        )}
        <ActionBar source={source} canQuery={canQuery} />
        <Tabs
          activeKey={activeTab}
          onSelect={(_e, key) => setActiveTab(key)}
          aria-label="Source detail tabs"
        >
          <Tab eventKey="overview" title={<TabTitleText>Overview</TabTitleText>}>
            <OverviewTab source={source} />
          </Tab>
          <Tab eventKey="recipe" title={<TabTitleText>Recipe</TabTitleText>}>
            <RecipeTab source={source} />
          </Tab>
          <Tab
            eventKey="evaluations"
            title={<TabTitleText>Evaluations</TabTitleText>}
          >
            <EvaluationsTab source={source} />
          </Tab>
          <Tab eventKey="rewriter" title={<TabTitleText>Rewriter</TabTitleText>}>
            <RewriterTab source={source} />
          </Tab>
          <Tab
            eventKey="prompts"
            title={<TabTitleText>Sample Prompts</TabTitleText>}
          >
            <SamplePromptsTab source={source} />
          </Tab>
          <Tab eventKey="access" title={<TabTitleText>Access</TabTitleText>}>
            <AccessTab source={source} />
          </Tab>
          <Tab eventKey="lineage" title={<TabTitleText>Lineage</TabTitleText>}>
            <LineageTab source={source} />
          </Tab>
        </Tabs>
      </PageSection>
    </>
  );
}

// ---------------------------------------------------------------------------
// Overview tab
// ---------------------------------------------------------------------------

function OverviewTab({ source }: { source: Source }) {
  const best = bestScore(source);
  const mcpSnippet = `{
  "mcpServers": {
    "retrieval-hub": {
      "transport": "streamable-http",
      "url": "https://mcp.retrieval-hub.example.com/mcp",
      "tools": ["query_source"],
      "defaults": {
        "source_slug": "${source.slug}",
        "top_k": 10,
        "use_rewrite": ${source.rewriter.enabled}
      }
    }
  }
}`;
  const firstPrompt = source.sample_prompts[0];

  return (
    <Stack hasGutter style={{ marginTop: '1rem' }}>
      <StackItem>
        <Card>
          <CardTitle>At a glance</CardTitle>
          <CardBody>
            <DescriptionList
              isHorizontal
              isCompact
              columnModifier={{ lg: '2Col' }}
            >
              <DescriptionListGroup>
                <DescriptionListTerm>Best score</DescriptionListTerm>
                <DescriptionListDescription>
                  {best
                    ? `R@5 ${formatScore(best.value)} on ${best.llm}${
                        best.rewrite_lift !== null && source.rewriter.enabled
                          ? ` (${formatSignedDelta(best.rewrite_lift)} with rewriter)`
                          : ''
                      }`
                    : 'Not evaluated yet'}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Latency hint</DescriptionListTerm>
                <DescriptionListDescription>
                  {formatLatencyHint(source.latency_p50_ms, source.latency_p95_ms)}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Cost hint</DescriptionListTerm>
                <DescriptionListDescription>
                  {source.cost_estimate_hint}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Rewriter</DescriptionListTerm>
                <DescriptionListDescription>
                  {source.rewriter.enabled
                    ? `Enabled (${source.rewriter.vocabulary_mappings.length} vocabulary mappings)`
                    : 'Disabled'}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Retrieval patterns</DescriptionListTerm>
                <DescriptionListDescription>
                  {source.retrieval_supported_patterns
                    .map((p) => p.pattern)
                    .join(', ')}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Agent writes</DescriptionListTerm>
                <DescriptionListDescription>
                  {source.agent_write_policy.allowed
                    ? `Allowed (${source.agent_write_policy.write_modes.join(', ')})`
                    : 'Not allowed'}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Refresh cadence</DescriptionListTerm>
                <DescriptionListDescription>
                  {source.lineage.refresh_cadence} · last{' '}
                  {relativeTime(source.lineage.last_refresh_at)}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Tags</DescriptionListTerm>
                <DescriptionListDescription>
                  <DomainTags tags={source.domain_tags} />
                </DescriptionListDescription>
              </DescriptionListGroup>
            </DescriptionList>
          </CardBody>
        </Card>
      </StackItem>

      <StackItem>
        <Card>
          <CardTitle>Description</CardTitle>
          <CardBody>
            <p style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
              {source.description_long}
            </p>
          </CardBody>
        </Card>
      </StackItem>

      <StackItem>
        <Card>
          <CardTitle>Intended use</CardTitle>
          <CardBody>
            <p style={{ margin: 0 }}>{source.intended_use}</p>
          </CardBody>
        </Card>
      </StackItem>

      <StackItem>
        <Card>
          <CardTitle>Out of scope</CardTitle>
          <CardBody>
            <p style={{ margin: 0 }}>{source.out_of_scope_use}</p>
          </CardBody>
        </Card>
      </StackItem>

      <StackItem>
        <Card>
          <CardTitle>Known limitations</CardTitle>
          <CardBody>
            <p style={{ margin: 0 }}>{source.known_limitations}</p>
          </CardBody>
        </Card>
      </StackItem>

      <StackItem>
        <Card>
          <CardTitle>Quick start</CardTitle>
          <CardBody>
            <ol style={{ margin: 0, paddingLeft: '1.25rem' }}>
              <li style={{ marginBottom: '1rem' }}>
                <strong>Copy the MCP config snippet:</strong>
                <CodeBlock style={{ marginTop: '0.5rem' }}>
                  <CodeBlockCode>{mcpSnippet}</CodeBlockCode>
                </CodeBlock>
              </li>
              <li style={{ marginBottom: '1rem' }}>
                <strong>Copy a sample prompt for your LLM:</strong>
                {firstPrompt ? (
                  <CodeBlock style={{ marginTop: '0.5rem' }}>
                    <CodeBlockCode>{firstPrompt.text}</CodeBlockCode>
                  </CodeBlock>
                ) : (
                  <p style={{ marginTop: '0.5rem' }}>
                    No sample prompts defined yet.
                  </p>
                )}
              </li>
              <li>
                <strong>Ask your agent a representative question.</strong>{' '}
                You should start getting results grounded in this source within
                a few seconds.
              </li>
            </ol>
          </CardBody>
        </Card>
      </StackItem>

      {source.citation_format && (
        <StackItem>
          <Card>
            <CardTitle>Citation format</CardTitle>
            <CardBody>
              <code>{source.citation_format}</code>
            </CardBody>
          </Card>
        </StackItem>
      )}
    </Stack>
  );
}

// ---------------------------------------------------------------------------
// Recipe tab
// ---------------------------------------------------------------------------

function RecipeTab({ source }: { source: Source }) {
  return (
    <Stack hasGutter style={{ marginTop: '1rem' }}>
      <StackItem>
        <Card>
          <CardTitle>Recipe v{source.recipe.version}</CardTitle>
          <CardBody>
            <CodeBlock>
              <CodeBlockCode>{source.recipe.raw_yaml}</CodeBlockCode>
            </CodeBlock>
          </CardBody>
        </Card>
      </StackItem>
      <StackItem>
        <Card>
          <CardTitle>Version history</CardTitle>
          <CardBody>
            <DataList aria-label="Recipe version history" isCompact>
              {source.recipe_version_history.map((v) => (
                <DataListItem key={v.version}>
                  <DataListItemRow>
                    <DataListItemCells
                      dataListCells={[
                        <DataListCell key="v" width={1}>
                          <strong>v{v.version}</strong>
                        </DataListCell>,
                        <DataListCell key="when" width={2}>
                          {relativeTime(v.active_since)}
                        </DataListCell>,
                        <DataListCell key="who" width={2}>
                          {v.author}
                        </DataListCell>,
                        <DataListCell key="summary" width={5}>
                          {v.summary}
                        </DataListCell>,
                      ]}
                    />
                  </DataListItemRow>
                </DataListItem>
              ))}
            </DataList>
          </CardBody>
        </Card>
      </StackItem>
      <StackItem>
        <Card>
          <CardTitle>Retrieval patterns</CardTitle>
          <CardBody>
            <Table variant="compact" aria-label="Retrieval patterns">
              <Thead>
                <Tr>
                  <Th>Pattern</Th>
                  <Th>Parameters</Th>
                </Tr>
              </Thead>
              <Tbody>
                {source.retrieval_supported_patterns.map((p) => (
                  <Tr key={p.pattern}>
                    <Td>
                      <code>{p.pattern}</code>
                      {p.pattern === source.retrieval_default_pattern && (
                        <Label color="blue" isCompact style={{ marginLeft: '0.5rem' }}>
                          default
                        </Label>
                      )}
                    </Td>
                    <Td>
                      <code style={{ fontSize: '0.8rem' }}>
                        {JSON.stringify(p.parameters)}
                      </code>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </CardBody>
        </Card>
      </StackItem>
    </Stack>
  );
}

// ---------------------------------------------------------------------------
// Evaluations tab
// ---------------------------------------------------------------------------

function EvaluationsTab({ source }: { source: Source }) {
  const openInMlflow = (e: EvalResult) => {
    alert(`Would open MLflow run: ${e.mlflow_run_id ?? e.eval_run_id}`);
  };

  if (source.evals.length === 0) {
    return (
      <EmptyState variant={EmptyStateVariant.sm} style={{ marginTop: '1rem' }}>
        <Title headingLevel="h3">No eval runs yet</Title>
        <EmptyStateBody>
          This source has not been evaluated. Publishing a source requires at
          least one eval run.
        </EmptyStateBody>
      </EmptyState>
    );
  }

  return (
    <Card style={{ marginTop: '1rem' }}>
      <CardTitle>All eval runs</CardTitle>
      <CardBody>
        <Table aria-label="Eval runs">
          <Thead>
            <Tr>
              <Th>LLM</Th>
              <Th>R@5</Th>
              <Th>MRR</Th>
              <Th>Rewrite lift</Th>
              <Th>Backend</Th>
              <Th>Run at</Th>
              <Th>Actions</Th>
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
                <Td>
                  <Label isCompact color="grey">
                    {e.source_system}
                  </Label>
                </Td>
                <Td>{relativeTime(e.run_at)}</Td>
                <Td>
                  <Button
                    variant="link"
                    isInline
                    onClick={() => openInMlflow(e)}
                  >
                    View in MLflow
                  </Button>
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      </CardBody>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Rewriter tab
// ---------------------------------------------------------------------------

function RewriterTab({ source }: { source: Source }) {
  const [testQuery, setTestQuery] = useState('');
  const [testResult, setTestResult] = useState<string[] | null>(null);

  if (!source.rewriter.enabled) {
    return (
      <EmptyState variant={EmptyStateVariant.sm} style={{ marginTop: '1rem' }}>
        <Title headingLevel="h3">Rewriter is disabled</Title>
        <EmptyStateBody>
          This source does not use the query rewriter. Enabling the rewriter
          requires declaring vocabulary mappings or sample queries so the
          shared template has domain context to work with.
        </EmptyStateBody>
      </EmptyState>
    );
  }

  const runTestRewrite = () => {
    if (!testQuery.trim()) return;
    // Mock: just substitute the first few known vocabulary terms.
    const base = testQuery.toLowerCase();
    let rewrite = testQuery;
    for (const m of source.rewriter.vocabulary_mappings.slice(0, 6)) {
      if (base.includes(m.lay_term.toLowerCase())) {
        rewrite = rewrite.replace(
          new RegExp(m.lay_term, 'ig'),
          m.canonical_term,
        );
      }
    }
    setTestResult([
      rewrite,
      `${rewrite} (focused on ${source.family})`,
      `${source.rewriter.domain_notes.split('.')[0] || 'domain-aware'}: ${rewrite}`,
    ]);
  };

  return (
    <Stack hasGutter style={{ marginTop: '1rem' }}>
      <StackItem>
        <Card>
          <CardTitle>Template</CardTitle>
          <CardBody>
            <DescriptionList isHorizontal isCompact>
              <DescriptionListGroup>
                <DescriptionListTerm>Shared template</DescriptionListTerm>
                <DescriptionListDescription>
                  <code>
                    {source.rewriter.shared_template_pointer} v
                    {source.rewriter.shared_template_version}
                  </code>
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Default LLM</DescriptionListTerm>
                <DescriptionListDescription>
                  <code>{source.rewriter.default_llm}</code>
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>LLM resolution</DescriptionListTerm>
                <DescriptionListDescription>
                  {source.rewriter.llm_resolution}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Max rewrites</DescriptionListTerm>
                <DescriptionListDescription>
                  {source.rewriter.max_rewrites}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Metadata version</DescriptionListTerm>
                <DescriptionListDescription>
                  v{source.rewriter.metadata_version}
                </DescriptionListDescription>
              </DescriptionListGroup>
            </DescriptionList>
          </CardBody>
        </Card>
      </StackItem>
      <StackItem>
        <Card>
          <CardTitle>
            Vocabulary mappings ({source.rewriter.vocabulary_mappings.length})
          </CardTitle>
          <CardBody>
            <Table variant="compact" aria-label="Vocabulary mappings">
              <Thead>
                <Tr>
                  <Th>Lay term</Th>
                  <Th>Canonical term</Th>
                  <Th>Qualifiers</Th>
                </Tr>
              </Thead>
              <Tbody>
                {source.rewriter.vocabulary_mappings.map((m) => (
                  <Tr key={m.lay_term}>
                    <Td>{m.lay_term}</Td>
                    <Td>{m.canonical_term}</Td>
                    <Td>{m.qualifiers ?? '—'}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </CardBody>
        </Card>
      </StackItem>
      <StackItem>
        <Card>
          <CardTitle>
            Sample queries ({source.rewriter.sample_queries.length})
          </CardTitle>
          <CardBody>
            <Table variant="compact" aria-label="Sample queries">
              <Thead>
                <Tr>
                  <Th>Raw query</Th>
                  <Th>Good rewrites</Th>
                </Tr>
              </Thead>
              <Tbody>
                {source.rewriter.sample_queries.map((q, idx) => (
                  <Tr key={idx}>
                    <Td>{q.raw_query}</Td>
                    <Td>
                      <ul style={{ margin: 0, paddingLeft: '1rem' }}>
                        {q.good_rewrites.map((r, ri) => (
                          <li key={ri}>{r}</li>
                        ))}
                      </ul>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </CardBody>
        </Card>
      </StackItem>
      <StackItem>
        <Card>
          <CardTitle>Domain notes</CardTitle>
          <CardBody>
            <p style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
              {source.rewriter.domain_notes}
            </p>
          </CardBody>
        </Card>
      </StackItem>
      <StackItem>
        <Card>
          <CardTitle>Test rewrite</CardTitle>
          <CardBody>
            <Form>
              <FormGroup label="Raw query" fieldId="test-query">
                <TextInput
                  id="test-query"
                  type="text"
                  value={testQuery}
                  onChange={(_e, v) => setTestQuery(v)}
                  placeholder="Try a lay-language query..."
                />
              </FormGroup>
              <Button
                variant="primary"
                onClick={runTestRewrite}
                style={{ marginTop: '0.5rem' }}
              >
                Run test rewrite (mock)
              </Button>
            </Form>
            {testResult && (
              <div style={{ marginTop: '1rem' }}>
                <strong>Mock rewrites:</strong>
                <ul>
                  {testResult.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            )}
          </CardBody>
        </Card>
      </StackItem>
    </Stack>
  );
}

// ---------------------------------------------------------------------------
// Sample prompts tab
// ---------------------------------------------------------------------------

function SamplePromptsTab({ source }: { source: Source }) {
  const [active, setActive] = useState<string | number>(
    source.sample_prompts[0]?.applies_to_llm_family ?? 0,
  );

  if (source.sample_prompts.length === 0) {
    return (
      <EmptyState variant={EmptyStateVariant.sm} style={{ marginTop: '1rem' }}>
        <Title headingLevel="h3">No sample prompts defined</Title>
        <EmptyStateBody>
          The source owner has not curated sample prompts yet.
        </EmptyStateBody>
      </EmptyState>
    );
  }

  const copyPrompt = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      alert('Prompt copied to clipboard.');
    } catch {
      alert(`Clipboard unavailable. Prompt:\n\n${text}`);
    }
  };

  return (
    <div style={{ marginTop: '1rem' }}>
      <Tabs
        activeKey={active}
        onSelect={(_e, key) => setActive(key)}
        isBox
        aria-label="Sample prompts by LLM family"
      >
        {source.sample_prompts.map((p) => (
          <Tab
            key={p.applies_to_llm_family}
            eventKey={p.applies_to_llm_family}
            title={<TabTitleText>{p.applies_to_llm_family}</TabTitleText>}
          >
            <Card style={{ marginTop: '1rem' }}>
              <CardBody>
                <div style={{ marginBottom: '0.5rem' }}>
                  <Label isCompact color="grey">
                    role: {p.role}
                  </Label>
                </div>
                <CodeBlock>
                  <CodeBlockCode>{p.text}</CodeBlockCode>
                </CodeBlock>
                <Button
                  variant="secondary"
                  onClick={() => copyPrompt(p.text)}
                  style={{ marginTop: '0.75rem' }}
                >
                  Copy prompt
                </Button>
              </CardBody>
            </Card>
          </Tab>
        ))}
      </Tabs>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Access tab
// ---------------------------------------------------------------------------

function AccessTab({ source }: { source: Source }) {
  return (
    <Stack hasGutter style={{ marginTop: '1rem' }}>
      <StackItem>
        <Card>
          <CardTitle>Access policy</CardTitle>
          <CardBody>
            <DescriptionList isHorizontal>
              <DescriptionListGroup>
                <DescriptionListTerm>Visibility</DescriptionListTerm>
                <DescriptionListDescription>
                  <Label
                    color={
                      source.access.visibility === 'public' ? 'blue' : 'orange'
                    }
                  >
                    {source.access.visibility}
                  </Label>
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Allowed groups</DescriptionListTerm>
                <DescriptionListDescription>
                  {source.access.allowed_groups.length === 0 ? (
                    <em>(any authenticated identity)</em>
                  ) : (
                    <LabelGroup isCompact>
                      {source.access.allowed_groups.map((g) => (
                        <Label key={g} isCompact color="blue">
                          {g}
                        </Label>
                      ))}
                    </LabelGroup>
                  )}
                </DescriptionListDescription>
              </DescriptionListGroup>
            </DescriptionList>
          </CardBody>
        </Card>
      </StackItem>
      <StackItem>
        <Card>
          <CardTitle>Agent write policy</CardTitle>
          <CardBody>
            <DescriptionList isHorizontal>
              <DescriptionListGroup>
                <DescriptionListTerm>Writes allowed</DescriptionListTerm>
                <DescriptionListDescription>
                  {source.agent_write_policy.allowed ? 'Yes' : 'No'}
                </DescriptionListDescription>
              </DescriptionListGroup>
              {source.agent_write_policy.allowed && (
                <>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Scope required</DescriptionListTerm>
                    <DescriptionListDescription>
                      <code>{source.agent_write_policy.scope_required}</code>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Allowed groups</DescriptionListTerm>
                    <DescriptionListDescription>
                      <LabelGroup isCompact>
                        {source.agent_write_policy.allowed_groups.map((g) => (
                          <Label key={g} isCompact color="orange">
                            {g}
                          </Label>
                        ))}
                      </LabelGroup>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Write modes</DescriptionListTerm>
                    <DescriptionListDescription>
                      <LabelGroup isCompact>
                        {source.agent_write_policy.write_modes.map((m) => (
                          <Label key={m} isCompact color="orange">
                            {m}
                          </Label>
                        ))}
                      </LabelGroup>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  {source.agent_write_policy.write_validation && (
                    <DescriptionListGroup>
                      <DescriptionListTerm>Validation</DescriptionListTerm>
                      <DescriptionListDescription>
                        Schema:{' '}
                        <code>
                          {source.agent_write_policy.write_validation.schema_id}
                        </code>
                        , requires provenance:{' '}
                        {source.agent_write_policy.write_validation.require_provenance
                          ? 'yes'
                          : 'no'}
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                  )}
                  {source.agent_write_policy.recent_write_activity_summary && (
                    <DescriptionListGroup>
                      <DescriptionListTerm>Recent activity</DescriptionListTerm>
                      <DescriptionListDescription>
                        {source.agent_write_policy.recent_write_activity_summary}
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                  )}
                </>
              )}
            </DescriptionList>
          </CardBody>
        </Card>
      </StackItem>
    </Stack>
  );
}

// ---------------------------------------------------------------------------
// Lineage tab
// ---------------------------------------------------------------------------

function LineageTab({ source }: { source: Source }) {
  return (
    <Stack hasGutter style={{ marginTop: '1rem' }}>
      <StackItem>
        <Card>
          <CardTitle>Origin</CardTitle>
          <CardBody>
            <DescriptionList isHorizontal>
              <DescriptionListGroup>
                <DescriptionListTerm>Kind</DescriptionListTerm>
                <DescriptionListDescription>
                  <code>{source.lineage.origin_kind}</code>
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Config</DescriptionListTerm>
                <DescriptionListDescription>
                  <CodeBlock>
                    <CodeBlockCode>
                      {JSON.stringify(source.lineage.origin_config, null, 2)}
                    </CodeBlockCode>
                  </CodeBlock>
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Refresh cadence</DescriptionListTerm>
                <DescriptionListDescription>
                  {source.lineage.refresh_cadence}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Last refresh</DescriptionListTerm>
                <DescriptionListDescription>
                  {relativeTime(source.lineage.last_refresh_at)} (
                  {absoluteTime(source.lineage.last_refresh_at)})
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Next refresh</DescriptionListTerm>
                <DescriptionListDescription>
                  {source.lineage.next_scheduled_refresh_at
                    ? relativeTime(source.lineage.next_scheduled_refresh_at)
                    : 'On demand / not scheduled'}
                </DescriptionListDescription>
              </DescriptionListGroup>
            </DescriptionList>
          </CardBody>
        </Card>
      </StackItem>
      <StackItem>
        <Card>
          <CardTitle>
            Ingestion runs ({source.lineage.ingestion_runs.length})
          </CardTitle>
          <CardBody>
            {source.lineage.ingestion_runs.length === 0 ? (
              <p>No ingestion runs recorded yet.</p>
            ) : (
              <DataList aria-label="Ingestion runs" isCompact>
                {source.lineage.ingestion_runs.map((r) => (
                  <DataListItem key={r.id}>
                    <DataListItemRow>
                      <DataListItemCells
                        dataListCells={[
                          <DataListCell key="status" width={1}>
                            <Label
                              isCompact
                              color={
                                r.status === 'completed'
                                  ? 'green'
                                  : r.status === 'failed'
                                    ? 'red'
                                    : 'blue'
                              }
                            >
                              {r.status}
                            </Label>
                          </DataListCell>,
                          <DataListCell key="time" width={2}>
                            {relativeTime(r.started_at)}
                          </DataListCell>,
                          <DataListCell key="duration" width={1}>
                            {r.duration_seconds}s
                          </DataListCell>,
                          <DataListCell key="docs" width={2}>
                            {formatNumber(r.document_count)} docs
                          </DataListCell>,
                          <DataListCell key="by" width={3}>
                            {r.triggered_by}
                          </DataListCell>,
                        ]}
                      />
                    </DataListItemRow>
                  </DataListItem>
                ))}
              </DataList>
            )}
          </CardBody>
        </Card>
      </StackItem>
    </Stack>
  );
}
