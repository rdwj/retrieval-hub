import { Link } from 'react-router-dom';
import {
  Button,
  Card,
  CardBody,
  CardTitle,
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
  Label,
  PageSection,
  Stack,
  StackItem,
  Title,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';

import { usePersona } from '../context/PersonaContext';
import { MOCK_SOURCES, MOCK_AUDIT_RECORDS } from '../data/mockSources';
import {
  bestScore,
  healthIsProblematic,
  ownedSources,
} from '../utils/accessCheck';
import {
  absoluteTime,
  familyDisplayName,
  formatScore,
  relativeTime,
} from '../utils/formatters';
import type { Source } from '../types/source';

export default function AdminPage() {
  const { persona } = usePersona();
  const isAdmin = persona.scopes.includes('admin.read');
  const isOwner = persona.owner_of_teams.length > 0;

  if (!isAdmin && !isOwner) {
    return (
      <PageSection>
        <EmptyState variant={EmptyStateVariant.lg}>
          <Title headingLevel="h2">Not authorized</Title>
          <EmptyStateBody>
            The admin dashboard is only available to platform admins and
            source owners. Use the "View as..." dropdown in the header to
            switch personas.
          </EmptyStateBody>
        </EmptyState>
      </PageSection>
    );
  }

  const scopedSources: Source[] = isAdmin
    ? MOCK_SOURCES
    : ownedSources(persona, MOCK_SOURCES);

  // Scoped audit: owner view only shows records for owned sources.
  const scopedAudit = isAdmin
    ? MOCK_AUDIT_RECORDS
    : MOCK_AUDIT_RECORDS.filter((r) =>
        scopedSources.some((s) => s.slug === r.source_slug),
      );

  const scopeIndicator = isAdmin
    ? 'Cluster view'
    : `My sources (${scopedSources.length})`;

  const published = scopedSources.filter((s) => s.status === 'published').length;
  const draft = scopedSources.filter((s) => s.status === 'draft').length;
  const curated = scopedSources.filter((s) => s.status === 'curated').length;
  const retired = scopedSources.filter((s) => s.status === 'retired').length;
  const flaggedSources = scopedSources.filter(healthIsProblematic);
  const lastAgentWrite = scopedAudit.find((r) =>
    r.action.startsWith('source.write.'),
  );

  // Sort sources for the Top Sources table: problematic first, then by
  // recently updated.
  const topSources = [...scopedSources].sort((a, b) => {
    const ap = healthIsProblematic(a) ? 1 : 0;
    const bp = healthIsProblematic(b) ? 1 : 0;
    if (ap !== bp) return bp - ap;
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
  });

  return (
    <>
      <PageSection variant="light">
        <Title headingLevel="h1">Admin dashboard</Title>
        <div
          style={{
            marginTop: '0.25rem',
            color: 'var(--pf-v5-global--Color--200)',
            fontSize: '0.9rem',
          }}
        >
          {scopeIndicator}
          {' · '}
          retrieval-hub catalog · observability delegated to Grafana & MLflow
        </div>
      </PageSection>

      <PageSection>
        <Stack hasGutter>
          {/* Panel 1: Cluster Health */}
          <StackItem>
            <Card>
              <CardTitle>Cluster health</CardTitle>
              <CardBody>
                <DescriptionList
                  isHorizontal
                  isCompact
                  columnModifier={{ lg: '3Col' }}
                >
                  <DescriptionListGroup>
                    <DescriptionListTerm>Published</DescriptionListTerm>
                    <DescriptionListDescription>
                      <strong style={{ fontSize: '1.25rem' }}>{published}</strong>{' '}
                      sources
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Draft</DescriptionListTerm>
                    <DescriptionListDescription>{draft}</DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Curated</DescriptionListTerm>
                    <DescriptionListDescription>{curated}</DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Retired</DescriptionListTerm>
                    <DescriptionListDescription>{retired}</DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Flagged</DescriptionListTerm>
                    <DescriptionListDescription>
                      {flaggedSources.length > 0 ? (
                        <Label color="orange">
                          {flaggedSources.length} source
                          {flaggedSources.length === 1 ? '' : 's'}
                        </Label>
                      ) : (
                        'none'
                      )}
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Last agent write</DescriptionListTerm>
                    <DescriptionListDescription>
                      {lastAgentWrite
                        ? relativeTime(lastAgentWrite.occurred_at)
                        : 'none'}
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                </DescriptionList>
                <Flex
                  spaceItems={{ default: 'spaceItemsSm' }}
                  style={{ marginTop: '1rem' }}
                >
                  <FlexItem>
                    <Button
                      variant="secondary"
                      onClick={() =>
                        alert(
                          'Would open: https://grafana.example.com/d/retrieval-hub',
                        )
                      }
                    >
                      View in Grafana
                    </Button>
                  </FlexItem>
                  <FlexItem>
                    <Button
                      variant="secondary"
                      onClick={() =>
                        alert(
                          'Would open: https://mlflow.example.com/#/experiments?filter=retrieval_hub',
                        )
                      }
                    >
                      View in MLflow
                    </Button>
                  </FlexItem>
                  {isAdmin && (
                    <FlexItem>
                      <Button
                        variant="secondary"
                        onClick={() =>
                          alert(
                            'Would open: https://keycloak.example.com/admin/master/console/events',
                          )
                        }
                      >
                        View in Keycloak
                      </Button>
                    </FlexItem>
                  )}
                </Flex>
              </CardBody>
            </Card>
          </StackItem>

          {/* Panel 2: Top Sources */}
          <StackItem>
            <Card>
              <CardTitle>Top sources</CardTitle>
              <CardBody>
                <Table variant="compact" aria-label="Top sources">
                  <Thead>
                    <Tr>
                      <Th>Name</Th>
                      <Th>Family</Th>
                      <Th>Status</Th>
                      <Th>Best R@5</Th>
                      <Th>Last refresh</Th>
                      <Th>Health</Th>
                      <Th>Actions</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {topSources.map((s) => {
                      const best = bestScore(s);
                      const health =
                        s.active_physical_index?.health ?? 'unknown';
                      const isStale =
                        s.health_flags.some((f) => f.kind === 'stale_refresh');
                      return (
                        <Tr key={s.id}>
                          <Td>
                            <Link to={`/sources/${s.slug}`}>{s.name}</Link>
                          </Td>
                          <Td>{familyDisplayName(s.family)}</Td>
                          <Td>
                            <Label isCompact>{s.status}</Label>
                          </Td>
                          <Td>
                            {best ? formatScore(best.value) : '—'}
                          </Td>
                          <Td>
                            <span
                              style={{
                                color: isStale
                                  ? 'var(--pf-v5-global--warning-color--100)'
                                  : undefined,
                              }}
                            >
                              {relativeTime(s.lineage.last_refresh_at)}
                            </span>
                          </Td>
                          <Td>
                            <Label
                              isCompact
                              color={
                                health === 'ok'
                                  ? 'green'
                                  : health === 'degraded'
                                    ? 'orange'
                                    : health === 'failed'
                                      ? 'red'
                                      : 'grey'
                              }
                            >
                              {health}
                            </Label>
                          </Td>
                          <Td>
                            <Button
                              variant="link"
                              isInline
                              onClick={() =>
                                alert(
                                  `Would open: https://grafana.example.com/d/retrieval-hub?var-source=${s.slug}`,
                                )
                              }
                            >
                              View in Grafana
                            </Button>
                          </Td>
                        </Tr>
                      );
                    })}
                  </Tbody>
                </Table>
              </CardBody>
            </Card>
          </StackItem>

          {/* Panel 3: Recent Catalog Changes */}
          <StackItem>
            <Card>
              <CardTitle>Recent catalog changes</CardTitle>
              <CardBody>
                <DataList aria-label="Recent catalog changes" isCompact>
                  {scopedAudit.map((r, idx) => (
                    <DataListItem key={idx}>
                      <DataListItemRow>
                        <DataListItemCells
                          dataListCells={[
                            <DataListCell key="when" width={2}>
                              <div>{relativeTime(r.occurred_at)}</div>
                              <div
                                style={{
                                  fontSize: '0.7rem',
                                  color:
                                    'var(--pf-v5-global--Color--200)',
                                }}
                              >
                                {absoluteTime(r.occurred_at)}
                              </div>
                            </DataListCell>,
                            <DataListCell key="action" width={2}>
                              <code style={{ fontSize: '0.75rem' }}>
                                {r.action}
                              </code>
                            </DataListCell>,
                            <DataListCell key="who" width={2}>
                              <code style={{ fontSize: '0.75rem' }}>
                                {r.actor_sub}
                              </code>
                            </DataListCell>,
                            <DataListCell key="source" width={2}>
                              <Link to={`/sources/${r.source_slug}`}>
                                {r.source_slug}
                              </Link>
                            </DataListCell>,
                            <DataListCell key="summary" width={4}>
                              {r.summary}
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
        </Stack>
      </PageSection>
    </>
  );
}
