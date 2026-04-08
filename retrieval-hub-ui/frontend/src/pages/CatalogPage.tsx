import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Checkbox,
  EmptyState,
  EmptyStateBody,
  EmptyStateVariant,
  Gallery,
  PageSection,
  SearchInput,
  Select,
  SelectList,
  SelectOption,
  Title,
  Toolbar,
  ToolbarContent,
  ToolbarFilter,
  ToolbarGroup,
  ToolbarItem,
  MenuToggle,
} from '@patternfly/react-core';
import { useState } from 'react';

import SourceCard from '../components/SourceCard';
import { usePersona } from '../context/PersonaContext';
import { MOCK_SOURCES } from '../data/mockSources';
import { bestScore, visibleSourcesForCatalog } from '../utils/accessCheck';
import type { SourceFamily, Visibility } from '../types/source';

type SortMode = 'alpha' | 'recent' | 'score';

export default function CatalogPage() {
  const { persona } = usePersona();
  const [searchParams, setSearchParams] = useSearchParams();

  const q = searchParams.get('q') ?? '';
  const familyFilter = searchParams.get('family') as SourceFamily | null;
  const accessFilter = searchParams.get('access') as Visibility | null;
  const hasRewriter = searchParams.get('has_rewriter') === 'true';
  const sort = (searchParams.get('sort') as SortMode | null) ?? 'alpha';

  const [familyOpen, setFamilyOpen] = useState(false);
  const [accessOpen, setAccessOpen] = useState(false);
  const [sortOpen, setSortOpen] = useState(false);

  const updateParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(searchParams);
    if (value === null || value === '') next.delete(key);
    else next.set(key, value);
    setSearchParams(next, { replace: true });
  };

  const visible = useMemo(
    () => visibleSourcesForCatalog(persona, MOCK_SOURCES),
    [persona],
  );

  const filtered = useMemo(() => {
    let out = visible.filter((s) => s.status === 'published');
    if (q.trim()) {
      const needle = q.toLowerCase();
      out = out.filter(
        (s) =>
          s.name.toLowerCase().includes(needle) ||
          s.slug.toLowerCase().includes(needle) ||
          s.description_short.toLowerCase().includes(needle) ||
          s.domain_tags.some((t) => t.toLowerCase().includes(needle)),
      );
    }
    if (familyFilter) out = out.filter((s) => s.family === familyFilter);
    if (accessFilter) out = out.filter((s) => s.access.visibility === accessFilter);
    if (hasRewriter) out = out.filter((s) => s.rewriter.enabled);

    // Sort
    const sorted = [...out];
    if (sort === 'alpha') {
      sorted.sort((a, b) => a.name.localeCompare(b.name));
    } else if (sort === 'recent') {
      sorted.sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      );
    } else if (sort === 'score') {
      sorted.sort((a, b) => (bestScore(b)?.value ?? 0) - (bestScore(a)?.value ?? 0));
    }
    return sorted;
  }, [visible, q, familyFilter, accessFilter, hasRewriter, sort]);

  return (
    <>
      <PageSection variant="light">
        <Title headingLevel="h1">Catalog</Title>
        <p style={{ marginTop: '0.5rem', color: 'var(--pf-v5-global--Color--200)' }}>
          Browse retrieval sources. Click any card for details, eval scores, and a
          copy-paste MCP configuration.
        </p>
      </PageSection>
      <PageSection variant="light" style={{ paddingTop: 0 }}>
        <Toolbar>
          <ToolbarContent>
            <ToolbarItem style={{ minWidth: '20rem' }}>
              <SearchInput
                placeholder="Search by name, slug, description, tag..."
                value={q}
                onChange={(_e, v) => updateParam('q', v)}
                onClear={() => updateParam('q', null)}
              />
            </ToolbarItem>
            <ToolbarFilter
              chips={familyFilter ? [familyFilter] : []}
              deleteChip={() => updateParam('family', null)}
              categoryName="Family"
            >
              <Select
                isOpen={familyOpen}
                onOpenChange={(open) => setFamilyOpen(open)}
                onSelect={(_e, value) => {
                  updateParam('family', value as string);
                  setFamilyOpen(false);
                }}
                selected={familyFilter ?? undefined}
                toggle={(toggleRef) => (
                  <MenuToggle
                    ref={toggleRef}
                    onClick={() => setFamilyOpen(!familyOpen)}
                    isExpanded={familyOpen}
                  >
                    {familyFilter ?? 'Family: any'}
                  </MenuToggle>
                )}
              >
                <SelectList>
                  <SelectOption value="document">document</SelectOption>
                  <SelectOption value="clinical_document">clinical_document</SelectOption>
                  <SelectOption value="code">code</SelectOption>
                  <SelectOption value="tabular">tabular</SelectOption>
                  <SelectOption value="graph">graph</SelectOption>
                </SelectList>
              </Select>
            </ToolbarFilter>
            <ToolbarFilter
              chips={accessFilter ? [accessFilter] : []}
              deleteChip={() => updateParam('access', null)}
              categoryName="Access"
            >
              <Select
                isOpen={accessOpen}
                onOpenChange={(open) => setAccessOpen(open)}
                onSelect={(_e, value) => {
                  updateParam('access', value as string);
                  setAccessOpen(false);
                }}
                selected={accessFilter ?? undefined}
                toggle={(toggleRef) => (
                  <MenuToggle
                    ref={toggleRef}
                    onClick={() => setAccessOpen(!accessOpen)}
                    isExpanded={accessOpen}
                  >
                    {accessFilter ?? 'Access: any'}
                  </MenuToggle>
                )}
              >
                <SelectList>
                  <SelectOption value="public">public</SelectOption>
                  <SelectOption value="restricted">restricted</SelectOption>
                </SelectList>
              </Select>
            </ToolbarFilter>
            <ToolbarItem>
              <Checkbox
                label="Has rewriter"
                id="has-rewriter"
                isChecked={hasRewriter}
                onChange={(_e, checked) =>
                  updateParam('has_rewriter', checked ? 'true' : null)
                }
              />
            </ToolbarItem>
            <ToolbarGroup align={{ default: 'alignRight' }}>
              <ToolbarItem>
                <Select
                  isOpen={sortOpen}
                  onOpenChange={(open) => setSortOpen(open)}
                  onSelect={(_e, value) => {
                    updateParam('sort', value as string);
                    setSortOpen(false);
                  }}
                  selected={sort}
                  toggle={(toggleRef) => (
                    <MenuToggle
                      ref={toggleRef}
                      onClick={() => setSortOpen(!sortOpen)}
                      isExpanded={sortOpen}
                    >
                      Sort:{' '}
                      {sort === 'alpha'
                        ? 'Alphabetical'
                        : sort === 'recent'
                          ? 'Most recent'
                          : 'Best eval score'}
                    </MenuToggle>
                  )}
                >
                  <SelectList>
                    <SelectOption value="alpha">Alphabetical</SelectOption>
                    <SelectOption value="recent">Most recently updated</SelectOption>
                    <SelectOption value="score">Best eval score</SelectOption>
                  </SelectList>
                </Select>
              </ToolbarItem>
            </ToolbarGroup>
          </ToolbarContent>
        </Toolbar>
      </PageSection>
      <PageSection>
        {filtered.length === 0 ? (
          <EmptyState variant={EmptyStateVariant.lg}>
            <Title headingLevel="h2">No sources match your filters</Title>
            <EmptyStateBody>
              Try clearing the search box or removing a filter.
            </EmptyStateBody>
          </EmptyState>
        ) : (
          <Gallery
            hasGutter
            minWidths={{
              default: '280px',
              md: '320px',
              lg: '340px',
              xl: '360px',
            }}
          >
            {filtered.map((s) => (
              <SourceCard key={s.id} source={s} />
            ))}
          </Gallery>
        )}
      </PageSection>
    </>
  );
}
