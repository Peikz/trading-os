// The shell and the read-mostly places: every place and tab opens without an error; the market
// in one word; Ctrl+K search; Market's five tabs; Lab's Health, Runs (view-only, as on the
// server image) and Guide; the manual Pull latest / Save & push in Settings.
import { expect, open, sym, test, TICKERS } from "./fixtures";

const PLACES: [string, string[]][] = [
  ["Today", []],
  ["Stocks", []],
  ["Market", ["Overview", "Heat & setups", "Sectors", "Breadth", "IBD"]],
  ["Journal", ["Positions", "Trades", "Plans", "Notes", "Live vs study"]],
  ["Lab", ["Research", "Runs", "Health", "Guide"]],
];

test("every place and tab opens from the top bar", async ({ page }) => {
  await open(page, "today");
  for (const [place, tabs] of PLACES) {
    await page.getByRole("navigation", { name: "Places", exact: true }).getByRole("link", { name: place, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: place, exact: true })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expect(page.locator("main .error")).toHaveCount(0);
    for (const tab of tabs) {
      await page.getByRole("tablist", { name: `${place} tabs` }).getByRole("tab", { name: tab, exact: true }).click();
      await expect(page.getByRole("tab", { name: tab, exact: true })).toHaveAttribute("aria-selected", "true");
      await page.waitForLoadState("networkidle");
      await expect(page.locator("main .error")).toHaveCount(0);
    }
  }
});

test("the old page addresses open their place and tab", async ({ page }) => {
  for (const [old, heading, tab] of [
    ["positions", "Journal", "Positions"],
    ["live", "Journal", "Live vs study"],
    ["research", "Lab", "Research"],
    ["health", "Lab", "Health"],
    ["guide", "Lab", "Guide"],
    ["market", "Market", "Overview"],
  ]) {
    await open(page, old);
    await expect(page.getByRole("heading", { level: 1, name: heading, exact: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: tab, exact: true })).toHaveAttribute("aria-selected", "true");
  }
  await open(page, "watchlists");
  await expect(page.getByRole("heading", { level: 1, name: "Stocks", exact: true })).toBeVisible();
});

test("the market in one word, with its reasons and SPY / QQQ / VIX", async ({ page }) => {
  await open(page, "today");
  const pill = page.getByRole("button", { name: /^Market: .+\. Show why$/ });
  await expect(pill).not.toContainText("Market…");
  await pill.click();
  const why = page.getByRole("dialog", { name: "Market" });
  await expect(why).toContainText("QQQ light is green.");
  await expect(why.locator(".quote", { hasText: "SPY" })).toBeVisible();
  await why.getByRole("link", { name: "Open Market" }).click();
  await expect(page.getByRole("tab", { name: "Overview", exact: true })).toHaveAttribute("aria-selected", "true");
});

