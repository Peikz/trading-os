// Watchlists: a new list with checked tickers (added / already there / not found), removing a
// stock, price alerts, the scan watchlists. And the Positions page's cards.
import { expect, open, sym, test, TICKERS } from "./fixtures";

const UNKNOWN = sym("Q") + "Q"; // in no universe and no bars: "not found"

test("a new list: each ticker is checked and the answer says what happened", async ({ page }) => {
  const name = `e2e list ${Date.now()}`;
  await open(page, "watchlists");
  const list = page.getByLabel("List", { exact: true });
  await expect(list.locator("option")).not.toHaveCount(1); // the lists have loaded
  await list.selectOption({ index: (await list.locator("option").count()) - 1 }); // ＋ new list
  await page.getByLabel("New list name").fill(name);
  await page.getByLabel("Add tickers").fill(`${TICKERS[0]}, ${UNKNOWN}`);
  await page.getByRole("button", { name: "Add to list" }).click();
  const msg = page.getByRole("status");
  await expect(msg).toHaveClass(/warning/);
  await expect(msg).toContainText(`✅ Added to ${name}: ${TICKERS[0]}`);
  await expect(msg).toContainText(`❌ Not found, not added: ${UNKNOWN}`);
  await expect(page.getByLabel("List", { exact: true })).toHaveValue(name);
  await expect(page.getByRole("table", { name: `Watchlist ${name}` })).toContainText(TICKERS[0]);

  // The same ticker again: already on the list, nothing added
  await page.getByLabel("Add tickers").fill(TICKERS[0]);
  await page.getByRole("button", { name: "Add to list" }).click();
  await expect(msg).toHaveText(`Already on the list: ${TICKERS[0]}`);
  // Only unknown tickers: an error, the list unchanged
  await page.getByLabel("Add tickers").fill(UNKNOWN);
  await page.getByRole("button", { name: "Add to list" }).click();
  await expect(msg).toHaveClass(/error/);
  // Nothing typed
  await page.getByLabel("Add tickers").fill("");
  await page.getByRole("button", { name: "Add to list" }).click();
  await expect(msg).toHaveText("No tickers to add.");
});

test("remove a stock from a list", async ({ page }) => {
  await open(page, "watchlists");
  await page.getByLabel("List", { exact: true }).selectOption("Leaders");
  const rows = page.getByRole("table", { name: "Watchlist Leaders" }).locator("tbody tr");
  await expect(rows.first()).toBeVisible();
  const before = await rows.count();
  const gone = (await rows.first().locator("td").first().textContent()) ?? "";
  await page.getByLabel("Remove from the list").selectOption(gone);
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await expect(rows).toHaveCount(before - 1);
  await expect(page.getByRole("table", { name: "Watchlist Leaders" })).not.toContainText(gone);
});

test("a price alert: add, list, remove; the scan watchlists", async ({ page }) => {
  await open(page, "watchlists");
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

  await expect(page.getByRole("table", { name: "BO-Watch" })).toContainText(TICKERS[1]);
  await expect(page.getByRole("table", { name: "EP-Watch" })).toContainText(TICKERS[0]);
  await page.getByLabel("Include triggered / expired").check();
  await expect(page.getByRole("table", { name: "BO-Watch" })).toContainText(TICKERS[2]);
});

test("Positions: a card per open position with its stop", async ({ page, request }) => {
  const data = (await (await request.get("/api/positions")).json()) as { cards: { ticker: string; stop: number | null }[] };
  expect(data.cards.length).toBeGreaterThan(0);
  await open(page, "positions");
  await expect(page.locator(".cards article.card")).toHaveCount(data.cards.length);
  const first = data.cards[0];
  const card = page.getByLabel(`${first.ticker} position`);
  await expect(card).toContainText(first.stop === null ? "no stop" : `stop ${first.stop.toFixed(2)}`);
  await card.getByRole("link", { name: "📈 Chart" }).click();
  await expect(page.getByLabel("Any ticker")).toHaveValue(first.ticker);
  await page.waitForLoadState("networkidle");
});
