// The Screener: "Screener" (every stock, a filter chip, a saved screen from the Screen menu, the
// column views, the preview panel) and "Scan hits" (a run of today or all of them, the scan and
// grade filters, the stock on the Chart and the grading form).
import { expect, open, test, TICKERS } from "./fixtures";

type Result = { count: number; tickers: string[]; rows: { ticker: string; grade?: string }[] };
type Hits = { count: number; rows: { ticker: string; scan: string; grade: string }[]; scans: { id: string }[] };

test("Screener: a filter chip narrows the list, a saved screen is kept in the Screen menu", async ({ page, request }) => {
  await open(page, "screener/screen");
  const count = page.locator(".filter-bar .fb-count");
  await expect(count).toHaveText(new RegExp(`^${TICKERS.length} stocks · `)); // the whole synthetic universe
  await expect(page.getByRole("table", { name: "Results" }).locator("tbody tr")).toHaveCount(TICKERS.length);

  const filter = { field: "adr20_pct", op: ">=", value: 4 };
  const expected = (await (await request.post("/api/screener/run", {
    data: { filters: [filter], sort: "rs_pct" },
  })).json()) as Result;
  expect(expected.count).toBeGreaterThan(0);
  expect(expected.count).toBeLessThan(TICKERS.length); // the filter really drops stocks
  await page.getByRole("button", { name: "+ Filter" }).click();
  await page.getByRole("dialog", { name: "Add a filter" }).getByRole("button", { name: "Add filter" }).click();
  await expect(page.locator(".filter-bar .fchip")).toHaveText(["Daily range % >= 4"]);
  await expect(count).toHaveText(new RegExp(`^${expected.count} stocks? · `));
  await expect(page.getByRole("table", { name: "Results" }).locator("tbody tr").first().locator("td").first()).toContainText(
    expected.rows[0].ticker,
  );

  // The column views and the preview of the selected row
  await page.getByRole("tab", { name: "Technical" }).click();
  await expect(page.getByRole("columnheader", { name: "From high" })).toBeVisible();
  await page.getByRole("tab", { name: "Overview" }).click();
  const preview = page.getByLabel("Preview");
  await expect(preview).toContainText(expected.rows[0].ticker);
  await page.keyboard.press("ArrowDown");
  await expect(preview).toContainText(expected.rows[1].ticker);

  // Save it from the Screen menu, find it there, delete it
  await page.getByRole("button", { name: /^Screen/ }).click();
  await page.getByLabel("Screen name").fill("e2e wide ranges");
  await page.getByRole("listbox", { name: "Screen" }).getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("button", { name: /^Screen\s*e2e wide ranges/ })).toBeVisible();
  const saved = (await (await request.get("/api/screens")).json()) as Record<string, unknown>;
  expect(Object.keys(saved)).toContain("e2e wide ranges");
  await page.getByRole("button", { name: /^Screen/ }).click();
  await page.getByRole("button", { name: "Delete screen e2e wide ranges" }).click();
  await expect(page.getByRole("button", { name: /^Screen\s*All stocks/ })).toBeVisible();
  const after = (await (await request.get("/api/screens")).json()) as Record<string, unknown>;
  expect(Object.keys(after)).not.toContain("e2e wide ranges");
});

test("Charts: the grid of mini charts draws its candles", async ({ page }) => {
  await open(page, "screener/screen");
  await page.getByRole("group", { name: "View" }).getByRole("button", { name: "Charts" }).click();
  await expect(page.getByRole("button", { name: /^Open / })).toHaveCount(TICKERS.length);
  await expect(page.locator(".chart-grid svg.mini rect").first()).toBeVisible();
  await page.getByRole("group", { name: "View" }).getByRole("button", { name: "Table" }).click();
});

test("Scan hits: today's runs, the scan and grade filters, the stock on the Chart and the grading form", async ({ page, request }) => {
  const hits = (await (await request.get("/api/scan-hits?run=all")).json()) as Hits;
  expect(hits.rows.length).toBeGreaterThan(0);
  await open(page, "screener/hits");
  const table = page.getByRole("table", { name: "Results" });
  await expect(table.locator("tbody tr")).toHaveCount(hits.rows.length);
  await expect(page.locator(".filter-bar .fb-count")).toHaveText(`${hits.rows.length} ${hits.rows.length === 1 ? "hit" : "hits"}`);
  await expect(table.locator("tbody .badge").first()).toHaveText(hits.rows[0].grade);

  // The run picker is the one on Today; the grade filter narrows the rows
  await page.getByRole("button", { name: /^Run All today/ }).click();
  await expect(page.getByRole("listbox", { name: "Run" }).getByRole("option").first()).toContainText("All today");
  await page.keyboard.press("Escape");
  const graded = hits.rows.filter((r) => r.grade === "B").length;
  await page.getByRole("group", { name: "Grade" }).getByRole("button", { name: "B", exact: true }).click();
  await expect(table.locator("tbody tr")).toHaveCount(graded);
  await page.getByRole("group", { name: "Grade" }).getByRole("button", { name: "All", exact: true }).click();
  await expect(table.locator("tbody tr")).toHaveCount(hits.rows.length);

  // Enter opens the selected row on the Chart; a graded hit has its grading form in the Journal tab
  const first = hits.rows[0];
  await page.keyboard.press("Enter");
  await expect(page.locator(".ws-bar .ticker")).toHaveText(first.ticker);
  await page.getByRole("tab", { name: "Journal", exact: true }).click();
  const form = page.getByLabel("Grading form");
  await expect(form).toBeVisible();
  await form.getByRole("radiogroup").locator("label", { hasText: /^B$/ }).click();
  await form.getByLabel("Notes").fill("e2e: graded from the Chart");
  await form.getByRole("button", { name: "Save" }).click();
  await expect(form.locator("p.ok")).toContainText("Saved");
  await page.goBack();
  await expect(table).toBeVisible();
});
