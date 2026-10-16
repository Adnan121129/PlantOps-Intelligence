export interface Paged<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export type Role = "ADMIN" | "OPERATIONS" | "MAINTENANCE" | "STORE" | "SUPERVISOR" | "MANAGEMENT";

export interface Me {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  display_name: string;
  email: string;
  role: Role;
  role_label: string;
  job_title: string;
  department: number | null;
  assigned_unit_ids: number[];
  theme_preference: "light" | "dark" | "system";
  permissions: string[];
  last_login: string | null;
}

export interface Kpi {
  code: string;
  label: string;
  value: number | null;
  unit: string | null;
  period_type: "period" | "snapshot";
  definition: string;
  formula: string;
  notes: string;
  status: "ok" | "insufficient_data" | "low_confidence";
  detail: Record<string, unknown>;
  link: string | null;
}

export interface PeriodInfo {
  date_from: string;
  date_to: string;
  timezone: string;
  days: number;
}

export interface Unit { id: number; plant: number; plant_code: string; code: string; name: string; unit_type: string; is_active: boolean; requires_shift_reports: boolean }
export interface Option { value: string | number; label: string }
