import { Label, LabelGroup } from '@patternfly/react-core';

import type { SourceFamily, SourceStatus, Visibility } from '../types/source';

interface DomainTagsProps {
  tags: string[];
  numLabels?: number;
  // Optional: if provided, tags matching these values (case-insensitive) are
  // filtered out to avoid duplicating the source's family/status/visibility
  // badges shown elsewhere on the card.
  filterAgainst?: {
    family?: SourceFamily;
    status?: SourceStatus;
    visibility?: Visibility;
  };
}

export default function DomainTags({
  tags,
  numLabels = 5,
  filterAgainst,
}: DomainTagsProps) {
  const excluded = new Set<string>();
  if (filterAgainst) {
    if (filterAgainst.family) {
      excluded.add(filterAgainst.family.toLowerCase());
      // also exclude family name without the "_document" suffix
      excluded.add(filterAgainst.family.replace('_document', '').toLowerCase());
    }
    if (filterAgainst.status) excluded.add(filterAgainst.status.toLowerCase());
    if (filterAgainst.visibility) excluded.add(filterAgainst.visibility.toLowerCase());
  }

  const visible = tags.filter((tag) => !excluded.has(tag.toLowerCase()));

  if (visible.length === 0) return null;
  return (
    <LabelGroup numLabels={numLabels} isCompact>
      {visible.map((tag) => (
        <Label key={tag} isCompact color="blue">
          {tag}
        </Label>
      ))}
    </LabelGroup>
  );
}
