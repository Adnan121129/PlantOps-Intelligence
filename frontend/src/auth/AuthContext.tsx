import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { get, send, SESSION_EXPIRED_EVENT } from "@/api/client";
import type { Me } from "@/api/types";

interface AuthState {
  user: Me | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<Me>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  can: (permission: string) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setUser(await get<Me>("/auth/me/"));
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const expired = () => setUser(null);
    window.addEventListener(SESSION_EXPIRED_EVENT, expired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, expired);
  }, []);

  useEffect(() => {
    // Ensure a CSRF cookie exists before any write, then load the session user.
    get("/auth/csrf/").catch(() => undefined).finally(refresh);
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    await get("/auth/csrf/");
    const me = await send<Me>("post", "/auth/login/", { username, password });
    setUser(me);
    return me;
  }, []);

  const logout = useCallback(async () => {
    try {
      await send("post", "/auth/logout/");
    } finally {
      setUser(null);
      await get("/auth/csrf/").catch(() => undefined);
    }
  }, []);

  const can = useCallback((permission: string) => !!user?.permissions.includes(permission), [user]);
  const value = useMemo(() => ({ user, loading, login, logout, refresh, can }), [user, loading, login, logout, refresh, can]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** Renders children only when the user holds the permission (presentation only; the API enforces it). */
export function Can({ perm, children, fallback = null }: { perm: string | string[]; children: ReactNode; fallback?: ReactNode }) {
  const { can } = useAuth();
  const perms = Array.isArray(perm) ? perm : [perm];
  return <>{perms.some(can) ? children : fallback}</>;
}
