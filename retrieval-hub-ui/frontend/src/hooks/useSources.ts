import { useState, useEffect } from 'react';
import type { Source } from '../types/source';
import { fetchSources } from '../services/catalogApi';
import { MOCK_SOURCES } from '../data/mockSources';

export function useSources() {
  const [data, setData] = useState<Source[]>(MOCK_SOURCES);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isLive, setIsLive] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchSources()
      .then((sources) => {
        if (!cancelled) {
          setData(sources);
          setIsLive(true);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e.message);
          // Keep MOCK_SOURCES as fallback
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { data, loading, error, isLive };
}
