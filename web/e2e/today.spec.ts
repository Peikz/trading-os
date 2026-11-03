// Today (design review 4 Nov 2026): the queue's three parts, flipping with the arrow keys, the
// bar switch, W (watch) and N (note), the plan card that leads with the decision (copy, edit
// order, I placed it in Saxo), the C setups on request, a push link, and the phone's cards.
import type { APIRequestContext, Page } from "@playwright/test";
import { expect, open, test } from "./fixtures";

type Row = {
  ticker: string;
  grade: string;
  plan_stop: number;
  plan_entry: number;
  decision: { text: string } | null;
} & Record<string, unknown>;

async function queue(request: APIRequestContext, query = "") {
  const res = await request.get(`/api/today${query}`);
  expect(res.ok()).toBeTruthy();
  return (await res.json()) as { rows: Row[]; hidden_c: number };
}

const queueNav = (page: Page) => page.getByRole("navigation", { name: "Queue" });
const section = (page: Page, label: string) =>
  queueNav(page).locator(":scope > div", { has: page.locator(".section-label", { hasText: label }) });
const plan = (page: Page, ticker: string) => page.getByLabel(`${ticker} plan`, { exact: true });

test("the queue: to act on, your positions, watching; the arrow keys flip round", async ({ page, request }) => {
  const { rows, hidden_c } = await queue(request);
  const positions = (await (await request.get("/api/positions")).json()) as { cards: { ticker: string }[] };
  expect(rows.length).toBeGreaterThan(2);
  expect(hidden_c).toBeGreaterThan(0); // the fixture has C hits
  await open(page, "today");
  await expect(page.locator(".place-head .muted")).toContainText(`${rows.length} setups to act on`);
  await expect(section(page, "To act on").locator(".queue li")).toHaveCount(rows.length);
  await expect(section(page, "Your positions").locator(".queue li")).toHaveCount(positions.cards.length);
  await expect(plan(page, rows[0].ticker)).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await expect(plan(page, rows[1].ticker)).toBeVisible();
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp"); // round to the bottom of the queue
  await expect(queueNav(page).locator(".queue button").last()).toHaveAttribute("aria-current", "true");
  await page.keyboard.press("ArrowDown");
  await expect(plan(page, rows[0].ticker)).toBeVisible();
});

test("the bar switch asks for daily, weekly and monthly bars, and the Indicators menu adds a line", async ({ page }) => {
  await open(page, "today");
  const bars = page.getByRole("group", { name: "Bars" });
  await expect(bars.getByRole("button", { name: "1D", exact: true })).toHaveAttribute("aria-pressed", "true");
  for (const tf of ["1W", "1M", "1D"]) {
    const answer = page.waitForResponse((r) => r.url().includes("/api/bars/") && r.url().includes(`tf=${tf}`));
    await bars.getByRole("button", { name: tf, exact: true }).click();
    const res = await answer;
    expect(res.status()).toBe(200);
    expect(((await res.json()) as { candles: unknown[] }).candles.length).toBeGreaterThan(0);
    await expect(bars.getByRole("button", { name: tf, exact: true })).toHaveAttribute("aria-pressed", "true");
  }
  await page.getByRole("button", { name: /Indicators/ }).click();
  const more = page.waitForResponse((r) => r.url().includes("/api/bars/") && r.url().includes("MA+200"));
  await page.getByRole("group", { name: "Indicators" }).getByLabel("MA 200").check();
  expect((await more).status()).toBe(200);
});

test("W watches the stock (Flag green) and N writes a note; a price alert", async ({ page, request }) => {
  const { rows } = await queue(request);
  const t = rows[0].ticker;
  await open(page, "today");
  await expect(plan(page, t)).toBeVisible();
  await page.keyboard.press("w");
  await expect(page.locator("p.toast")).toHaveText(`${t} is on your watchlist`);
  await expect(section(page, "Watching")).toContainText(t);
  const lists = (await (await request.get("/api/watchlists")).json()) as { lists: string[] };
  expect(lists.lists).toContain("Flag green");

  await page.keyboard.press("n");
  const note = page.getByLabel("Note", { exact: true });
  await expect(note).toBeFocused();
  await note.fill("e2e: base looks tight");
  await page.getByRole("button", { name: "Add note" }).click();
  await expect(page.locator("p.toast")).toHaveText("Note saved");
  await expect(page.getByLabel("Watch and note")).toContainText("e2e: base looks tight");
  // The price alert starts at the plan's pivot / entry
  await page.getByLabel("Watch and note").locator("summary").click();
  await page.getByRole("button", { name: "Add alert" }).click();
  await expect(page.locator("p.toast")).toContainText(`Alert: ${t} above`);
  // The star again takes it off the watchlist
  await page.getByRole("button", { name: /Watching: remove/ }).click();
  await expect(page.locator("p.toast")).toHaveText(`${t} is off your watchlist`);
});

