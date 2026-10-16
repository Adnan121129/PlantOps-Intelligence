import axios, { AxiosError } from "axios";

/** Reads Django's CSRF cookie. Session auth: the cookie is HttpOnly=false by design so the SPA can echo it. */
export function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name.replace(/[.$?*|{}()[\]\\/+^]/g, "\\$&")}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export const api = axios.create({ baseURL: "/api", withCredentials: true, timeout: 60_000 });

api.interceptors.request.use((config) => {
  const method = (config.method ?? "get").toLowerCase();
  if (!["get", "head", "options"].includes(method)) {
    const token = getCookie("csrftoken");
    if (token) config.headers.set("X-CSRFToken", token);
  }
  return config;
});

/** Session expiry: any API call rejected for missing credentials tells the auth layer to sign out. */
export const SESSION_EXPIRED_EVENT = "plantops:session-expired";
api.interceptors.response.use(undefined, (error) => {
  const status = error?.response?.status;
  const detail = String(error?.response?.data?.detail ?? "");
  const url = String(error?.config?.url ?? "");
  if ((status === 401 || status === 403) && /credentials were not provided|not authenticated/i.test(detail) && !url.includes("/auth/")) {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  }
  return Promise.reject(error);
});

export type FieldErrors = Record<string, string[]>;

export class ApiError extends Error {
  status: number;
  fieldErrors: FieldErrors;
  constructor(message: string, status: number, fieldErrors: FieldErrors = {}) {
    super(message);
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

function flatten(errors: unknown, prefix = ""): FieldErrors {
  const out: FieldErrors = {};
  if (Array.isArray(errors)) {
    if (errors.every((e) => typeof e === "string")) out[prefix || "non_field_errors"] = errors as string[];
    else errors.forEach((e, i) => Object.assign(out, flatten(e, prefix ? `${prefix}.${i}` : String(i))));
  } else if (errors && typeof errors === "object") {
    for (const [k, v] of Object.entries(errors as Record<string, unknown>)) {
      Object.assign(out, flatten(v, prefix ? `${prefix}.${k}` : k));
    }
  } else if (typeof errors === "string") {
    out[prefix || "non_field_errors"] = [errors];
  }
  return out;
}

export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  const ax = err as AxiosError<{ detail?: string; errors?: unknown }>;
  if (ax?.isAxiosError) {
    if (!ax.response) return new ApiError("Cannot reach the server. Check your connection and try again.", 0);
    const { status, data } = ax.response;
    const fieldErrors = data && typeof data === "object" ? flatten(data.errors ?? {}) : {};
    let message = (data && typeof data === "object" && data.detail) || "";
    if (!message || message === "Validation failed.") {
      const first = Object.entries(fieldErrors)[0];
      message = first ? (first[0] === "non_field_errors" ? first[1][0] : `${first[0]}: ${first[1][0]}`) : message;
    }
    if (!message) {
      message = status === 403 ? "You do not have permission to perform this action."
        : status === 404 ? "The record was not found." : status >= 500 ? "The server encountered an error." : "Request failed.";
    }
    return new ApiError(message, status, fieldErrors);
  }
  return new ApiError(err instanceof Error ? err.message : "Unexpected error", 0);
}

export async function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  try {
    const res = await api.get<T>(url, { params: clean(params) });
    return res.data;
  } catch (e) {
    throw toApiError(e);
  }
}

export async function send<T>(method: "post" | "patch" | "put" | "delete", url: string, body?: unknown): Promise<T> {
  try {
    const res = await api.request<T>({ method, url, data: body });
    return res.data;
  } catch (e) {
    throw toApiError(e);
  }
}

export function clean(params?: Record<string, unknown>): Record<string, unknown> | undefined {
  if (!params) return undefined;
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""));
}

/** Build a download URL for an export endpoint with the current filters. */
export function exportUrl(path: string, params: Record<string, unknown>): string {
  const query = new URLSearchParams(Object.entries(clean(params) ?? {}).map(([k, v]) => [k, String(v)]));
  return `/api${path}?${query.toString()}`;
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
    (Number(c) ^ (Math.random() * 16) >> (Number(c) / 4)).toString(16));
}
