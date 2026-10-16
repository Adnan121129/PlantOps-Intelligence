import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ApiError, toApiError } from "@/api/client";
import type { Kpi } from "@/api/types";
import { KpiCard } from "@/components/charts";
import { DataTable, Pagination } from "@/components/data";
import { PeriodFilter, presetRange } from "@/components/PeriodFilter";

vi.mock("@/lib/ReferenceContext", () => ({
  useReference: () => ({ units: [{ id: 1, code: "GT1", name: "Gas Turbine 1" }], timeZone: "UTC", currency: "USD" }),
}));

const kpi = (over: Partial<Kpi> = {}): Kpi => ({
  code: "mttr_hours", label: "MTTR", value: 4.25, unit: "h", period_type: "period", definition: "Mean time to repair.",
  formula: "AVG(ended_at - started_at)", notes: "", status: "ok", detail: {}, link: "/maintenance/downtime", ...over,
});

describe("DataTable", () => {
  const columns = [{ key: "name", header: "Name" }];
  it("shows an empty state", () => {
    render(<DataTable columns={columns} rows={[]} rowKey={(r: { name: string }) => r.name} />);
    expect(screen.getByText("No records found")).toBeInTheDocument();
  });
  it("shows an error state with retry", async () => {
    const retry = vi.fn();
    render(<DataTable columns={columns} rows={undefined} error={new ApiError("Server unavailable", 500)} onRetry={retry} rowKey={() => 1} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Server unavailable");
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(retry).toHaveBeenCalled();
  });
  it("shows a loading skeleton then rows", () => {
    const { rerender, container } = render(<DataTable columns={columns} rows={undefined} loading rowKey={() => 1} />);
    expect(container.querySelectorAll("[aria-hidden=true].animate-pulse").length).toBeGreaterThan(0);
    rerender(<DataTable columns={columns} rows={[{ name: "Pump A" }]} rowKey={(r) => r.name} />);
    expect(screen.getByText("Pump A")).toBeInTheDocument();
  });
  it("requests server-side sorting", async () => {
    const onOrder = vi.fn();
    render(<DataTable columns={[{ key: "name", header: "Name", sortKey: "name" }]} rows={[{ name: "x" }]} rowKey={(r) => r.name} ordering="name" onOrder={onOrder} />);
    await userEvent.click(screen.getByRole("button", { name: /name/i }));
    expect(onOrder).toHaveBeenCalledWith("-name");
  });
});

describe("Pagination", () => {
  it("moves between pages", async () => {
    const onPage = vi.fn();
    render(<Pagination count={60} page={2} pageSize={25} onPage={onPage} />);
    expect(screen.getByText("26–50 of 60")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(onPage).toHaveBeenCalledWith(3);
    await userEvent.click(screen.getByRole("button", { name: /previous/i }));
    expect(onPage).toHaveBeenCalledWith(1);
  });
});

describe("KpiCard", () => {
  it("renders value, unit and an expandable definition", async () => {
    render(<MemoryRouter><KpiCard kpi={kpi()} /></MemoryRouter>);
    expect(screen.getByText("4.25")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /definition of mttr/i }));
    expect(screen.getByText("Mean time to repair.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view records behind mttr/i })).toHaveAttribute("href", "/maintenance/downtime");
  });
  it("never shows zero for insufficient data", () => {
    render(<MemoryRouter><KpiCard kpi={kpi({ value: null, status: "insufficient_data" })} /></MemoryRouter>);
    expect(screen.getByText("Insufficient data")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });
});

describe("PeriodFilter", () => {
  it("applies presets and unit filters", async () => {
    const onChange = vi.fn();
    render(<PeriodFilter value={{ ...presetRange("30"), unit: "" }} onChange={onChange} />);
    await userEvent.selectOptions(screen.getByLabelText("Period"), "7");
    expect(onChange).toHaveBeenCalledWith(presetRange("7"));
    await userEvent.selectOptions(screen.getByLabelText("Plant unit"), "1");
    expect(onChange).toHaveBeenCalledWith({ unit: "1" });
  });
  it("computes inclusive date ranges", () => {
    const r = presetRange("7");
    const days = (Date.parse(r.date_to) - Date.parse(r.date_from)) / 86400000 + 1;
    expect(days).toBe(7);
  });
});

describe("API error normalisation", () => {
  it("maps DRF validation payloads to field errors", () => {
    const err = toApiError({ isAxiosError: true, response: { status: 400, data: { detail: "Validation failed.", errors: { quantity: ["Insufficient stock: 2 EA available."] } } } });
    expect(err.status).toBe(400);
    expect(err.fieldErrors.quantity[0]).toContain("Insufficient stock");
    expect(err.message).toBe("quantity: Insufficient stock: 2 EA available.");
  });
  it("reports network failures clearly", () => {
    expect(toApiError({ isAxiosError: true }).message).toMatch(/cannot reach the server/i);
  });
});
