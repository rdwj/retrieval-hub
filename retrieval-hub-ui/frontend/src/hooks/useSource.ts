import { useState, useEffect } from 'react';
import type { Source } from '../types/source';
import { fetchSource } from '../services/catalogApi';
import { MOCK_SOURCES } from '../data/mockSources';

export function useSource(slug: string) {
  const mockSource = MOCK_SOURCES.find((s) => s.slug === slug) ?? null;
  const [data, setData] = useState<Source | null>(mockSource);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isLive, setIsLive] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchSource(slug)
      .then((source) => {
        if (!cancelled && source) {
          setData(source);
          setIsLive(true);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e.message);
          // Keep mock source as fallback
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  return { data, loading, error, isLive };
}
