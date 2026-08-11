import { Link } from 'react-router-dom';
import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  FlexItem,
  Grid,
  GridItem,
  PageSection,
  Stack,
  StackItem,
  Title,
} from '@patternfly/react-core';
import {
  ArrowRightIcon,
  ConnectedIcon,
  LockIcon,
  MagicIcon,
  PlayIcon,
  ProjectDiagramIcon,
  SearchIcon,
  TachometerAltIcon,
} from '@patternfly/react-icons';

import { useTour } from '../context/TourContext';

interface FeatureCardProps {
  icon: React.ReactNode;
  iconColor: string;
  title: string;
  description: string;
  linkTo: string;
  linkLabel: string;
}

function FeatureCard({
  icon,
  iconColor,
  title,
  description,
  linkTo,
  linkLabel,
}: FeatureCardProps) {
  return (
    <Card isFullHeight>
      <CardBody>
        <Stack hasGutter>
          <StackItem>
            <div
              style={{
                width: 48,
                height: 48,
                borderRadius: '50%',
                background: iconColor,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                fontSize: '1.25rem',
              }}
            >
              {icon}
            </div>
          </StackItem>
          <StackItem>
            <CardTitle style={{ fontSize: '1.1rem', fontWeight: 600 }}>
              {title}
            </CardTitle>
          </StackItem>
          <StackItem>
            <p
              style={{
                fontSize: '0.9rem',
                lineHeight: 1.6,
                color: 'var(--pf-v5-global--Color--200)',
                margin: 0,
              }}
            >
              {description}
            </p>
          </StackItem>
          <StackItem>
            <Button
              variant="link"
              component={(props: React.ComponentProps<typeof Link>) => (
                <Link {...props} to={linkTo} />
              )}
              icon={<ArrowRightIcon />}
              iconPosition="end"
              style={{ paddingLeft: 0 }}
            >
              {linkLabel}
            </Button>
          </StackItem>
        </Stack>
      </CardBody>
    </Card>
  );
}

interface StepCardProps {
  number: number;
  text: string;
}

function StepCard({ number, text }: StepCardProps) {
  return (
    <Card isFlat isCompact style={{ textAlign: 'center', height: '100%' }}>
      <CardBody>
        <div
          style={{
            fontSize: '2rem',
            fontWeight: 700,
            color: 'var(--pf-v5-global--primary-color--100)',
            marginBottom: '0.5rem',
          }}
        >
          {number}
        </div>
        <p
          style={{
            fontSize: '0.9rem',
            lineHeight: 1.5,
            color: 'var(--pf-v5-global--Color--200)',
            margin: 0,
          }}
        >
          {text}
        </p>
      </CardBody>
    </Card>
  );
}

