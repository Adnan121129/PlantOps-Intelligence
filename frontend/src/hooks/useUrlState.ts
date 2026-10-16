import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Filter state stored in the URL query string, so filtered views are shareable and dashboard
 * drill-through links (e.g. /maintenance/work-orders?overdue=true) open pre-filtered.
 */
export function useUrlState<T extends Record<string, string>>(defaults: T) {
  const [params, setParams] = useSearchParams();
  const defaultsKey = JSON.stringify(defaults);
  const state = useMemo(() => {
    const base = JSON.parse(defaultsKey) as Record<string, string>;
    params.forEach((value, key) => {
      base[key] = value;
    });
    return base as T & Record<string, string>;
  }, [params, defaultsKey]);

  const update = useCallback((patch: Partial<Record<string, string | undefined>>, opts: { resetPage?: boolean } = {}) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(patch)) {
        if (v === undefined || v === "") next.delete(k);
        else next.set(k, v);
      }
      if (opts.resetPage !== false && !("page" in patch)) next.delete("page");
      return next;
    }, { replace: true });
  }, [setParams]);

  const reset = useCallback(() => setParams(new URLSearchParams(), { replace: true }), [setParams]);
  return [state, update, reset] as const;
}
