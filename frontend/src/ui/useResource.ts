import { useCallback, useEffect, useState } from "react";
export interface Resource<T> {
  data: T | null;
  loading: boolean;
  error: boolean;
  received: string | null;
}
export function useResource<T>(fetcher: (signal: AbortSignal) => Promise<T>) {
  const [revision, setRevision] = useState(0);
  const [resource, setResource] = useState<Resource<T>>({
    data: null,
    loading: true,
    error: false,
    received: null,
  });
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    setResource((old) => ({ ...old, loading: true, error: false }));
    fetcher(controller.signal)
      .then((data) => {
        if (active)
          setResource({
            data,
            loading: false,
            error: false,
            received: new Date().toISOString(),
          });
      })
      .catch(() => {
        if (active)
          setResource((old) => ({ ...old, loading: false, error: true }));
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [fetcher, revision]);
  const refresh = useCallback(() => setRevision((n) => n + 1), []);
  return { ...resource, refresh };
}
