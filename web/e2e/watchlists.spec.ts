// Your lists in Watchlists: a new list with checked tickers (added / already there / not found),
// removing selected stocks, price alerts, the scan watchlists. And the Journal's position cards.
import { expect, open, sym, test, TICKERS } from "./fixtures";

const UNKNOWN = sym("Q") + "Q"; // in no universe and no bars: "not found"

test("a new list: its first tickers are checked, then more can be added", async ({ page }) => {
  const name = `e2e list ${Date.now()}`;
  await open(page, "watchlists");
  const rail = page.getByRole("navigation", { name: "Lists" });
  await rail.getByRole("button", { name: "+ New list" }).click();
  await page.getByLabel("New list name").fill(name);
  await page.getByLabel("First tickers").fill(`${TICKERS[0]}, ${UNKNOWN}`);
  await page.getByRole("button", { name: "Create" }).click();
  // The list opens with the stock it took
  await expect(rail.getByRole("button", { name: new RegExp(`^${name}`) })).toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("button", { name: TICKERS[0], exact: true })).toBeVisible();

  // A new one plus an unknown one: the new one is added
  await page.getByLabel("Add tickers").fill(`${TICKERS[1]}, ${UNKNOWN}`);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText(`Added to ${name}: ${TICKERS[1]}`, { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: TICKERS[1], exact: true })).toBeVisible();
  // Nothing typed: nothing to send
  await expect(page.getByRole("button", { name: "Add", exact: true })).toBeDisabled();
});

test("select stocks, then remove them or open the list on the Chart", async ({ page }) => {
  await open(page, "watchlists");
  await page.getByRole("navigation", { name: "Lists" }).getByRole("button", { name: /^Leaders/ }).click();
  const rows = page.getByRole("table", { name: "Watchlist Leaders" }).locator("tbody tr");
  await expect(rows.first()).toBeVisible();
  const before = await rows.count();
  const gone = ((await rows.first().locator("td").nth(1).textContent()) ?? "").trim().split(/\s/)[0];
  await rows.first().getByRole("checkbox").check();
  await expect(page.getByText("1 selected")).toBeVisible();
  await page.getByRole("button", { name: "Clear" }).click();
  await expect(page.getByText("1 selected")).toHaveCount(0);
  await rows.first().getByRole("checkbox").check();
  await page.getByRole("button", { name: "Remove selected" }).click();
  await expect(rows).toHaveCount(before - 1);
  await expect(page.getByRole("table", { name: "Watchlist Leaders" })).not.toContainText(gone);
});

test("a price alert: add, list, remove; the scan watchlists", async ({ page }) => {
  await open(page, "watchlists");
  const rail = page.getByRole("navigation", { name: "Lists" });
  await rail.getByRole("button", { name: /^Price alerts/ }).click();
  const t = TICKERS[2];
  await page.getByLabel("Ticker", { exact: true }).fill(t);
  await page.getByLabel("Price", { exact: true }).fill("42.5");
  await page.getByLabel("When it trades").selectOption("below");
  await page.getByRole("button", { name: "Add alert" }).click();
  await expect(page.locator("p.ok")).toHaveText(`Alert set: ${t} below 42.50.`);
  const remove = page.getByRole("button", { name: `Remove ${t} below 42.5` });
  await expect(remove).toBeVisible();
  await remove.click();
  await expect(remove).toHaveCount(0);

  await rail.getByRole("button", { name: /^BO-Watch/ }).click();
  await expect(page.getByRole("table", { name: "BO-Watch" })).toContainText(TICKERS[1]);
  await page.getByLabel("Include triggered / expired").check();
  await expect(page.getByRole("table", { name: "BO-Watch" })).toContainText(TICKERS[2]);
  await rail.getByRole("button", { name: /^EP-Watch/ }).click();
  await expect(page.getByRole("table", { name: "EP-Watch" })).toContainText(TICKERS[0]);
});

test("Positions: a card per open position with its stop", async ({ page, request }) => {
  const data = (await (await request.get("/api/positions")).json()) as { cards: { ticker: string; stop: number | null }[] };
  expect(data.cards.length).toBeGreaterThan(0);
  await open(page, "journal/positions");
  await expect(page.locator(".cards article.card")).toHaveCount(data.cards.length);
  const first = data.cards[0];
  const card = page.getByLabel(`${first.ticker} position`);
  await expect(card).toContainText(first.stop === null ? "no stop" : `stop ${first.stop.toFixed(2)}`);
  await card.getByRole("link", { name: "Full chart" }).click();
  await expect(page.locator(".ws-bar .ticker")).toHaveText(first.ticker);
  await page.waitForLoadState("networkidle");
});
