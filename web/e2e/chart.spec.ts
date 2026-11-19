// The Chart workspace: draw a trend line with two clicks and erase it, daily / weekly / monthly
// bars, the list panel (picker, sorting, stepping with the arrow keys and J/K, the address
// following), the stock panel's tabs, an anchored VWAP and a stock note, search on "/" and on
// typed letters; and the phone layout (bottom tabs, the list as a sheet, no sideways scroll).
import type { APIRequestContext, Page } from "@playwright/test";
import { expect, open, test, TICKERS } from "./fixtures";

const T = TICKERS[0];
type Mark = { mark_id: string; kind: string };
type ListRow = { ticker: string; grade: string; chg_pct: number | null };

async function lines(request: APIRequestContext): Promise<Mark[]> {
  const out = (await (await request.get(`/api/chart/${T}`)).json()) as { marks: Mark[] };
  return out.marks.filter((m) => m.kind === "line");
}

async function hitsList(request: APIRequestContext): Promise<ListRow[]> {
  return ((await (await request.get("/api/chart-lists/hits")).json()) as { rows: ListRow[] }).rows;
}

async function chartBox(page: Page) {
  const box = page.getByLabel("Chart", { exact: true });
  await expect(box.locator("canvas").first()).toBeVisible();
  const b = await box.boundingBox();
  if (!b) throw new Error("no chart box");
  return b;
}

const symbol = (page: Page) => page.locator(".ws-bar .ticker, .ws-phone-head .ticker");

