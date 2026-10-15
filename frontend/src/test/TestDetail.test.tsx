import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { planVsActual, testDetail } from "./fixtures";
import { mockApi, renderAt } from "./mockApi";

describe("test detail", () => {
  it("renders planned and actual groups, statuses and unexpected runs", async () => {
    mockApi({ "/tests/21": testDetail, "/tests/21/plan-vs-actual": planVsActual, "/tests/21/objectives": [] });
    renderAt("/tests/21");
    expect(await screen.findByRole("heading", { name: "Autocross and skidpad" })).toBeInTheDocument();
    expect(screen.getByText("Rain shower", { selector: "dd" })).toBeInTheDocument();

    const table = await screen.findByRole("table", { name: "Planned runs and their actual attempts" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(within(rows[0]!).getByText("Executed")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Repeated attempts")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("differs: Lap count")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Cancelled")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Cancelled: Rain shower")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Replaced")).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "Unexpected runs" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Run 2" })).toHaveAttribute("href", "/runs/13");
    expect(screen.getByText("No objectives are linked to this test.")).toBeInTheDocument();
  });

  it("shows a clear state for a missing test", async () => {
    mockApi({
      "/tests/999": () => ({ status: 404, body: { error: { code: "test_not_found", message: "Test 999 was not found.", details: [] } } }),
    });
    renderAt("/tests/999");
    expect(await screen.findByRole("heading", { name: "Test not found" })).toBeInTheDocument();
  });
});
