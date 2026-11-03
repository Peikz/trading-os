// Lab · Research (every section, Strategy rules for every label) and Journal · Live vs study
// (the live results' every section).
import type { Page } from "@playwright/test";
import { expect, open, test, TICKERS } from "./fixtures";

const SECTIONS = [
  "Strategy rules",
  "How it was tested",
  "Grades",
  "History",
  "Entries & exits",
  "Market regime",
  "Study notes",
];

async function section(page: Page, name: string) {
  await page.getByRole("tablist", { name: "Section" }).getByRole("tab", { name, exact: true }).click();
  await expect(page.getByRole("tab", { name, exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("main p.muted", { hasText: "Loading…" })).toHaveCount(0);
  await expect(page.locator("main .error")).toHaveCount(0);
}

test("Strategy rules: every label shows its rules", async ({ page, request }) => {
  const first = (await (await request.get("/api/research/strategy-rules")).json()) as { labels: string[] };
  expect(first.labels.length).toBeGreaterThan(5);
  await open(page, "lab/research");
  const pick = page.getByLabel("Strategy", { exact: true });
  for (const label of first.labels) {
    const answer = page.waitForResponse((r) => r.url().includes("/api/research/strategy-rules?"));
    await pick.selectOption(label);
    expect((await answer).status(), label).toBe(200);
    await expect(pick).toHaveValue(label);
    await expect(page.locator("main section b").first()).not.toBeEmpty();
    await expect(page.locator("main section .markdown").first()).toBeVisible();
  }
});

test("every Research section renders", async ({ page }) => {
  await open(page, "lab/research");
  for (const name of SECTIONS) await section(page, name);
});

test("History: filters, a split and an event chart", async ({ page }) => {
  await open(page, "lab/research");
  await section(page, "History");
  // 10 years is a release the fixture leaves out: the page says so; 2 years is in the repo
  await expect(page.getByText("No history here yet.")).toBeVisible();
  await page.getByRole("group", { name: "Period" }).getByRole("button", { name: "2 years (Massive)" }).click();
  await expect(page.locator("h3", { hasText: /events$/ })).toBeVisible();
  const split = page.getByLabel("Split by").first();
  await split.selectOption({ index: 1 });
  await expect(page.locator("main .error")).toHaveCount(0);
  const chart = page.getByLabel("Event chart");
  await chart.selectOption({ index: 1 }); // 0 is "—"
  await expect(page.locator("main .chart canvas").first()).toBeVisible();
});

test("Entries & exits on two years, Study notes rendered from Markdown", async ({ page }) => {
  await open(page, "lab/research");
  await section(page, "Entries & exits");
  await page.getByRole("group", { name: "Period" }).getByRole("button", { name: "2 years (all trades)" }).click();
  await expect(page.locator("h3", { hasText: "Best entry, stop and exit per strategy" })).toBeVisible();
  await page.getByRole("group", { name: "Period" }).getByRole("button", { name: "10 years (summaries)" }).click();
  await expect(page.getByText("The 10-year minute study hasn't been published yet")).toBeVisible();
  await section(page, "Market regime");
  await section(page, "Study notes");
  await expect(page.locator("main h1", { hasText: "A synthetic study" })).toBeVisible();
  await expect(page.locator("main table")).toContainText("120");
  await page.getByLabel("Study").selectOption("how-we-test");
  await expect(page.locator("main h1", { hasText: "How we test" })).toBeVisible();
});

test("Live results: every section, and the fixture's graded signal", async ({ page, request }) => {
  const graded = (await (await request.get("/api/live/graded")).json()) as { rows: { ticker: string }[] };
  expect(graded.rows.length).toBeGreaterThan(0);
  expect(TICKERS).toContain(graded.rows[0].ticker);
  await open(page, "journal/live");
  for (const name of ["Grades live vs study", "All signals", "Signals you graded"]) await section(page, name);
  await expect(page.getByRole("table", { name: "Signals you graded" })).toContainText(graded.rows[0].ticker);
});
