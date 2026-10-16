import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/api/client";

const sendMock = vi.fn();
vi.mock("@/api/client", async (orig) => {
  const actual = await orig<typeof import("@/api/client")>();
  return { ...actual, send: (...a: unknown[]) => sendMock(...a) };
});
const { ResourceFormDialog } = await import("@/components/data");

const fields = [
  { name: "code", label: "Code", required: true },
  { name: "amount", label: "Amount", type: "number" as const, required: true },
  { name: "notes", label: "Notes", type: "textarea" as const },
];

describe("ResourceFormDialog", () => {
  beforeEach(() => { sendMock.mockClear(); });

  it("validates required fields before calling the API", async () => {
    render(<ResourceFormDialog open onClose={() => undefined} title="New thing" endpoint="/things/" fields={fields} onSaved={() => undefined} />);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getAllByText("This field is required.")).toHaveLength(2);
    expect(sendMock).not.toHaveBeenCalled();
  });

  it("shows server-side field errors next to the field", async () => {
    sendMock.mockImplementation(async () => {
      throw new ApiError("amount: Amount must be greater than zero.", 400, { amount: ["Amount must be greater than zero."] });
    });
    render(<ResourceFormDialog open onClose={() => undefined} title="New thing" endpoint="/things/" fields={fields} onSaved={() => undefined} />);
    await userEvent.type(screen.getByLabelText(/code/i), "X1");
    await userEvent.type(screen.getByLabelText(/amount/i), "-5");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findAllByText(/greater than zero/)).not.toHaveLength(0);
    expect(screen.getByLabelText(/amount/i)).toHaveAttribute("aria-invalid", "true");
    expect(sendMock.mock.calls[0]).toEqual(["post", "/things/", { code: "X1", amount: "-5", notes: "" }]);
  });

  it("submits a PATCH for an existing record and reports success", async () => {
    const saved = vi.fn();
    const close = vi.fn();
    sendMock.mockResolvedValue({ id: 7 });
    render(<ResourceFormDialog open onClose={close} title="Edit" endpoint="/things/" fields={fields} id={7}
      initial={{ code: "A", amount: 2, notes: "" }} onSaved={saved} />);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(sendMock).toHaveBeenCalledWith("patch", "/things/7/", { code: "A", amount: 2, notes: "" });
    expect(saved).toHaveBeenCalledWith({ id: 7 });
    expect(close).toHaveBeenCalled();
  });
});
