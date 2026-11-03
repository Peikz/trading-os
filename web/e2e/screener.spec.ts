// Screener: All stocks and Scan hits, a filter, saving a screen, and flipping it on Today.
import { expect, open, test, TICKERS } from "./fixtures";

type Result = { count: number; tickers: string[]; rows: { ticker: string; grade?: string }[] };

test("All stocks: a filter narrows the list, a saved screen flips through on Today", async ({ page, request }) => {
  await open(page, "screener");
  const summary = page.locator(".screener section > p b").first();
  await expect(summary).toHaveText(`${TICKERS.length} stocks`); // the whole synthetic universe

  const filter = { field: "adr20_pct", op: ">=", value: 4 };
  const expected = (await (await request.post("/api/screener/run", {
    data: { filters: [filter], sort: "rs_pct" },
  })).json()) as Result;
  expect(expected.count).toBeGreaterThan(0);
  expect(expected.count).toBeLessThan(TICKERS.length); // the filter really drops stocks
  await page.getByRole("button", { name: "＋ Add filter" }).click();
  await expect(page.getByLabel("Field")).toHaveValue("adr20_pct");
  await expect(summary).toHaveText(`${expected.count} stocks`);
  await expect(page.locator(".screener tbody tr").first().locator("td").first()).toHaveText(expected.rows[0].ticker);

  await page.getByLabel("Screen name").fill("e2e wide ranges");
  await page.getByRole("button", { name: "Save screen" }).click();
  await expect(page.getByLabel("Screen", { exact: true })).toHaveValue("e2e wide ranges");
  const saved = (await (await request.get("/api/screens")).json()) as Record<string, unknown>;
  expect(Object.keys(saved)).toContain("e2e wide ranges");

  await page.getByRole("button", { name: `📈 Flip through on Today (${expected.count})` }).click();
  await expect(page.getByLabel("Show")).toHaveValue("push");
  await expect(page.getByLabel("Show").locator("option:checked")).toHaveText("From the screen: e2e wide ranges");
  await expect(page.getByRole("navigation", { name: "Flip through" }).locator("span")).toHaveText(
    `1 of ${expected.count}`,
  );
  await expect(page.locator("article.card .ticker")).toHaveText(expected.rows[0].ticker);
});

test("Scan hits: a run's scan with its grades and the grading form", async ({ page }) => {
  await open(page, "screener");
  await page.getByRole("group", { name: "Stocks from" }).getByRole("button", { name: "Scan hits" }).click();
  const scan = page.getByLabel("Scan", { exact: true });
  await expect(scan).toBeVisible();
  const answer = page.waitForResponse((r) => r.url().endsWith("/api/screener/run") && r.request().method() === "POST");
  await scan.selectOption({ index: 0 });
  const hits = (await (await answer).json()) as Result;
  await expect(page.locator(".screener tbody tr")).toHaveCount(hits.rows.length);
  expect(hits.rows.length).toBeGreaterThan(0);
  await expect(page.locator(".screener tbody .badge").first()).toHaveText(hits.rows[0].grade ?? "");
  const form = page.getByLabel("Grading form");
  await expect(form).toBeVisible();
  await form.getByRole("radiogroup").locator("label", { hasText: /^B$/ }).click();
  await form.getByLabel("Notes").fill("e2e: graded from the Screener");
  await form.getByRole("button", { name: "Save" }).click();
  await expect(form.locator("p.ok")).toContainText("Saved");
});
