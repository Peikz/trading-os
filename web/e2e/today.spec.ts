// Today: the queue, flipping, W, Show by watchlist, the F / N hotkeys and the Saxo ticket.
import type { APIRequestContext, Page } from "@playwright/test";
import { expect, open, test, WATCHLISTS } from "./fixtures";

type Row = { ticker: string; grade: string; plan_stop: number; plan_entry: number } & Record<string, unknown>;

async function queue(request: APIRequestContext, query = "") {
  const res = await request.get(`/api/today${query}`);
  expect(res.ok()).toBeTruthy();
  return (await res.json()) as { rows: Row[]; hidden_c: number };
}

const counter = (page: Page) => page.getByRole("navigation", { name: "Flip through" }).locator("span");
const card = (page: Page) => page.locator("article.card");

test("the queue counts the graded hits and the arrow keys flip round", async ({ page, request }) => {
  const { rows, hidden_c } = await queue(request);
  expect(rows.length).toBeGreaterThan(2);
  expect(hidden_c).toBeGreaterThan(0); // the fixture has C hits
  await open(page, "today");
  await expect(counter(page)).toHaveText(`1 of ${rows.length} · ${hidden_c} C hidden`);
  await expect(card(page).locator(".ticker")).toHaveText(rows[0].ticker);
  await page.keyboard.press("ArrowRight");
  await expect(counter(page)).toHaveText(new RegExp(`^2 of ${rows.length}`));
  await expect(card(page).locator(".ticker")).toHaveText(rows[1].ticker);
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft"); // wraps round to the last
  await expect(counter(page)).toHaveText(new RegExp(`^${rows.length} of ${rows.length}`));
  await page.getByTitle("Next (→ key)").click();
  await expect(counter(page)).toHaveText(new RegExp(`^1 of ${rows.length}`));
  // Pushed, incl. C shows the C hits too
  const pushed = await queue(request, "?scope=pushed");
  await page.getByLabel("Show").selectOption("pushed");
  await expect(counter(page)).toHaveText(`1 of ${pushed.rows.length}`);
  expect(pushed.rows.some((r) => r.grade === "C")).toBeTruthy();
});

test("W steps the bars 1D → 1W → 1M → 1D", async ({ page }) => {
  await open(page, "today");
  const bars = page.getByRole("group", { name: "Bars and indicators" });
  await expect(bars.getByRole("button", { name: "1D", exact: true })).toHaveClass("on");
  for (const tf of ["1W", "1M", "1D"]) {
    const answer = page.waitForResponse((r) => r.url().includes("/api/bars/") && r.url().includes(`tf=${tf}`));
    await page.keyboard.press("w");
    const res = await answer;
    expect(res.status()).toBe(200);
    expect(((await res.json()) as { candles: unknown[] }).candles.length).toBeGreaterThan(0);
    await expect(bars.getByRole("button", { name: tf, exact: true })).toHaveClass("on");
    await expect(page.locator(".focus-main")).toContainText(`· ${tf}`);
  }
});

test("Show picks each watchlist by its name", async ({ page, request }) => {
  await open(page, "today");
  const show = page.getByLabel("Show");
  for (const name of WATCHLISTS) {
    const { rows } = await queue(request, `?scope=watchlists&wl=${encodeURIComponent(name)}`);
    expect(rows.length).toBeGreaterThan(0);
    await show.selectOption({ label: `📋 ${name}` });
    await expect(counter(page)).toHaveText(`1 of ${rows.length}`);
    await expect(card(page).locator(".ticker")).toHaveText(rows[0].ticker);
  }
});

