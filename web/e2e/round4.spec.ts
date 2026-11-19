// Round 4 (19 Nov 2026), the last Streamlit gaps: search by words and a ticker's detail, the
// settings (manual test runs, the data folder), Today's Grid / List / Show / All scans, the
// Chart's one Notes tab and the Lines tab, the Screener's TradingView links and a scan's own
// table, the position's trade chart, and removing several alerts at once.
import { expect, open, test, TICKERS } from "./fixtures";

const T = TICKERS[0];
type Today = { rows: { ticker: string; scan: string }[] };
const palette = (page: import("@playwright/test").Page) => page.getByRole("dialog", { name: "Search" });

test("search: a ticker shows its scan hits, lists and notes; an unknown one is not in the universe", async ({ page, request }) => {
  await request.post(`/api/stock-notes/${T}`, { data: { text: "e2e round4 searchable note" } });
  await open(page, "today");
  await page.getByRole("button", { name: "Search stocks, pages and tabs" }).click();
  const box = palette(page).getByRole("textbox");
  await box.fill(T.toLowerCase());
  const detail = palette(page).getByRole("region", { name: `${T} everywhere` });
  await expect(detail).toContainText("scan hits");
  await expect(detail).toContainText("On:");
  await expect(detail.getByText(/e2e round4 searchable note/)).toBeVisible();
  // Words find the note too, and Enter on the exact known ticker opens the Chart
  await box.fill("searchable note");
  await expect(palette(page).getByRole("region", { name: "Words in your notes and the guide" })).toContainText("e2e round4 searchable note");
  await box.fill(T.toLowerCase());
  await expect(palette(page).getByRole("listbox", { name: "Results" }).getByRole("option").first()).toContainText(T);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`#/chart\\?s=${T}`));
  // A ticker that is not in the universe is said so, and Enter does not open it
  await page.keyboard.press("/");
  await palette(page).getByRole("textbox").fill("QQXQ");
  await expect(palette(page).getByText("QQXQ is not in the universe")).toBeVisible();
});

test("settings: the manual test runs toggle (on by default) and the data folder", async ({ page, request }) => {
  const seen: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/runs")) seen.push(r.headers()["x-manual-runs"] ?? "");
  });
  await open(page, "today");
  await page.getByRole("button", { name: "Settings" }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog.getByRole("checkbox", { name: "Show manual test runs" })).toBeChecked();
  const folder = ((await (await request.get("/api/settings")).json()) as { data_folder: string }).data_folder;
  await expect(dialog.locator("code")).toHaveText(folder);
  await expect(dialog).toContainText(/\d+ runs · session \d{4}-\d{2}-\d{2}/);
  await dialog.getByRole("checkbox", { name: "Show manual test runs" }).uncheck();
  await expect.poll(() => seen.at(-1)).toBe("0");
  await page.reload();
  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("checkbox", { name: "Show manual test runs" })).not.toBeChecked(); // per browser
});

test("Today: Grid and List views, Show another list, and All scans", async ({ page, request }) => {
  const { rows } = (await (await request.get("/api/today")).json()) as Today;
  expect(rows.length).toBeGreaterThan(0);
  await open(page, "today");
  await page.getByRole("button", { name: "Grid", exact: true }).click();
  const grid = page.getByRole("region", { name: "Grid of charts" });
  await expect(grid.getByRole("article")).toHaveCount(Math.min(4, rows.length));
  await expect(grid.locator("canvas").first()).toBeVisible();
  await page.getByRole("button", { name: "List", exact: true }).click();
  const list = page.getByRole("region", { name: "List of cards" });
  await expect(list.getByRole("article").first()).toBeVisible();
  await expect(list.getByRole("article", { name: `${rows[0].ticker} card` }).getByRole("link", { name: "Chart" })).toBeVisible();
  await page.getByRole("button", { name: "Focus", exact: true }).click();

  // Show: every scan hit, and one of your watchlists
  const every = (await (await request.get("/api/today?scope=all")).json()) as Today;
  await page.locator(".place-head").getByRole("button", { name: /^Show/ }).click();
  await page.getByRole("option", { name: "Every scan hit" }).click();
  await expect(page.locator(".place-head .muted")).toContainText(`${every.rows.length} ${every.rows.length === 1 ? "stock" : "stocks"} · Every scan hit`);
  await page.locator(".place-head").getByRole("button", { name: /^Show/ }).click();
  await page.getByRole("option", { name: "Leaders" }).click();
  await expect(page.locator(".place-head .muted")).toContainText("· Leaders");
  await expect(page.getByRole("group", { name: "Scan run" })).toHaveCount(0);
  await page.locator(".place-head").getByRole("button", { name: /^Show/ }).click();
  await page.getByRole("option", { name: "Today's list" }).click();

  // All scans: closed until opened; then each pushed scan's table
  await expect(page.getByRole("region", { name: /table$/ })).toHaveCount(0);
  await page.getByRole("button", { name: /all scans/i }).click();
  const tables = page.locator(".all-scans-body .scan-table");
  await expect(tables.first()).toBeVisible();
  await expect(tables.first().getByRole("link", { name: "TradingView ↗" }).first()).toHaveAttribute("href", /tradingview\.com/);
  await tables.first().getByRole("columnheader").first().getByRole("button").click(); // sorts
  await expect(tables.first().getByRole("button", { name: /as CSV$/ })).toBeVisible();
});

