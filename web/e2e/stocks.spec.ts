// Stocks (the Screener's twin): All stocks with a filter chip, a saved screen flipped through on
// Today, the grid and the table, and a scan's hits with their grades and the grading form.
import { expect, open, test, TICKERS } from "./fixtures";

type Result = { count: number; tickers: string[]; rows: { ticker: string; grade?: string }[] };

test("All stocks: a filter narrows the list, a saved screen flips through on Today", async ({ page, request }) => {
  await open(page, "stocks?src=all");
  const count = page.locator(".stocks-main .toolbar .muted").first();
  await expect(count).toHaveText(new RegExp(`^${TICKERS.length} stocks · `)); // the whole synthetic universe
  await expect(page.getByRole("button", { name: /^Open / })).toHaveCount(TICKERS.length); // the grid

  const filter = { field: "adr20_pct", op: ">=", value: 4 };
  const expected = (await (await request.post("/api/screener/run", {
    data: { filters: [filter], sort: "rs_pct" },
  })).json()) as Result;
  expect(expected.count).toBeGreaterThan(0);
  expect(expected.count).toBeLessThan(TICKERS.length); // the filter really drops stocks
  await page.getByLabel("Filters").getByRole("button", { name: "Filter", exact: true }).click();
  await expect(page.getByLabel("Filters").locator(".chip")).toHaveText(["Daily range % >= 4"]);
  await expect(count).toHaveText(new RegExp(`^${expected.count} stocks? · `));
  await page.getByRole("group", { name: "View" }).getByRole("button", { name: /Table/ }).click();
  await expect(page.getByRole("table", { name: "Results" }).locator("tbody tr").first().locator("td").first()).toHaveText(
    expected.rows[0].ticker,
  );

  await page.getByRole("button", { name: "Save screen" }).click();
  await page.getByLabel("Screen name").fill("e2e wide ranges");
  await page.getByRole("dialog", { name: "Save screen" }).getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("navigation", { name: "Sources" }).getByRole("button", { name: "e2e wide ranges" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  const saved = (await (await request.get("/api/screens")).json()) as Record<string, unknown>;
  expect(Object.keys(saved)).toContain("e2e wide ranges");

  await page.getByRole("button", { name: `Flip through on Today (${expected.count})` }).click();
  const queue = page.getByRole("navigation", { name: "Queue" });
  await expect(queue.locator(".section-label").first()).toContainText("From the screen: e2e wide ranges");
  await expect(queue.locator(".queue button").first()).toContainText(expected.rows[0].ticker);
  await expect(page.getByLabel(`${expected.rows[0].ticker} screen`)).toContainText("no grade, no buy");
  await page.waitForLoadState("networkidle");
});

test("Scan hits: a run's scan with its grades, a stock's chart and the grading form", async ({ page }) => {
  const answer = page.waitForResponse((r) => r.url().endsWith("/api/screener/run") && r.request().method() === "POST");
  await open(page, "stocks?src=scans");
  const hits = (await (await answer).json()) as Result;
  expect(hits.rows.length).toBeGreaterThan(0);
  await page.getByRole("group", { name: "View" }).getByRole("button", { name: /Table/ }).click();
  const table = page.getByRole("table", { name: "Results" });
  await expect(table.locator("tbody tr")).toHaveCount(hits.rows.length);
  await expect(table.locator("tbody .badge").first()).toHaveText(hits.rows[0].grade ?? "");
  await table.locator("tbody tr").first().click();
  await expect(page.getByLabel(`${hits.rows[0].ticker} full chart`)).toBeVisible();
  const form = page.getByLabel("Grading form");
  await expect(form).toBeVisible();
  await form.getByRole("radiogroup").locator("label", { hasText: /^B$/ }).click();
  await form.getByLabel("Notes").fill("e2e: graded from Stocks");
  await form.getByRole("button", { name: "Save" }).click();
  await expect(form.locator("p.ok")).toContainText("Saved");
  // Back to the hits, the grid shows again
  await page.getByRole("button", { name: /^Back to / }).click();
  await expect(table).toBeVisible();
});