test("a trend line drawn with two clicks is saved, then erased by a click on it", async ({ page, request }) => {
  const before = (await lines(request)).length;
  await open(page, `chart?s=${T}`);
  await expect(symbol(page)).toHaveText(T);
  const b = await chartBox(page);
  // Two points inside the candles' price range, so the saved line does not rescale the chart
  const a = { x: b.x + b.width * 0.45, y: b.y + b.height * 0.42 };
  const z = { x: b.x + b.width * 0.7, y: b.y + b.height * 0.5 };
  await page.getByRole("button", { name: "Draw a trend line (two clicks)" }).click();
  await page.mouse.click(a.x, a.y);
  await expect(page.getByText(/click the second/)).toBeVisible();
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
  await open(page, `chart?s=${T}`);
  const bars = page.getByRole("group", { name: "Bars" });
  const counts: Record<string, number> = {};
  for (const [tf, button] of [["Weekly", "W"], ["Monthly", "M"], ["Daily", "D"]]) {
    const answer = page.waitForResponse((r) => r.url().includes(`/api/chart/${T}?`) && r.url().includes(`timeframe=${tf}`));
    await bars.getByRole("button", { name: button, exact: true }).click();
    const res = await answer;
    expect(res.status(), `${tf} bars`).toBe(200);
    counts[tf] = ((await res.json()) as { candles: unknown[] }).candles.length;
    await expect(bars.getByRole("button", { name: button, exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByLabel("Chart", { exact: true }).locator("canvas").first()).toBeVisible();
  }
  // Two years of sessions: about 504 days, 104 weeks, 24-25 months
  expect(counts.Daily).toBeGreaterThan(500);
  expect(counts.Weekly).toBeGreaterThan(100);
  expect(counts.Weekly).toBeLessThan(110);
  expect(counts.Monthly).toBeGreaterThanOrEqual(24);
  expect(counts.Monthly).toBeLessThanOrEqual(26);
  // The drawing tools are for the daily bars only
  await expect(page.getByRole("group", { name: "Tools" }).getByRole("button")).toHaveCount(4);
  await bars.getByRole("button", { name: "W", exact: true }).click();
  await expect(page.getByRole("group", { name: "Tools" })).toHaveCount(0);
});

test("the list panel: the picker, sorting, and Up / Down / J / K step through it while the address follows", async ({ page, request }) => {
  const rows = await hitsList(request);
  expect(rows.length).toBeGreaterThan(2);
  await open(page, "chart?list=hits");
  const table = page.getByRole("table", { name: "List: Today's hits" });
  await expect(table.locator("tbody tr")).toHaveCount(rows.length);
  await expect(symbol(page)).toHaveText(rows[0].ticker); // no stock in the address: the list's first
  await expect(table.locator("tbody tr.active")).toContainText(rows[0].ticker);
  await expect(page.getByText(`Today's hits · 1 of ${rows.length}`)).toBeVisible();

  await page.keyboard.press("ArrowDown");
  await expect(symbol(page)).toHaveText(rows[1].ticker);
  await page.keyboard.press("ArrowDown");
  await expect(symbol(page)).toHaveText(rows[2].ticker);
  await expect(page).toHaveURL(new RegExp(`#/chart\\?s=${rows[2].ticker}&list=hits`));
  await page.keyboard.press("k");
  await expect(symbol(page)).toHaveText(rows[1].ticker);
  await page.keyboard.press("j");
  await expect(symbol(page)).toHaveText(rows[2].ticker);
  await expect(table.locator("tbody tr.active")).toContainText(rows[2].ticker);
  await page.waitForLoadState("networkidle");

  // A click picks a stock too; a second sort click flips the order
  await table.getByRole("button", { name: `Open ${rows[0].ticker}` }).click();
  await expect(symbol(page)).toHaveText(rows[0].ticker);
  await table.getByRole("columnheader", { name: "Symbol" }).getByRole("button").click();
  const names = await table.getByRole("button", { name: /^Open / }).allTextContents();
  expect(names).toEqual([...names].sort());

  // Another list from the picker
  const lists = (await (await request.get("/api/chart-lists")).json()) as { lists: { id: string; label: string }[] };
  const other = lists.lists.find((l) => l.id.startsWith("wl:"));
  expect(other).toBeTruthy();
  await page.getByRole("combobox", { name: "List" }).selectOption(other!.id);
  await expect(page.getByRole("table", { name: `List: ${other!.label}` })).toBeVisible();
  await expect.poll(() => new URL(page.url().replace("/#", "/")).searchParams.get("list")).toBe(other!.id);
});

test("the stock panel's tabs and collapsing the panels", async ({ page }) => {
  await open(page, `chart?s=${T}&list=hits`);
  const panel = page.getByRole("region", { name: "Stock panel" });
  await expect(panel.getByRole("tab")).toHaveText(["Plan", "Notes", "Position", "Lines"]); // one Notes tab
  for (const tab of ["Plan", "Notes", "Position", "Lines"]) {
    await panel.getByRole("tab", { name: tab, exact: true }).click();
    await expect(panel.getByRole("tabpanel")).toBeVisible();
    await page.waitForLoadState("networkidle");
  }
  await panel.getByRole("button", { name: "Hide the stock panel" }).click();
  await expect(panel.getByRole("tabpanel")).toHaveCount(0);
  await page.getByRole("button", { name: "Hide the list" }).click();
  await expect(page.getByRole("complementary", { name: "List panel" })).toHaveCount(0);
});

test("an anchored VWAP, a stock note, and search on / and on typed letters", async ({ page, request }) => {
  const picks = (await (await request.get("/api/chart/picks")).json()) as { ticker: string; where: string }[];
  expect(picks.length).toBeGreaterThan(0);
  await open(page, "chart");
  await page.getByRole("button", { name: "Search stocks, pages and tabs" }).click();
  const results = page.getByRole("dialog", { name: "Search" }).getByRole("listbox");
  await expect(results.getByRole("option").first()).toContainText(picks[0].ticker);
  await results.getByRole("option").first().click();
  await expect(symbol(page)).toHaveText(picks[0].ticker);

  // "/" and a typed letter open the search; Enter on an exact ticker opens it on the Chart
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("/");
  await expect(page.getByRole("dialog", { name: "Search" })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.keyboard.press("w");
  const search = page.getByRole("dialog", { name: "Search" }).getByRole("textbox");
  await expect(search).toHaveValue("W");
  await search.fill(T.toLowerCase());
  await page.keyboard.press("Enter");
  await expect(symbol(page)).toHaveText(T);
  await expect(page).toHaveURL(new RegExp(`#/chart\\?s=${T}`));

  await page.getByRole("button", { name: /^Lines/ }).click();
  const anchors = page.getByRole("group", { name: "Anchored VWAP from" });
  await anchors.getByRole("button").first().click();
  await expect(anchors.getByRole("button").first()).toHaveClass("on");
  await page.keyboard.press("Escape");

  // The Notes tab is the stock's notebook page: a note is written right there and saved by itself
  await page.getByRole("tab", { name: "Notes", exact: true }).click();
  await expect(page.getByRole("link", { name: "Open in Journal" })).toBeVisible();
  const text = `e2e: chart note ${Date.now()}`;
  await page.locator(".notes-tab .editor .ed-tail").first().click();
  await page.keyboard.type(text);
  await expect(page.locator(".nb-save.saved").first()).toHaveText("Saved");
  const stored = (await (await request.get(`/api/chart/${T}/notes`)).json()) as { notes: { note_id: string; text: string }[] };
  expect(stored.notes.map((n) => n.text)).toContain(text);
  await request.delete(`/api/chart/${T}/notes/${stored.notes.find((n) => n.text === text)!.note_id}`);
});

test.describe("on a phone", () => {
  test.use({
    viewport: { width: 390, height: 844 },
    userAgent:
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    hasTouch: true,
  });

  test("bottom tabs with More, a full-width chart, step arrows, the list as a sheet, no sideways scroll", async ({ page, request }) => {
    const rows = await hitsList(request);
    await open(page, "chart?list=hits");
    await expect(symbol(page)).toHaveText(rows[0].ticker);
    const tabs = page.getByRole("navigation", { name: "Places (phone)" });
    await expect(tabs.getByRole("link")).toHaveText(["Today", "Chart", "Lists", "Screener"]);
    await expect(tabs.getByRole("button", { name: "More" })).toBeVisible();
    const chart = await chartBox(page);
    expect(chart.width).toBeGreaterThanOrEqual(388);

    await page.getByRole("button", { name: "Next stock" }).click();
    await expect(symbol(page)).toHaveText(rows[1].ticker);
    await page.getByRole("button", { name: "Previous stock" }).click();
    await expect(symbol(page)).toHaveText(rows[0].ticker);

    const sheet = page.getByRole("region", { name: "List sheet" });
    await expect(sheet).toHaveAttribute("data-stop", "peek");
    await sheet.getByRole("button", { name: /^List sheet/ }).click();
    await expect(sheet).toHaveAttribute("data-stop", "half");
    await sheet.getByRole("button", { name: `Open ${rows[2].ticker}` }).click();
    await expect(symbol(page)).toHaveText(rows[2].ticker);

    await tabs.getByRole("button", { name: "More" }).click();
    const more = page.getByRole("dialog", { name: "More pages" });
    await expect(more.getByRole("link", { name: "Positions" })).toBeVisible();
    await expect(more.getByRole("link", { name: "Guide" })).toBeVisible();
    await more.getByRole("link", { name: "Guide" }).click();
    await expect(page.getByRole("tab", { name: "Guide", exact: true })).toHaveAttribute("aria-selected", "true");

    for (const route of ["today", `chart?s=${T}`, "screener/screen", "screener/hits", "watchlists", "market/overview", "journal/positions"]) {
      await open(page, route);
      const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(wide, `${route}: sideways scroll`).toBeLessThanOrEqual(0);
    }
  });
});
