import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useApi } from "@/hooks/useApi";
import type { Unit } from "@/api/types";
import { configureFormatting } from "./format";

interface Plant { id: number; code: string; name: string; timezone: string; currency: string }
interface Department { id: number; code: string; name: string; is_active: boolean }
interface Setting { key: string; value: unknown }

interface Reference {
  plants: Plant[];
  units: Unit[];
  departments: Department[];
  defaultPlant: Plant | null;
  currency: string;
  timeZone: string;
  ready: boolean;
  reload: () => void;
}

const Ctx = createContext<Reference | null>(null);

/** Small, rarely-changing reference data shared by every page (plants, units, departments, settings). */
export function ReferenceProvider({ children }: { children: ReactNode }) {
  const plants = useApi<{ results: Plant[] } | Plant[]>("/core/plants/", { page_size: 200 });
  const units = useApi<Unit[]>("/core/units/");
  const departments = useApi<Department[]>("/core/departments/");
  const settings = useApi<Setting[]>("/core/settings/");

  const value = useMemo<Reference>(() => {
    const plantList = Array.isArray(plants.data) ? plants.data : plants.data?.results ?? [];
    const code = settings.data?.find((s) => s.key === "default_plant_code")?.value as string | undefined;
    const currency = (settings.data?.find((s) => s.key === "base_currency")?.value as string) ?? "USD";
    const defaultPlant = plantList.find((p) => p.code === code) ?? plantList[0] ?? null;
    // Configure synchronously so the very first render already formats in the plant time zone.
    configureFormatting({ timeZone: defaultPlant?.timezone ?? "UTC", currency });
    return {
      plants: plantList, units: units.data ?? [], departments: departments.data ?? [], defaultPlant, currency,
      timeZone: defaultPlant?.timezone ?? "UTC",
      ready: !plants.loading && !units.loading && !settings.loading,
      reload: () => { plants.reload(); units.reload(); departments.reload(); settings.reload(); },
    };
  }, [plants, units, departments, settings]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useReference(): Reference {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useReference must be used inside ReferenceProvider");
  return ctx;
}
