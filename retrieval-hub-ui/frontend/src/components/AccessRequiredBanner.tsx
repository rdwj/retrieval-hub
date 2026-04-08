import {
  Alert,
  Button,
  ExpandableSection,
  Flex,
  FlexItem,
  Label,
  LabelGroup,
  Stack,
  StackItem,
} from '@patternfly/react-core';
import { useState } from 'react';

import type { Persona, Source } from '../types/source';

interface AccessRequiredBannerProps {
  source: Source;
  persona: Persona;
}

export default function AccessRequiredBanner({
  source,
  persona,
}: AccessRequiredBannerProps) {
  const [expanded, setExpanded] = useState(false);

  const subject = `Access request: ${source.slug}`;
  const body = `Hi ${source.owner.team},

I am requesting access to the retrieval-hub source "${source.name}" (slug: ${source.slug}).

My identity is: ${persona.identity_sub} (${persona.identity_kind})
My current groups: ${persona.identity_groups.join(', ') || '(none)'}
Required groups: ${source.access.allowed_groups.join(', ')}

I plan to use this source for:
[ please describe your use case ]

Thanks,
${persona.identity_sub}`;

  const mailto = `mailto:${source.owner.contacts.join(',')}?subject=${encodeURIComponent(
    subject,
  )}&body=${encodeURIComponent(body)}`;

  return (
    <Alert
      variant="warning"
      title="Access required"
      isInline
      style={{ marginBottom: '1rem' }}
    >
      <Stack hasGutter>
        <StackItem>
          This source is restricted. Your agent identity does not currently
          have access.
        </StackItem>
        <StackItem>
          <Flex direction={{ default: 'column' }} spaceItems={{ default: 'spaceItemsXs' }}>
            <FlexItem>
              <strong>Your identity:</strong>{' '}
              <code>{persona.identity_sub}</code> ({persona.identity_kind})
            </FlexItem>
            <FlexItem>
              <strong>Your groups:</strong>{' '}
              <LabelGroup isCompact>
                {persona.identity_groups.length === 0 ? (
                  <Label isCompact color="grey">
                    (none)
                  </Label>
                ) : (
                  persona.identity_groups.map((g) => (
                    <Label key={g} isCompact color="grey">
                      {g}
                    </Label>
                  ))
                )}
              </LabelGroup>
            </FlexItem>
            <FlexItem>
              <strong>Required groups:</strong>{' '}
              <LabelGroup isCompact>
                {source.access.allowed_groups.map((g) => {
                  const missing = !persona.identity_groups.includes(g);
                  return (
                    <Label
                      key={g}
                      isCompact
                      color={missing ? 'red' : 'green'}
                    >
                      {g}
                      {missing ? ' (missing)' : ''}
                    </Label>
                  );
                })}
              </LabelGroup>
            </FlexItem>
            <FlexItem>
              <strong>Owner:</strong> {source.owner.team} (
              {source.owner.contacts.join(', ') || 'no contact listed'})
            </FlexItem>
          </Flex>
        </StackItem>
        <StackItem>
          <Button
            component="a"
            href={mailto}
            variant="primary"
            isDisabled={source.owner.contacts.length === 0}
          >
            Contact Owner
          </Button>
        </StackItem>
        <StackItem>
          <ExpandableSection
            toggleText={expanded ? 'Hide email preview' : 'Show email preview'}
            onToggle={(_e, isExpanded) => setExpanded(isExpanded)}
            isExpanded={expanded}
          >
            <div
              style={{
                background: 'var(--pf-v5-global--BackgroundColor--200)',
                padding: '0.75rem',
                borderRadius: '4px',
                fontFamily: 'var(--pf-v5-global--FontFamily--monospace)',
                fontSize: '0.8rem',
                whiteSpace: 'pre-wrap',
              }}
            >
              <strong>Subject:</strong> {subject}
              {'\n\n'}
              {body}
            </div>
          </ExpandableSection>
        </StackItem>
      </Stack>
    </Alert>
  );
}
