// Journal: log a fill by hand, import a broker CSV, a daily note, and every tab.
import type { APIRequestContext, Page } from "@playwright/test";
import { expect, open, test, TICKERS } from "./fixtures";

const tab = (page: Page, name: string) => page.getByRole("tab", { name, exact: true }).click();
const json = async <T>(request: APIRequestContext, path: string) => (await (await request.get(path)).json()) as T;

test("log a fill: the entry opens a position", async ({ page, request }) => {
  const t = TICKERS[7];
  const before = await json<{ totals: { positions: number } }>(request, "/api/journal/open");
  await open(page, "journal");
  await tab(page, "Log a trade");
  await page.getByLabel("Ticker", { exact: true }).fill(t);
  await page.getByLabel("Side").selectOption("buy");
  await page.getByLabel("Shares", { exact: true }).fill("10");
  await page.getByLabel("Price", { exact: true }).fill("12.5");
  await page.getByLabel("Initial stop (entries)").fill("11.75");
  await page.getByRole("button", { name: "Save fill" }).click();
  await expect(page.locator("p.ok")).toHaveText(`Saved: buy 10 ${t} @ 12.5.`);

  await tab(page, "Open positions");
  const after = await json<{ totals: { positions: number } }>(request, "/api/journal/open");
  expect(after.totals.positions).toBeGreaterThanOrEqual(before.totals.positions); // new, or added to
  await expect(page.locator(".metric", { hasText: "Open positions" })).toContainText(String(after.totals.positions));
  await expect(page.getByRole("table", { name: "Open positions" })).toContainText(t);
});

test("a broker CSV import adds fills and closes a trade", async ({ page, request }) => {
  const t = TICKERS[3];
  type Closed = { trades: { ticker: string }[] };
  const closedOf = async () =>
    (await json<Closed>(request, "/api/journal/closed")).trades.filter((x) => x.ticker === t).length;
  const before = await closedOf();
  const csv = [
    "trade_date,ticker,side,quantity,price,fees",
    `2026-06-01,${t},buy,100,10.0,1`,
    `2026-06-10,${t},sell,100,11.0,1`,
  ].join("\n");
  await open(page, "journal");
  await page.getByText("Import broker fills (CSV)").click();
  await page.getByLabel("Fills export").setInputFiles({ name: "fills.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await expect(page.locator("details p.ok")).toBeVisible();
  // The fixture has no trade in this stock: the import closes one. (A rerun on the same repo
  // overlaps the first import's dates, and the journal rightly keeps that as one trade.)
  expect(await closedOf()).toBe(Math.max(before, 1));
  await tab(page, "Closed trades");
  await expect(page.getByRole("table", { name: "Closed trades" })).toContainText(t);
});

test("a CSV without the mapped columns says what is missing", async ({ page, guard }) => {
  guard.allow(/^\/api\/journal\/import$/, 400);
  await open(page, "journal");
  await page.getByText("Import broker fills (CSV)").click();
  await page.getByLabel("Fills export").setInputFiles({ name: "bad.csv", mimeType: "text/csv", buffer: Buffer.from("a,b\n1,2\n") });
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await expect(page.locator("details p.error")).toContainText("missing columns");
});

test("a daily note with a stock, filtered by that stock", async ({ page, request }) => {
  const t = TICKERS[2];
  await open(page, "journal");
  await tab(page, "Daily notes");
  await expect(page.locator(".note").first()).toBeVisible(); // the fixture's notes
  await page.getByLabel("Stocks (comma or space separated)").fill(t);
  const text = `e2e: breadth thrust ${Date.now()}`;
  await page.getByLabel("Daily note").fill(text);
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(page.locator(".note", { hasText: text })).toBeVisible();
  const tagged = await json<{ notes: unknown[] }>(request, `/api/journal/daily-notes?tag=${t}`);
  const all = await json<{ notes: unknown[] }>(request, "/api/journal/daily-notes");
  expect(tagged.notes.length).toBeLessThan(all.notes.length); // the filter drops the others
  await page.getByLabel("Show").selectOption(t);
  await expect(page.locator(".note")).toHaveCount(tagged.notes.length);
  await expect(page.locator(".note", { hasText: text })).toBeVisible();
});

test("the Plans, Closed trades and Real vs study tabs", async ({ page }) => {
  await open(page, "journal");
  await tab(page, "Plans");
  await expect(page.getByLabel("Start from a scan hit")).toBeVisible();
  await expect(page.getByRole("table").first()).toBeVisible();
  await tab(page, "Closed trades");
  await expect(page.locator(".metric").first()).toBeVisible();
  await tab(page, "Real vs study");
  await expect(page.getByRole("table").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
});
