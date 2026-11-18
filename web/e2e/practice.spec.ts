// Practice: a signal's chart up to the entry, the four answers, the revealed trade, your numbers.
// The fixture has two practice signals and one exam signal (tests/e2e/make_repo.py).
import { expect, open, test } from "./fixtures";

type State = { stats: Record<string, { answered: number; remaining: number }> };

test("answer a signal: the trade is revealed, it is saved once and the numbers move", async ({ page, request }) => {
  const before = (await (await request.get("/api/practice")).json()) as State;
  await open(page, "practice");
  const card = page.getByLabel("The signal");
  await expect(card.locator("canvas").first()).toBeVisible();
  await expect(card.getByLabel("Facts known at the entry")).toContainText("Stop distance");
  await card.getByLabel("Note").fill("e2e: clean base");
  await card.getByRole("group", { name: "Your answer" }).getByRole("button", { name: "2", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("your pick 2 =");
  await expect(card.getByRole("group", { name: "Your answer" })).toHaveCount(0);
  const after = (await (await request.get("/api/practice")).json()) as State;
  expect(after.stats.practice.answered).toBe(before.stats.practice.answered + 1);
  await expect(page.getByRole("table", { name: "Your answered signals" })).toContainText("e2e: clean base");
});

test("the stock and the date stay hidden until you switch them on", async ({ page, request }) => {
  await open(page, "practice");
  await page.getByLabel("Show stock and date").uncheck();
  const next = (await (await request.get("/api/practice/next?pool=practice")).json()) as { signal_id: string | null };
  if (!next.signal_id) return; // the earlier test used the pool up on a rerun
  const blind = (await (await request.get(`/api/practice/signal/${next.signal_id}?shown=false`)).json()) as {
    ticker: string | null;
    chart: { candles: { time: string }[]; labels: Record<string, string> | null };
  };
  expect(blind.ticker).toBeNull();
  expect(Object.values(blind.chart.labels ?? {}).every((l) => l.startsWith("day -"))).toBe(true); // nothing from the entry on
  await expect(page.getByLabel("The signal").locator("canvas").first()).toBeVisible();
});
