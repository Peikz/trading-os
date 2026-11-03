// Market, System health, Scans (view-only, as on the server image), Guide, the header's Pull
// latest / Save & push, and every page opened from the header without an error.
import { expect, open, sym, test } from "./fixtures";

const PAGES = [
  ["☀️ Today", "Candidates"],
  ["☀️ Market", "Market"],
  ["☀️ Watchlists", "Watchlists"],
  ["☀️ Screener", "Screener"],
  ["⚡ Positions", "Positions"],
  ["⚡ Chart", "Chart"],
  ["⚡ Scans", "Scans"],
  ["🌙 Journal", "Journal"],
  ["🌙 Live results", "Live results"],
  ["🔬 Research", "Research"],
  ["🔬 System health", "System health"],
  ["🔬 Guide", "Guide"],
];

test("every page opens from the header", async ({ page }) => {
  await open(page, "today");
  for (const [link, heading] of PAGES) {
    await page.getByRole("navigation").first().getByRole("link", { name: link, exact: true }).click();
    await expect(page.getByRole("heading", { level: 2, name: heading, exact: true })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expect(page.locator("main .error")).toHaveCount(0);
  }
});

test("Market: tiles, the setups at today's heat, sectors with the rotation, industries, breadth", async ({ page }) => {
  await open(page, "market");
  await expect(page.locator(".metric", { hasText: "QQQ light" })).toContainText("GREEN");
  await expect(page.locator("h3", { hasText: /^Warm market: scan count \d+/ })).toBeVisible();
  const heat = page.getByRole("group", { name: "Setups at this heat" });
  await heat.getByRole("button", { name: /^cool/ }).click();
  await expect(heat.getByRole("button", { name: /^cool/ })).toHaveClass("on");
  await expect(page.getByRole("table", { name: "Indexes, sectors and themes" })).toContainText(sym("K"));
  await expect(page.getByRole("img", { name: "Rotation against SPY" })).toBeVisible();
  await page.getByRole("group", { name: "Return over" }).getByRole("button").first().click();
  await expect(page.getByRole("table", { name: "Top 15 industries" })).toBeVisible();
  await page.getByRole("group", { name: "Rank move since" }).getByRole("button", { name: "1 month" }).click();
  await expect(page.locator("b", { hasText: "Climbing most (1 month)" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Breadth" }).locator("tbody tr")).toHaveCount(3);
  await page.getByText("The IBD market state (tracked, not a rule)").click();
  await expect(page.getByLabel("Breadth ratios").locator("canvas").first()).toBeVisible();
});

test("System health: the run grid, freshness, GitHub runs, validation against a CSV", async ({ page }) => {
  await open(page, "health");
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

test("Scans is view-only on the server image", async ({ page, request }) => {
  const scans = (await (await request.get("/api/scans")).json()) as { writable: boolean; checkout: boolean; note: string };
  expect(scans.writable).toBe(false);
  await open(page, "scans");
  await expect(page.getByRole("table", { name: "Scans" }).locator("tbody tr").first()).toBeVisible();
  await expect(page.locator("main p.warn")).toHaveText(scans.note);
  const editor = page.getByLabel("Edit a scan");
  await page.getByLabel("Scan", { exact: true }).selectOption({ index: 1 });
  await expect(editor).toBeVisible();
  await expect(editor.getByRole("button", { name: "Check and save" })).toBeDisabled();
  await expect(editor.getByRole("button", { name: "Commit & push to GitHub" })).toBeDisabled();
});

test("the Guide renders the Markdown guide", async ({ page }) => {
  await open(page, "guide");
  await expect(page.locator("main .markdown h2").first()).toBeVisible();
  await expect(page.locator("main .markdown")).toContainText("The dashboard, page by page");
});

test("Pull latest and Save & push report git's answer (the fixture is not a git clone)", async ({ page }) => {
  await open(page, "today");
  await page.getByRole("button", { name: "Pull latest" }).click();
  const msg = page.locator("p.sync-msg");
  await expect(msg).toHaveClass(/error/);
  await expect(msg).not.toBeEmpty();
  await msg.getByRole("button", { name: "Dismiss" }).click();
  await expect(msg).toHaveCount(0);
  await page.getByRole("button", { name: "Save & push" }).click();
  await expect(page.locator("p.sync-msg")).toBeVisible();
});
