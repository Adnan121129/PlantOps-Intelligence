import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, get, toApiError } from "@/api/client";

export interface ApiState<T> {
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
  setData: (d: T) => void;
}

/** GET a resource whenever `url` or `params` change. Pass url=null to skip. */
export function useApi<T>(url: string | null, params?: Record<string, unknown>): ApiState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState<boolean>(!!url);
  const [tick, setTick] = useState(0);
  const key = JSON.stringify(params ?? {});
  const seq = useRef(0);

  useEffect(() => {
    if (!url) {
      setLoading(false);
      return;
    }
    const mine = ++seq.current;
    setLoading(true);
    setError(null);
    get<T>(url, JSON.parse(key))
      .then((d) => mine === seq.current && setData(d))
      .catch((e) => mine === seq.current && setError(toApiError(e)))
      .finally(() => mine === seq.current && setLoading(false));
  }, [url, key, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload, setData };
}