test("Today: F watches, T opens the Saxo values, W steps the bars", async ({ page, request }) => {
  const { rows } = (await (await request.get("/api/today")).json()) as Today;
  await open(page, "today");
  await expect(page.getByLabel(`${rows[0].ticker} plan`, { exact: true })).toBeVisible();
  await page.keyboard.press("t");
  const edit = page.getByLabel("Edit order");
  await expect(edit).toBeVisible();
  await expect(edit.getByRole("button", { name: /^Copy / }).first()).toBeVisible();
  await page.keyboard.press("t");
  await expect(edit).toHaveCount(0);
  const bars = page.waitForRequest((r) => r.url().includes("/api/bars/") && r.url().includes("tf=1W"));
  await page.keyboard.press("w");
  await bars;
  await expect(page.getByRole("group", { name: "Bars" }).getByRole("button", { name: "1W" })).toHaveAttribute("aria-pressed", "true");
});

test("Chart: one Notes tab, a horizontal line at a price, and its saved lines", async ({ page, request }) => {
  await open(page, `chart?s=${T}&list=hits`);
  const panel = page.getByRole("region", { name: "Stock panel" });
  await expect(panel.getByRole("tab")).toHaveText(["Plan", "Notes", "Position", "Lines"]);
  await panel.getByRole("tab", { name: "Notes", exact: true }).click();
  await expect(panel.getByRole("link", { name: "Open in Journal" })).toHaveAttribute("href", new RegExp(`#/journal/notes\\?p=stock%3A${T}`));
  await expect(panel.getByRole("table", { name: `Trades in ${T}` }).or(panel.getByText(`No trades in ${T} yet.`))).toBeVisible();
  await panel.getByRole("link", { name: "Open in Journal" }).click();
  await expect(page).toHaveURL(new RegExp(`#/journal/notes\\?p=stock`));
  await open(page, `chart?s=${T}&list=hits`);

  await panel.getByRole("tab", { name: "Lines", exact: true }).click();
  const lines = panel.getByRole("region", { name: `Lines on ${T}` });
  await lines.getByLabel("Level price").fill("12.5");
  await lines.getByRole("button", { name: "Horizontal line" }).click();
  const item = lines.getByRole("list", { name: "Saved lines" }).getByText("Level 12.50");
  await expect(item).toBeVisible();
  const saved = (await (await request.get(`/api/chart/${T}/saved`)).json()) as { text: string }[];
  expect(saved.map((m) => m.text)).toContain("Level 12.50");
  await lines.getByRole("button", { name: "Remove: Level 12.50" }).click();
  await expect(item).toHaveCount(0);
});

test("Screener: a TradingView link per row, the scan's own table and the grade blocks", async ({ page, request }) => {
  await open(page, "screener/hits");
  const table = page.getByRole("table", { name: "Results" });
  await expect(table.getByRole("link", { name: /on TradingView$/ }).first()).toHaveAttribute("href", /tradingview\.com/);
  const hits = (await (await request.get("/api/scan-hits")).json()) as { scans: { id: string; label: string }[] };
  const pushed = hits.scans.find((s) => s.label.startsWith("EP")) ?? hits.scans[0];
  await page.getByRole("button", { name: /Scan\s*All scans/ }).click();
  await page.getByRole("option", { name: new RegExp(pushed.label) }).click();
  await page.getByRole("tab", { name: "Scan table" }).click();
  await expect(page.getByRole("region", { name: new RegExp(`^${pushed.label} table$`) })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Study grade" })).toBeVisible();
});

test("Screener: from a screen, flip through on Today and open the Chart's last screener result", async ({ page }) => {
  await open(page, "screener/screen");
  await expect(page.getByRole("table", { name: "Results" }).locator("tbody tr").first()).toBeVisible();
  await page.getByRole("button", { name: "Flip through on Today" }).click();
  await expect(page).toHaveURL(/#\/today\?screen=Screener&t=/);
  await expect(page.getByText("From the screen: Screener")).toBeVisible();
  await open(page, "screener/screen");
  await page.getByRole("table", { name: "Results" }).locator("tbody tr").first().dblclick();
  await expect(page).toHaveURL(/#\/chart\?s=\w+&list=screen/);
  await expect(page.getByRole("table", { name: "List: Last screener result" })).toBeVisible();
});

test("Journal positions: a chart with the entry, the fills and the stop", async ({ page, request }) => {
  const positions = (await (await request.get("/api/positions")).json()) as { cards: { ticker: string }[] };
  test.skip(positions.cards.length === 0, "the fixture has no open position");
  await open(page, "journal/positions");
  const card = page.getByLabel(`${positions.cards[0].ticker} position`, { exact: true });
  await card.locator("summary").click();
  await expect(card.getByLabel(`${positions.cards[0].ticker} trade chart`)).toBeVisible();
});

test("alerts: remove several at once", async ({ page, request }) => {
  for (const level of [501, 502]) {
    await request.post("/api/alerts", { data: { ticker: T, level, direction: "above", note: "e2e multi" } });
  }
  await open(page, "watchlists");
  await page.getByRole("button", { name: /^Price alerts/ }).click();
  await page.getByRole("checkbox", { name: `Select ${T} above 501` }).check();
  await page.getByRole("checkbox", { name: `Select ${T} above 502` }).check();
  await expect(page.getByText("2 selected")).toBeVisible();
  await page.getByRole("button", { name: "Remove selected" }).click();
  await expect(page.getByText("Removed 2 alerts.")).toBeVisible();
  const left = (await (await request.get("/api/alerts")).json()) as { alerts: { level: number }[] };
  expect(left.alerts.some((a) => a.level === 501 || a.level === 502)).toBe(false);
});
