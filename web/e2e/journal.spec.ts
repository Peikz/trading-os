// Journal: log a fill by hand, import a broker CSV, a daily note, and every tab.
import type { APIRequestContext, Page } from "@playwright/test";
import { expect, open, test, TICKERS } from "./fixtures";

const tab = (page: Page, name: string) =>
  page.getByRole("tablist", { name: "Journal tabs" }).getByRole("tab", { name, exact: true }).click();
const json = async <T>(request: APIRequestContext, path: string) => (await (await request.get(path)).json()) as T;

test("log a fill: the entry opens a position", async ({ page, request }) => {
  const t = TICKERS[7];
  const before = await json<{ totals: { positions: number } }>(request, "/api/journal/open");
  await open(page, "journal/trades");
  await page.getByText("Log a fill by hand").click();
  await page.getByLabel("Ticker", { exact: true }).fill(t);
  await page.getByLabel("Side").selectOption("buy");
  await page.getByLabel("Shares", { exact: true }).fill("10");
  await page.getByLabel("Price", { exact: true }).fill("12.5");
  await page.getByLabel("Initial stop (entries)").fill("11.75");
  await page.getByRole("button", { name: "Save fill" }).click();
  await expect(page.locator("p.ok")).toHaveText(`Saved: buy 10 ${t} @ 12.5.`);

  await tab(page, "Positions");
  const after = await json<{ totals: { positions: number } }>(request, "/api/journal/open");
  expect(after.totals.positions).toBeGreaterThanOrEqual(before.totals.positions); // new, or added to
  // The journal's own totals, under the position cards
  await expect(page.locator(".metric", { hasText: "Open positions" }).last()).toContainText(String(after.totals.positions));
  await expect(page.getByRole("table", { name: "Open positions" })).toContainText(t);
});

test("a broker export: the preview first, then the import closes a trade", async ({ page, request }) => {
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
  await open(page, "journal/trades");
  await page.getByRole("button", { name: "Import broker fills" }).click();
  const dialog = page.getByRole("dialog", { name: "Import broker fills" });
  await dialog.getByLabel("Fills export").setInputFiles({ name: "fills.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await expect(dialog.getByText("2 rows read")).toBeVisible(); // the preview: nothing written yet
  expect(await closedOf()).toBe(before);
  await dialog.getByRole("button", { name: /^Import \d+ new fills$/ }).click();
  await expect(dialog.locator("p.ok")).toBeVisible();
  // The fixture has no trade in this stock: the import closes one. (A rerun on the same repo
  // overlaps the first import's dates, and the journal rightly keeps that as one trade.)
  expect(await closedOf()).toBe(Math.max(before, 1));
  await page.reload();
  await expect(page.getByRole("table", { name: "Closed trades" })).toContainText(t);
});

test("a CSV without the mapped columns says what is missing", async ({ page }) => {
  await open(page, "journal/trades");
  await page.getByRole("button", { name: "Import broker fills" }).click();
  const dialog = page.getByRole("dialog", { name: "Import broker fills" });
  await dialog.getByLabel("Fills export").setInputFiles({ name: "bad.csv", mimeType: "text/csv", buffer: Buffer.from("a,b\n1,2\n") });
  await expect(dialog.locator("p.error")).toContainText("missing columns");
  await expect(dialog.getByRole("button", { name: /^Import \d+ new fills$/ })).toHaveCount(0);
});

test("a trade opens beside the table: chart with the fills, and its conviction is saved", async ({ page, request }) => {
  type Closed = { trades: { trade_id: string; ticker: string; conviction: number | null }[] };
  const closed = await json<Closed>(request, "/api/journal/closed");
  expect(closed.trades.length).toBeGreaterThan(0);
  await open(page, "journal/trades");
  const detail = page.getByRole("region", { name: /trade$/ });
  await expect(detail).toBeVisible(); // the first trade is open at desktop width
  await expect(detail.locator("canvas").first()).toBeVisible();
  await detail.getByRole("radiogroup", { name: "Conviction" }).getByLabel("3", { exact: true }).check();
  await detail.getByRole("button", { name: "Save", exact: true }).click();
  await expect(detail.locator("p.ok")).toBeVisible();
  const after = await json<Closed>(request, "/api/journal/closed");
  expect(after.trades.some((t) => t.conviction === 3)).toBe(true); // the same file Streamlit reads
  await expect(page.getByRole("table", { name: "Closed trades" })).toContainText("◆3");
});

test("today's note is saved from the Journal and shows on Today", async ({ page, request }) => {
  await open(page, "journal/trades");
  await page.getByRole("button", { name: /Today's note/ }).click();
  const text = `e2e: today ${Date.now()}`;
  await page.getByLabel("Today's note text").fill(text);
  await page.getByRole("button", { name: "Save today's note" }).click();
  await expect(page.locator(".daily-body .ok")).toBeVisible();
  const saved = await json<{ text: string }>(request, "/api/journal/daily-notes/today");
  expect(saved.text).toBe(text);
  await open(page, "today");
  await expect(page.getByRole("button", { name: /Today's note/ })).toContainText(text);
});

test("the Plans, Trades and Live results tabs", async ({ page }) => {
  await open(page, "journal");
  await tab(page, "Plans");
  await expect(page.getByLabel("Start from a scan hit")).toBeVisible();
  await expect(page.getByRole("table").first()).toBeVisible();
  await tab(page, "Trades");
  await expect(page.locator(".metric").first()).toBeVisible();
  await tab(page, "Live results");
  await expect(page.getByRole("table").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
});
