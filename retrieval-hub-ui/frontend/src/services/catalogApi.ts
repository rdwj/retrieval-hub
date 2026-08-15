import type { Source } from '../types/source';

const API_BASE = '/api';

export async function fetchSources(): Promise<Source[]> {
  const res = await fetch(`${API_BASE}/sources`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function fetchSource(slug: string): Promise<Source | null> {
  const res = await fetch(`${API_BASE}/sources/${slug}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
