import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Alert, Button, Field, Icon, Input } from "@/components/ui";
import { ThemeToggle } from "@/components/layout/AppShell";

export default function LoginPage() {
  const { user, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  if (user) return <Navigate to={from} replace />;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) { setError("Enter your username and password."); return; }
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center bg-page p-4">
      <div className="absolute right-4 top-4"><ThemeToggle /></div>
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-md bg-accent text-accent-ink"><Icon name="factory" size={18} /></span>
          <div>
            <h1 className="text-base font-semibold">PlantOps Intelligence</h1>
            <p className="text-xs text-muted">Plant operations MIS &amp; business intelligence</p>
          </div>
        </div>
        <form onSubmit={submit} className="card space-y-3 p-5" noValidate>
          <h2 className="text-sm font-semibold">Sign in</h2>
          {error && <Alert tone="bad">{error}</Alert>}
          <Field label="Username" htmlFor="username">
            <Input id="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          </Field>
          <Field label="Password" htmlFor="password">
            <Input id="password" type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <Button type="submit" variant="primary" className="w-full" loading={busy}>Sign in</Button>
        </form>
        <p className="mt-4 text-center text-xs text-muted">
          Demo accounts: admin, operations, maintenance, store, supervisor, manager (see README for the demo password).
        </p>
      </div>
    </div>
  );
}
