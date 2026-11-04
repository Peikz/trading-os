// Your lists in Stocks: a new list with checked tickers (added / already there / not found),
// removing a stock, price alerts, the scan watchlists. And the Journal's position cards.
import { expect, open, sym, test, TICKERS } from "./fixtures";

const UNKNOWN = sym("Q") + "Q"; // in no universe and no bars: "not found"

test("a new list: each ticker is checked and the answer says what happened", async ({ page }) => {
  const name = `e2e list ${Date.now()}`;
  await open(page, "stocks");
  await page.getByRole("navigation", { name: "Sources" }).getByRole("button", { name: "New list" }).click();
  await page.getByLabel("New list name").fill(name);
  await page.getByLabel("Add tickers").fill(`${TICKERS[0]}, ${UNKNOWN}`);
  await page.getByRole("button", { name: "Add to list" }).click();
  // The list opens with the stock it took
  await expect(page.getByRole("navigation", { name: "Sources" }).getByRole("button", { name })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await expect(page.getByRole("button", { name: `Open ${TICKERS[0]}` })).toBeVisible();

  // The same ticker again plus an unknown one: already on the list, not found
  const msg = page.getByRole("status");
  await page.getByLabel("Add tickers").fill(`${TICKERS[0]} ${UNKNOWN}`);
  await page.getByRole("button", { name: "Add to list" }).click();
  await expect(msg).toContainText(`Already on the list: ${TICKERS[0]}`);
  await expect(msg).toContainText(`Not found, not added: ${UNKNOWN}`);
  // A new one and an unknown one: a warning, the new one added
  await page.getByLabel("Add tickers").fill(`${TICKERS[1]}, ${UNKNOWN}`);
  await page.getByRole("button", { name: "Add to list" }).click();
  await expect(msg).toHaveClass(/warning/);
  await expect(msg).toContainText(`Added to ${name}: ${TICKERS[1]}`);
  await expect(page.getByRole("button", { name: `Open ${TICKERS[1]}` })).toBeVisible();
  // Only unknown tickers: an error, the list unchanged
  await page.getByLabel("Add tickers").fill(UNKNOWN);
  await page.getByRole("button", { name: "Add to list" }).click();
  await expect(msg).toHaveClass(/error/);
  // Nothing typed: nothing to send
  await page.getByLabel("Add tickers").fill("");
  await expect(page.getByRole("button", { name: "Add to list" })).toBeDisabled();
});

test("remove a stock from a list", async ({ page }) => {
  await open(page, "stocks?src=list:Leaders");
  await page.getByRole("group", { name: "View" }).getByRole("button", { name: /Table/ }).click();
  const rows = page.getByRole("table", { name: "Watchlist Leaders" }).locator("tbody tr");
  await expect(rows.first()).toBeVisible();
  const before = await rows.count();
  const gone = ((await rows.first().locator("td").first().textContent()) ?? "").trim();
  await page.getByRole("button", { name: `Remove ${gone} from the list` }).click();
  await expect(rows).toHaveCount(before - 1);
  await expect(page.getByRole("table", { name: "Watchlist Leaders" })).not.toContainText(gone);
});

test("a price alert: add, list, remove; the scan watchlists", async ({ page }) => {
  await open(page, "stocks?src=alerts");
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

  await page.getByRole("navigation", { name: "Sources" }).getByRole("button", { name: "BO-Watch", exact: true }).click();
  await expect(page.getByRole("table", { name: "BO-Watch" })).toContainText(TICKERS[1]);
  await page.getByLabel("Include triggered / expired").check();
  await expect(page.getByRole("table", { name: "BO-Watch" })).toContainText(TICKERS[2]);
  await page.getByRole("navigation", { name: "Sources" }).getByRole("button", { name: "EP-Watch", exact: true }).click();
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
  await expect(page.getByLabel(`${first.ticker} full chart`)).toBeVisible();
  await page.waitForLoadState("networkidle");
});
