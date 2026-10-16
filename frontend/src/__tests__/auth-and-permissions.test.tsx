import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { Me } from "@/api/types";

const getMock = vi.fn();
vi.mock("@/api/client", async (orig) => {
  const actual = await orig<typeof import("@/api/client")>();
  return { ...actual, get: (...args: unknown[]) => getMock(...args), send: vi.fn() };
});

const { AuthProvider, Can } = await import("@/auth/AuthContext");
const { RequireAuth, RequirePerm } = await import("@/App");

const user = (perms: string[]): Me => ({
  id: 1, username: "u", first_name: "", last_name: "", display_name: "U", email: "", role: "OPERATIONS", role_label: "Operations Officer",
  job_title: "", department: null, assigned_unit_ids: [], theme_preference: "system", permissions: perms, last_login: null,
});

function renderAt(path: string, ui: React.ReactNode) {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<p>login page</p>} />
          <Route path="/secret" element={<RequireAuth>{ui}</RequireAuth>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

describe("protected routes and permission-aware UI", () => {
  beforeEach(() => getMock.mockReset());

  it("redirects anonymous users to the login page", async () => {
    getMock.mockImplementation((url: string) => (url === "/auth/me/" ? Promise.reject(new Error("403")) : Promise.resolve({})));
    renderAt("/secret", <p>secret content</p>);
    expect(await screen.findByText("login page")).toBeInTheDocument();
    expect(screen.queryByText("secret content")).not.toBeInTheDocument();
  });

  it("renders protected content for a signed-in user", async () => {
    getMock.mockImplementation((url: string) => Promise.resolve(url === "/auth/me/" ? user([]) : {}));
    renderAt("/secret", <p>secret content</p>);
    expect(await screen.findByText("secret content")).toBeInTheDocument();
  });

  it("hides actions and pages the role does not hold", async () => {
    getMock.mockImplementation((url: string) => Promise.resolve(url === "/auth/me/" ? user(["opsreports.edit"]) : {}));
    renderAt("/secret", <>
      <Can perm="opsreports.edit"><button>New report</button></Can>
      <Can perm="opsreports.review"><button>Approve</button></Can>
      <RequirePerm perm="users.manage"><p>user admin</p></RequirePerm>
    </>);
    expect(await screen.findByRole("button", { name: "New report" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument());
    expect(screen.getByText("Access restricted")).toBeInTheDocument();
    expect(screen.queryByText("user admin")).not.toBeInTheDocument();
  });
});
