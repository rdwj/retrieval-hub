// Lightweight formatters for the mockup. All dates are relative to "now".

export function relativeTime(iso: string | null): string {
  if (!iso) return 'never';
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diffSec = Math.round((now - then) / 1000);

  if (Number.isNaN(diffSec)) return 'unknown';

  // Future time (next refresh, etc.)
  if (diffSec < 0) {
    return formatRelativeFuture(-diffSec);
  }

  if (diffSec < 60) return 'just now';
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} minute${diffMin === 1 ? '' : 's'} ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr} hour${diffHr === 1 ? '' : 's'} ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 30) return `${diffDay} day${diffDay === 1 ? '' : 's'} ago`;
  const diffMo = Math.floor(diffDay / 30);
  if (diffMo < 12) return `${diffMo} month${diffMo === 1 ? '' : 's'} ago`;
  const diffYr = Math.floor(diffMo / 12);
  return `${diffYr} year${diffYr === 1 ? '' : 's'} ago`;
}

function formatRelativeFuture(diffSec: number): string {
  if (diffSec < 60) return 'in a moment';
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `in ${diffMin} minute${diffMin === 1 ? '' : 's'}`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `in ${diffHr} hour${diffHr === 1 ? '' : 's'}`;
  const diffDay = Math.floor(diffHr / 24);
  return `in ${diffDay} day${diffDay === 1 ? '' : 's'}`;
}

export function absoluteTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
}

export function formatNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return n.toLocaleString('en-US');
}

export function formatScore(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return n.toFixed(2);
}

export function formatSignedDelta(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}`;
}

export function formatLatencyHint(p50: number, p95: number): string {
  if (p50 === 0 && p95 === 0) return '—';
  return `~${Math.round(p50)}ms p50 · ~${Math.round(p95)}ms p95`;
}

export function familyDisplayName(family: string): string {
  switch (family) {
    case 'document':
      return 'Document';
    case 'clinical_document':
      return 'Clinical Doc';
    case 'code':
      return 'Code';
    case 'tabular':
      return 'Tabular';
    case 'graph':
      return 'Graph';
    case 'external':
      return 'External';
    default:
      return family;
  }
}

export function patternDisplayName(pattern: string): string {
  return pattern.replace(/_/g, ' ');
}