test("F flags the stock green and N opens the note box", async ({ page, request }) => {
  const { rows } = await queue(request);
  const t = rows[0].ticker;
  await open(page, "today");
  await expect(card(page).locator(".ticker")).toHaveText(t);
  await page.keyboard.press("f");
  await expect(page.locator("p.flash")).toHaveText(`${t} → Flag green`);
  const lists = (await (await request.get("/api/watchlists")).json()) as { lists: string[] };
  expect(lists.lists).toContain("Flag green");

  await page.keyboard.press("n");
  await expect(page.getByRole("tab", { name: "Notes & alerts" })).toHaveAttribute("aria-selected", "true");
  const note = page.getByLabel("Note", { exact: true });
  await expect(note).toBeFocused();
  await note.fill("e2e: base looks tight");
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(page.locator("p.flash")).toHaveText("Note saved");
  await expect(page.getByLabel("Notes and alerts")).toContainText("e2e: base looks tight");
  // The price alert starts at the plan's pivot / entry
  await page.getByRole("button", { name: "🔔 Add price alert" }).click();
  await expect(page.locator("p.flash")).toContainText(`Alert: ${t} above`);
});

test("the Saxo ticket shows the plan's values and Placed in Saxo saves a plan", async ({ page, request }) => {
  const { rows } = await queue(request);
  const row = rows[0];
  const view = (await (await request.post("/api/ticket", { data: { row } })).json()) as {
    ticket: { lines: { label: string; value: string }[]; shares: number };
  };
  await open(page, "today");
  const ticket = page.getByLabel("Saxo ticket", { exact: true });
  await expect(ticket.locator("dl.lines div")).toHaveCount(view.ticket.lines.length);
  for (const line of view.ticket.lines) {
    await expect(ticket.locator("dt", { hasText: line.label }).locator("+ dd code")).toHaveText(line.value);
  }
  // The stop is the plan's; shares keep the grade's risk (0.5 % of 100 000 USD x the grade's size)
  const stop = view.ticket.lines.find((l) => l.label.startsWith("Stop loss"));
  expect(Number(stop?.value)).toBeCloseTo(row.plan_stop, 2);
  const mult = { "A+": 2, A: 1.5, B: 1 }[row.grade] ?? 1;
  const perShare = row.plan_entry - row.plan_stop;
  expect(view.ticket.shares * perShare).toBeLessThanOrEqual(500 * mult + 1e-6);
  expect((view.ticket.shares + 1) * perShare).toBeGreaterThan(500 * mult);

  // Another order type recomputes the ticket; then save it
  await ticket.getByLabel("Order type", { exact: true }).selectOption("limit");
  await expect(ticket.locator("dt", { hasText: "Limit price" })).toBeVisible();
  const before = (await (await request.get("/api/journal/plans")).json()) as { plans: unknown[] };
  await ticket.getByRole("button", { name: "✅ Placed in Saxo: save as plan" }).click();
  await expect(ticket.locator("p.ok")).toHaveText("Saved as a plan. Your fill will match it in the Journal.");
  const after = (await (await request.get("/api/journal/plans")).json()) as { plans: { ticker: string }[] };
  expect(after.plans.length).toBe(before.plans.length + 1);
  expect(after.plans.map((p) => p.ticker)).toContain(row.ticker);
});

test("T hides the ticket and Grid and List views show the candidates", async ({ page, request }) => {
  const { rows } = await queue(request);
  await open(page, "today");
  await page.keyboard.press("t");
  await expect(page.getByText("Ticket hidden (T shows it).")).toBeVisible();
  await page.getByRole("group", { name: "View" }).getByRole("button", { name: "Grid" }).click();
  await expect(counter(page)).toHaveText(new RegExp(`^1-${Math.min(4, rows.length)} of ${rows.length}`));
  await page.getByRole("group", { name: "View" }).getByRole("button", { name: "List" }).click();
  await expect(page.locator(".cards article.card")).toHaveCount(rows.length);
});

test("a push link shows the push's stocks first", async ({ page, request }) => {
  const { rows } = await queue(request, "?scope=all");
  const picked = [...new Set(rows.map((r) => r.ticker))].slice(0, 2).reverse();
  await page.goto(`/?t=${picked.join(",")}#/today`);
  await expect(page.getByLabel("Show")).toHaveValue("push");
  await expect(card(page).locator(".ticker")).toHaveText(picked[0]);
});