test("Ctrl+K jumps to a stock, a place or a tab", async ({ page }) => {
  await open(page, "today");
  await page.keyboard.press("Control+k");
  const search = page.getByRole("dialog", { name: "Search" });
  await search.getByRole("textbox").fill("guide");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("tab", { name: "Guide", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Control+k");
  await search.getByRole("textbox").fill(TICKERS[0].toLowerCase());
  await page.keyboard.press("Enter");
  await expect(page.getByLabel(`${TICKERS[0]} full chart`)).toBeVisible();
  await page.waitForLoadState("networkidle");
});

test("Market: tiles, the setups at today's heat, sectors with the rotation, industries, breadth, IBD", async ({ page }) => {
  await open(page, "market/overview");
  await expect(page.locator(".metric", { hasText: "QQQ light" })).toContainText("GREEN");
  await page.getByRole("tab", { name: "Heat & setups" }).click();
  await expect(page.locator("h3", { hasText: /^Warm market: scan count \d+/ })).toBeVisible();
  const heat = page.getByRole("group", { name: "Setups at this heat" });
  await heat.getByRole("button", { name: /^cool/ }).click();
  await expect(heat.getByRole("button", { name: /^cool/ })).toHaveClass("on");
  await page.getByRole("tab", { name: "Sectors" }).click();
  await expect(page.getByRole("table", { name: "Indexes, sectors and themes" })).toContainText(sym("K"));
  await expect(page.getByRole("img", { name: "Rotation against SPY" })).toBeVisible();
  await page.getByRole("group", { name: "Return over" }).getByRole("button").first().click();
  await expect(page.getByRole("table", { name: "Top 15 industries" })).toBeVisible();
  await page.getByRole("group", { name: "Rank move since" }).getByRole("button", { name: "1 month" }).click();
  await expect(page.locator("b", { hasText: "Climbing most (1 month)" })).toBeVisible();
  await page.getByRole("tab", { name: "Breadth" }).click();
  await expect(page.getByRole("table", { name: "Breadth" }).locator("tbody tr")).toHaveCount(3);
  await expect(page.getByLabel("Breadth ratios").locator("canvas").first()).toBeVisible();
  await page.getByRole("tab", { name: "IBD", exact: true }).click();
  await expect(page.getByText("The IBD market state over the last 30 sessions")).toBeVisible();
});

test("Health: the run grid, freshness, GitHub runs, validation against a CSV", async ({ page }) => {
  await open(page, "lab/health");
  await expect(page.locator("h3", { hasText: "Runs per session" })).toBeVisible();
  await expect(page.locator("main table").first()).toBeVisible();
  await page.getByRole("button", { name: "Load the latest runs from GitHub" }).click();
  await expect(page.getByText("Did each timed job start on time?")).toBeVisible();

  await page.getByRole("tab", { name: "Validation against TradingView" }).click();
  const csv = `Symbol\nNASDAQ:${sym("W")}\nNYSE:${sym("X")}\n`;
  await page.getByLabel("TradingView screener export").setInputFiles({
    name: "screen.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csv),
  });
  await expect(page.getByRole("table", { name: "Validation" })).toBeVisible();
  await page.getByRole("button", { name: "Append to docs/validation.md" }).click();
  await expect(page.locator("main p.ok")).toBeVisible();
});

test("Runs and scans are view-only on the server image", async ({ page, request }) => {
  const scans = (await (await request.get("/api/scans")).json()) as { writable: boolean; checkout: boolean; note: string };
  const runs = (await (await request.get("/api/timed-runs")).json()) as { writable: boolean; note: string };
  expect(scans.writable).toBe(false);
  expect(runs.writable).toBe(false);
  await open(page, "lab/scans"); // the old address opens Runs
  await expect(page.getByRole("table", { name: "Runs" }).locator("tbody tr").first()).toBeVisible();
  await expect(page.getByRole("table", { name: "Scans" }).locator("tbody tr").first()).toBeVisible();
  await expect(page.locator("main p.warn")).toHaveText([runs.note, scans.note]);
  const runEditor = page.getByLabel("Edit a run");
  await expect(runEditor.getByRole("button", { name: "Check and save" })).toBeDisabled();
  const editor = page.getByLabel("Edit a scan");
  await page.getByLabel("Scan", { exact: true }).selectOption({ index: 1 });
  await expect(editor).toBeVisible();
  await expect(editor.getByRole("button", { name: "Check and save" })).toBeDisabled();
  await expect(editor.getByRole("button", { name: "Commit & push to GitHub" })).toBeDisabled();
});

test("the Guide renders the Markdown guide", async ({ page }) => {
  await open(page, "lab/guide");
  await expect(page.locator("main .markdown h2").first()).toBeVisible();
  await expect(page.locator("main .markdown")).toContainText("The dashboard, page by page");
});

test("Pull latest and Save & push run by themselves, with the buttons in Settings (the fixture is not a git clone)", async ({
  page,
}) => {
  const pulled = page.waitForResponse((r) => r.url().endsWith("/api/sync/pull"));
  await open(page, "today");
  expect((await pulled).status()).toBe(200); // a pull when the dashboard opens
  await page.getByRole("button", { name: "Settings" }).click();
  const settings = page.getByRole("dialog", { name: "Settings" });
  await expect(settings).toContainText("Pull latest: failed"); // not a git clone: git's answer
  await expect(settings.locator(".error").first()).not.toBeEmpty();
  await settings.getByRole("button", { name: "Save & push" }).click();
  await expect(settings).toContainText(/Save & push: (done|failed)/);
  await expect(page.getByRole("button", { name: /^System status: .*sync failed$/ })).toBeVisible();
});
