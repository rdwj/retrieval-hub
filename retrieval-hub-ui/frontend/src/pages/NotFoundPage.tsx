import { Link } from 'react-router-dom';
import {
  EmptyState,
  EmptyStateBody,
  EmptyStateVariant,
  PageSection,
  Title,
} from '@patternfly/react-core';

export default function NotFoundPage() {
  return (
    <PageSection>
      <EmptyState variant={EmptyStateVariant.lg}>
        <Title headingLevel="h2">Page not found</Title>
        <EmptyStateBody>
          That route does not exist. <Link to="/catalog">Back to catalog</Link>.
        </EmptyStateBody>
      </EmptyState>
    </PageSection>
  );
}