export default function ValuePropPage() {
  const tour = useTour();

  return (
    <>
      {/* Hero */}
      <PageSection
        style={{
          background: 'var(--pf-v5-global--BackgroundColor--dark-100)',
          color: '#fff',
          textAlign: 'center',
          padding: '4rem 2rem',
        }}
      >
        <Title
          headingLevel="h1"
          size="4xl"
          style={{ color: '#fff', marginBottom: '0.5rem' }}
        >
          retrieval-hub
        </Title>
        <p
          style={{
            fontSize: '1.25rem',
            color: 'var(--pf-v5-global--Color--light-300)',
            marginBottom: '1.5rem',
            maxWidth: 600,
            marginLeft: 'auto',
            marginRight: 'auto',
          }}
        >
          One catalog. Every retrieval source. Zero artisanal pipelines.
        </p>
        <p
          style={{
            fontSize: '1rem',
            lineHeight: 1.6,
            maxWidth: 700,
            marginLeft: 'auto',
            marginRight: 'auto',
            marginBottom: '2rem',
            color: 'var(--pf-v5-global--Color--light-200)',
          }}
        >
          RAG is artisanal today. Every team builds bespoke pipelines with siloed
          vocabulary and no quality comparison. retrieval-hub makes retrieval a
          platform service: a shared catalog of sources, transparent eval scores,
          per-domain query rewriters, and MCP-native access with identity flowing
          through to the agent.
        </p>
        <Flex
          justifyContent={{ default: 'justifyContentCenter' }}
          spaceItems={{ default: 'spaceItemsMd' }}
        >
          <FlexItem>
            <Button
              variant="primary"
              size="lg"
              icon={<PlayIcon />}
              onClick={() => tour.start()}
            >
              Take the guided tour
            </Button>
          </FlexItem>
          <FlexItem>
            <Button
              variant="secondary"
              size="lg"
              icon={<ArrowRightIcon />}
              iconPosition="end"
              component={(props: React.ComponentProps<typeof Link>) => (
                <Link {...props} to="/catalog" />
              )}
              style={{ color: '#fff', borderColor: '#fff' }}
            >
              Browse the catalog
            </Button>
          </FlexItem>
        </Flex>
      </PageSection>

      {/* Problem statement */}
      <PageSection>
        <div style={{ maxWidth: 800, margin: '0 auto' }}>
          <Card isFlat>
            <CardBody>
              <Title
                headingLevel="h2"
                size="xl"
                style={{ marginBottom: '1rem' }}
              >
                The problem
              </Title>
              <p style={{ fontSize: '0.95rem', lineHeight: 1.7, margin: 0 }}>
                Every team that wants to give their agent access to a corpus
                builds a bespoke pipeline: picks an embedding model, decides on
                chunking, stands up a vector store, writes retrieval code, and
                hardwires all of it into their agent. None of it is reusable. The
                next team does the same thing with different choices, and there
                is no way to compare quality across them. Vocabulary is siloed,
                and access control is ad-hoc.
              </p>
            </CardBody>
          </Card>
        </div>
      </PageSection>

      {/* Feature grid */}
      <PageSection>
        <Title
          headingLevel="h2"
          size="xl"
          style={{ marginBottom: '1.5rem', textAlign: 'center' }}
        >
          What retrieval-hub provides
        </Title>
        <Grid hasGutter>
          <GridItem xl={4} md={6} sm={12}>
            <FeatureCard
              icon={<SearchIcon />}
              iconColor="var(--pf-v5-global--primary-color--100)"
              title="Discoverability"
              description="A catalog of every retrieval source, browsable and searchable. Filter by family, access level, or domain tags. Find what's available before you build."
              linkTo="/catalog"
              linkLabel="Explore the catalog"
            />
          </GridItem>
          <GridItem xl={4} md={6} sm={12}>
            <FeatureCard
              icon={<TachometerAltIcon />}
              iconColor="#6753ac"
              title="Quality transparency"
              description="Eval scores front and center. Every source shows Recall@5 and MRR across multiple LLMs. You see the numbers before you wire a source into your agent."
              linkTo="/sources/va-clinical-guidelines#evaluations"
              linkLabel="See eval scores"
            />
          </GridItem>
          <GridItem xl={4} md={6} sm={12}>
            <FeatureCard
              icon={<MagicIcon />}
              iconColor="#3e8635"
              title="Per-source query rewriting"
              description='Domain vocabulary that improves retrieval. The VA Clinical Guidelines source translates "high blood pressure" to "hypertension" before searching, giving a +0.22 lift in recall.'
              linkTo="/sources/va-clinical-guidelines#rewriter"
              linkLabel="See the rewriter"
            />
          </GridItem>
          <GridItem xl={4} md={6} sm={12}>
            <FeatureCard
              icon={<ConnectedIcon />}
              iconColor="#004080"
              title="MCP-native access"
              description="One tool call. The agent calls query_source via MCP, and retrieval-hub handles embedding, rewriting, and routing. Copy the config snippet and you are live."
              linkTo="/sources/rh-product-docs"
              linkLabel="See MCP config"
            />
          </GridItem>
          <GridItem xl={4} md={6} sm={12}>
            <FeatureCard
              icon={<LockIcon />}
              iconColor="#c9190b"
              title="Identity-aware access control"
              description="Visibility and group-based access that flows through to the agent. The MCP auth token carries the caller's identity. If they lack access, the query is denied."
              linkTo="/sources/clinical-notes-staging#access"
              linkLabel="See access policies"
            />
          </GridItem>
          <GridItem xl={4} md={6} sm={12}>
            <FeatureCard
              icon={<ProjectDiagramIcon />}
              iconColor="#009596"
              title="Multi-family support"
              description="Documents, clinical documents, code, tabular data, and knowledge graphs. Each family gets appropriate chunking, embedding, and retrieval patterns."
              linkTo="/sources/openshift-kg"
              linkLabel="See the knowledge graph"
            />
          </GridItem>
        </Grid>
      </PageSection>

      {/* How it works */}
      <PageSection variant="light">
        <Title
          headingLevel="h2"
          size="xl"
          style={{ marginBottom: '1.5rem', textAlign: 'center' }}
        >
          How it works
        </Title>
        <Grid hasGutter>
          <GridItem xl={3} md={6} sm={12}>
            <StepCard
              number={1}
              text="Source owners define a recipe: the parser, chunker, embedding model, and storage backend."
            />
          </GridItem>
          <GridItem xl={3} md={6} sm={12}>
            <StepCard
              number={2}
              text="retrieval-hub builds and maintains the physical index. Ingestion runs are tracked with full lineage."
            />
          </GridItem>
          <GridItem xl={3} md={6} sm={12}>
            <StepCard
              number={3}
              text="Eval runs measure retrieval quality. Scores are visible in the catalog alongside rewriter lift."
            />
          </GridItem>
          <GridItem xl={3} md={6} sm={12}>
            <StepCard
              number={4}
              text="Agents call query_source via MCP. retrieval-hub handles embedding, rewriting, routing, and auth."
            />
          </GridItem>
        </Grid>
      </PageSection>

      {/* Footer CTA */}
      <PageSection style={{ textAlign: 'center', padding: '3rem 2rem' }}>
        <Title
          headingLevel="h2"
          size="xl"
          style={{ marginBottom: '1.5rem' }}
        >
          Ready to explore?
        </Title>
        <Flex
          justifyContent={{ default: 'justifyContentCenter' }}
          spaceItems={{ default: 'spaceItemsMd' }}
        >
          <FlexItem>
            <Button
              variant="primary"
              size="lg"
              icon={<PlayIcon />}
              onClick={() => tour.start()}
            >
              Take the guided tour
            </Button>
          </FlexItem>
          <FlexItem>
            <Button
              variant="secondary"
              size="lg"
              icon={<ArrowRightIcon />}
              iconPosition="end"
              component={(props: React.ComponentProps<typeof Link>) => (
                <Link {...props} to="/catalog" />
              )}
            >
              Browse the catalog
            </Button>
          </FlexItem>
        </Flex>
      </PageSection>
    </>
  );
}