test("the plan card: the decision, copy the order, edit it, and I placed it in Saxo", async ({ page, context, request }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const { rows } = await queue(request);
  const row = rows[0];
  const view = (await (await request.post("/api/ticket", { data: { row } })).json()) as {
    ticket: { lines: { label: string; value: string }[]; shares: number; summary: string };
  };
  await open(page, "today");
  const card = plan(page, row.ticker);
  await expect(card.locator(".decision")).toHaveText(row.decision?.text ?? "");
  await expect(card.locator(".quad")).toContainText(view.ticket.shares.toLocaleString("en-US"));
  await expect(card.locator(".order-line code")).toHaveText(view.ticket.summary);
  // The stop is the plan's; shares keep the grade's risk (0.5 % of 100 000 USD x the grade's size)
  const stop = view.ticket.lines.find((l) => l.label.startsWith("Stop loss"));
  expect(Number(stop?.value)).toBeCloseTo(row.plan_stop, 2);
  const mult = { "A+": 2, A: 1.5, B: 1 }[row.grade] ?? 1;
  const perShare = row.plan_entry - row.plan_stop;
  expect(view.ticket.shares * perShare).toBeLessThanOrEqual(500 * mult + 1e-6);
  expect((view.ticket.shares + 1) * perShare).toBeGreaterThan(500 * mult);

  await card.getByRole("button", { name: "Copy order for Saxo" }).click();
  await expect(card.getByRole("button", { name: /Copied/ })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(`${row.ticker}: ${view.ticket.summary}`);

  // Edit order: every value to type; another order type recomputes
  await card.getByRole("button", { name: "Edit order" }).click();
  const edit = card.getByLabel("Edit order");
  await expect(edit.locator("dl.lines div")).toHaveCount(view.ticket.lines.length);
  for (const line of view.ticket.lines) {
    await expect(edit.locator("dt", { hasText: line.label }).locator("+ dd code")).toHaveText(line.value);
  }
  await edit.getByLabel("Order type", { exact: true }).selectOption("limit");
  await expect(edit.locator("dt", { hasText: "Limit price" })).toBeVisible();
  const before = (await (await request.get("/api/journal/plans")).json()) as { plans: unknown[] };
  await card.getByRole("button", { name: "I placed it in Saxo" }).click();
  await expect(card.locator("p.ok")).toHaveText("Saved as a plan. Your fill will match it in the Journal.");
  const after = (await (await request.get("/api/journal/plans")).json()) as { plans: { ticker: string }[] };
  expect(after.plans.length).toBe(before.plans.length + 1);
  expect(after.plans.map((p) => p.ticker)).toContain(row.ticker);
});

test("the C setups show on request", async ({ page, request }) => {
  const { hidden_c } = await queue(request);
  const pushed = await queue(request, "?scope=pushed");
  const c = pushed.rows.filter((r) => r.grade === "C");
  expect(c.length).toBeGreaterThan(0);
  await open(page, "today");
  await page.getByRole("button", { name: `Show the ${hidden_c} C setup${hidden_c === 1 ? "" : "s"}` }).click();
  await expect(section(page, "C setups").locator(".queue li")).toHaveCount(c.length);
  await section(page, "C setups").locator(".queue button").first().click();
  await expect(plan(page, c[0].ticker)).toContainText("Not a buy by the study");
});

test("a push link shows the push's stocks first", async ({ page, request }) => {
  const { rows } = await queue(request, "?scope=all");
  const picked = [...new Set(rows.map((r) => r.ticker))].slice(0, 2).reverse();
  await page.goto(`/?t=${picked.join(",")}#/today`);
  await expect(queueNav(page).locator(".section-label").first()).toContainText("From the push");
  await expect(queueNav(page).locator(".queue button").first()).toContainText(picked[0]);
  await expect(queueNav(page).locator(".queue button").first()).toHaveAttribute("aria-current", "true");
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test("one card per stock, flipped with next; the places in a bottom bar", async ({ page, request }) => {
    const { rows } = await queue(request);
    await open(page, "today");
    const card = page.getByLabel(`${rows[0].ticker} card`);
    await expect(card).toBeVisible();
    await expect(card.getByRole("button", { name: "Copy order for Saxo" })).toBeVisible();
    await page.getByRole("button", { name: "Next stock" }).click();
    await expect(page.getByLabel(`${rows[1].ticker} card`)).toBeVisible();
    const bar = page.getByRole("navigation", { name: "Places (phone)" });
    await expect(bar).toBeVisible();
    await bar.getByRole("link", { name: "Market" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Market" })).toBeVisible();
    await page.waitForLoadState("networkidle");
  });
});
