import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Screener } from "./Screener";

const A = ["W", "Z", "Q", "W"].join(""); // synthetic

const meta = {
  fields: {
    adr20_pct: { label: "ADR % (20d)", kind: "pct", group: "Volatility" },
    rs_pct: { label: "RS percentile (1-99)", kind: "num", group: "Performance" },
  },
  ops: { num: [">=", "<=", "between"], pct: [">=", "<=", "between"], money: [], bool: [], text: [] },
  shown: ["ticker", "adr20_pct"],
  examples: { "Momentum leaders": { filters: [{ field: "adr20_pct", op: ">=", value: 4 }], sort: "rs_pct", descending: true } },
  saved: {},
  labels: {},
};

const posts: unknown[] = [];
beforeEach(() => {
  posts.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      let body: unknown = [];
      if (url === "/api/screener/meta") body = meta;
      if (url === "/api/screener/run") {
        posts.push(JSON.parse(String(init?.body)));
        body = {
          count: 1,
          when: "the 30 Oct close",
          summary: "ADR % (20d) >= 4",
          columns: ["ticker", "adr20_pct"],
          rows: [{ ticker: A, adr20_pct: 5.25 }],
        };
      }
      if (url.startsWith("/api/screens/")) body = { Mine: meta.examples["Momentum leaders"] };
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
});

describe("Screener", () => {
  it("runs an example screen and shows the result table", async () => {
    render(<Screener />);
    await screen.findByLabelText("Screen");
    fireEvent.change(screen.getByLabelText("Screen"), {
      target: { value: "Example: Momentum leaders" },
    });
    await waitFor(() =>
      expect(posts.some((p) => (p as { filters: unknown[] }).filters.length === 1)).toBe(true),
    );
    expect(await screen.findByText(A)).toBeInTheDocument();
    expect(screen.getByText("+5.3%")).toBeInTheDocument();
    expect(screen.getByText("1 stocks")).toBeInTheDocument();
  });

  it("saves a screen under a name", async () => {
    render(<Screener />);
    fireEvent.change(await screen.findByLabelText("Screen name"), { target: { value: "Mine" } });
    fireEvent.click(screen.getByText("Save screen"));
    expect(await screen.findByText("Delete 'Mine'")).toBeInTheDocument();
  });
});
