// Chart: draw a trend line with two clicks, erase it, weekly and monthly bars, AVWAP, notes.
import type { APIRequestContext, Page } from "@playwright/test";
import { expect, open, test, TICKERS } from "./fixtures";

const T = TICKERS[0];
type Mark = { mark_id: string; kind: string };

async function lines(request: APIRequestContext): Promise<Mark[]> {
  const out = (await (await request.get(`/api/chart/${T}`)).json()) as { marks: Mark[] };
  return out.marks.filter((m) => m.kind === "line");
}

async function chartBox(page: Page) {
  const box = page.getByLabel("Chart", { exact: true });
  await expect(box.locator("canvas").first()).toBeVisible();
  const b = await box.boundingBox();
  if (!b) throw new Error("no chart box");
  return b;
}

test("a trend line drawn with two clicks is saved, then erased by a click on it", async ({ page, request }) => {
  const before = (await lines(request)).length;
  await open(page, `chart?t=${T}`);
  await expect(page.getByRole("heading", { name: `Notes on ${T}` })).toBeVisible();
  const b = await chartBox(page);
  // Two points inside the candles' price range, so the saved line does not rescale the chart
  const a = { x: b.x + b.width * 0.45, y: b.y + b.height * 0.42 };
  const z = { x: b.x + b.width * 0.7, y: b.y + b.height * 0.5 };
  await page.getByRole("button", { name: "Draw a trend line (two clicks)" }).click();
  await page.mouse.click(a.x, a.y);
  await expect(page.locator(".hint")).toContainText("click the second");
  const saved = page.waitForResponse((r) => r.url().endsWith(`/api/chart/${T}/lines`) && r.request().method() === "POST");
  const redrawn = page.waitForResponse((r) => r.url().includes(`/api/chart/${T}?`) && r.request().method() === "GET");
  await page.mouse.click(z.x, z.y);
  expect((await saved).status()).toBe(200);
  await redrawn; // the chart reloads with the new line
  await expect(page.locator("p.flash")).toHaveText("Line saved.");
  await expect.poll(async () => (await lines(request)).length).toBe(before + 1);

  await page.getByRole("button", { name: "Delete the line you click" }).click();
  const gone = page.waitForResponse((r) => r.url().includes(`/api/chart/${T}/marks/`) && r.request().method() === "DELETE");
  await page.mouse.click((a.x + z.x) / 2, (a.y + z.y) / 2);
  expect((await gone).status()).toBe(200);
  await expect(page.locator("p.flash")).toHaveText("Line deleted.");
  await expect.poll(async () => (await lines(request)).length).toBe(before);
});

test("daily, weekly and monthly bars", async ({ page }) => {
  await open(page, `chart?t=${T}`);
  const bars = page.getByRole("group", { name: "Bars" });
  const counts: Record<string, number> = {};
  for (const tf of ["Weekly", "Monthly", "Daily"]) {
    const answer = page.waitForResponse((r) => r.url().includes(`/api/chart/${T}?`) && r.url().includes(`timeframe=${tf}`));
    await bars.getByRole("button", { name: tf, exact: true }).click();
    const res = await answer;
    expect(res.status(), `${tf} bars`).toBe(200);
    counts[tf] = ((await res.json()) as { candles: unknown[] }).candles.length;
    await expect(bars.getByRole("button", { name: tf, exact: true })).toHaveClass("on");
    await expect(page.getByLabel("Chart", { exact: true }).locator("canvas").first()).toBeVisible();
  }
  // Two years of sessions: about 504 days, 104 weeks, 24-25 months
  expect(counts.Daily).toBeGreaterThan(500);
  expect(counts.Weekly).toBeGreaterThan(100);
  expect(counts.Weekly).toBeLessThan(110);
  expect(counts.Monthly).toBeGreaterThanOrEqual(24);
  expect(counts.Monthly).toBeLessThanOrEqual(26);
  // The drawing tools are for the daily bars only
  await expect(page.getByRole("group", { name: "Tools" })).toBeVisible();
});

test("an anchored VWAP, a stock note and the picks list", async ({ page }) => {
  await open(page, "chart");
  await expect(page.getByText("Pick or type a ticker.")).toBeVisible();
  const picks = page.getByLabel("Today's hits, watchlists, open positions");
  await expect(picks.locator("option")).not.toHaveCount(1);
  await picks.selectOption({ index: 1 });
  const anchors = page.getByRole("group", { name: "Anchored VWAP from" });
  await anchors.getByRole("button").first().click();
  await expect(anchors.getByRole("button").first()).toHaveClass("on");
  await page.getByLabel("Any ticker").fill(T);
  await page.getByLabel("New note").fill("e2e: chart note");
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(page.locator(".note p.pre", { hasText: "e2e: chart note" })).toBeVisible();
  await page.locator(".note", { hasText: "e2e: chart note" }).getByRole("button", { name: "Delete" }).click();
  await expect(page.locator(".note p.pre", { hasText: "e2e: chart note" })).toHaveCount(0);
});
