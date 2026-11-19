// The Journal notebook: the sidebar, a trade page with its chart and tags, a new page typed in
// markdown and saved by itself, the slash menu, #tag suggestions and the tag view, the $TICKER
// hover card, a stock note, today's note, search, the trade filters, and the phone layout.
import type { APIRequestContext, Page } from "@playwright/test";
import { expect, open, test, TICKERS } from "./fixtures";

const json = async <T>(request: APIRequestContext, path: string) => (await (await request.get(path)).json()) as T;
type Index = {
  pages: { slug: string; title: string; text: string; tags: string[] }[];
  daily: { id: string; date: string; text: string }[];
  trades: { status: string; grade: string; tags: string[] }[];
  stocks: { ticker: string; notes: { text: string }[] }[];
};
const saved = (page: Page) => expect(page.locator(".nb-save.saved").first()).toHaveText("Saved");
const body = (page: Page) => page.locator(".editor");

test("the notebook is the Journal's first tab, with a sidebar of every kind of note", async ({ page }) => {
  await open(page, "journal");
  await expect(page.getByRole("tab", { name: "Notebook" })).toHaveAttribute("aria-selected", "true");
  const side = page.getByRole("navigation", { name: "Notebook" });
  for (const name of ["Daily notes", "Trades", "Stocks", "Pages", "Tags"]) {
    await expect(side.getByRole("region", { name })).toBeVisible();
  }
  await expect(side.getByRole("searchbox", { name: "Search notes" })).toBeVisible();
  await expect(side.getByRole("link", { name: /Today/ })).toBeVisible();
  await expect(side.getByRole("button", { name: "New page" })).toBeVisible();
  // Today is open on a desktop
  await expect(page.getByRole("article", { name: /2026|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday/ })).toBeVisible();
});

test("a trade page: properties, the rendered notes, its tags and the chart with the stop", async ({ page }) => {
  await open(page, "journal/notes");
  await page.getByRole("navigation", { name: "Notebook" }).locator('a[href*="p=trade"]', { hasText: TICKERS[4] }).first().click();
  const article = page.getByRole("article").first();
  await expect(article.getByLabel("Grade")).toHaveValue("A");
  await expect(article.getByLabel("Conviction")).toHaveValue(/^[23]$/); // 2 in the fixture, 3 once the Trades test has run
  await expect(article.locator(".ed-h1")).toHaveText("Clean breakout"); // `# ` renders as a heading
  for (const tag of ["#late", "#ep", "#winner"]) await expect(article.locator(".nb-chip", { hasText: tag })).toBeVisible();
  await expect(article.locator(".nb-tag", { hasText: "#winner" })).toBeVisible(); // and in the text
  await expect(page.getByLabel("Trade chart").locator("canvas").first()).toBeVisible();
  await expect(page.getByLabel("Trade facts")).toContainText("Stop");
});

test("a new page is typed in markdown, renders, and is saved by itself as plain markdown", async ({ page, request }) => {
  await open(page, "journal/notes");
  await page.getByRole("button", { name: "New page" }).click();
  const title = page.getByLabel("Page title");
  await expect(title).toBeVisible();
  const name = `E2E plan ${Date.now()}`;
  await title.fill(name);
  await body(page).locator(".ed-tail").click();
  const kb = page.keyboard;
  await kb.type("# Plan");
  await kb.press("Enter");
  await kb.type("- first");
  await kb.press("Enter");
  await kb.type("second");
  await kb.press("Enter");
  await kb.press("Enter"); // an empty item ends the list
  await kb.type("[ ] ship it"); // `[ ] ` becomes a checklist item
  await kb.press("Enter");
  await kb.press("Enter"); // and an empty checklist item ends it too
  await kb.type("> a quote with **bold**");
  await saved(page);
  const index = await json<Index>(request, "/api/notebook");
  const made = index.pages.find((p) => p.title === name)!;
  expect(made.text).toBe("# Plan\n- first\n- second\n- [ ] ship it\n> a quote with **bold**");
  // Off the line, the markdown is drawn
  await kb.press("Escape");
  await expect(body(page).locator(".ed-h1")).toHaveText("Plan");
  await expect(body(page).locator(".ed-li")).toHaveCount(3);
  await expect(body(page).locator('input[type="checkbox"]')).toHaveCount(1);
  await expect(body(page).locator(".ed-quote strong")).toHaveText("bold");
  // The checkbox toggles the stored text
  await body(page).locator('input[type="checkbox"]').check();
  await saved(page);
  const again = await json<Index>(request, `/api/notebook`);
  expect(again.pages.find((p) => p.title === name)!.text).toContain("- [x] ship it");
  // Renaming is saved too, and the page is in the sidebar
  await expect(page.getByRole("navigation", { name: "Notebook" }).getByText(name)).toBeVisible();
});

test("the slash menu inserts a heading, a checklist, a divider, a tag and a ticker", async ({ page, request }) => {
  await open(page, "journal/notes");
  await page.getByRole("button", { name: "New page" }).click();
  await page.getByLabel("Page title").fill(`E2E slash ${Date.now()}`);
  await body(page).locator(".ed-tail").click();
  const kb = page.keyboard;
  await kb.type("/");
  const menu = page.getByRole("listbox", { name: "Suggestions" });
  for (const name of ["Heading 1", "Checklist", "Quote", "Divider", "Image or screenshot", "Ticker", "Tag"]) {
    await expect(menu.getByRole("option", { name })).toBeVisible();
  }
  await kb.type("head");
  await expect(menu.getByRole("option")).toHaveCount(3);
  await kb.press("Enter"); // Heading 1
  await kb.type("Title");
  await kb.press("Enter");
  await kb.type("/che");
  await kb.press("Enter");
  await kb.type("do it");
  await kb.press("Enter");
  await kb.type("/");
  await menu.getByRole("option", { name: "Divider" }).click();
  await kb.type("after ");
  await kb.type("/tag");
  await kb.press("Enter");
  await kb.type("ep");
  await expect(menu.getByRole("option", { name: "#ep" })).toBeVisible(); // suggested from the existing tags
  await kb.press("Enter");
  await kb.type(`$${TICKERS[0].slice(0, 2)}`);
  await expect(menu.getByRole("option", { name: `$${TICKERS[0]}` })).toBeVisible();
  await kb.press("Enter");
  await saved(page);
  const made = (await json<Index>(request, "/api/notebook")).pages.find((p) => p.text.startsWith("# Title"))!;
  expect(made.text.trimEnd()).toBe(`# Title\n- [ ] do it\n---\nafter #ep $${TICKERS[0]}`);
  expect(made.tags).toContain("ep");
});

test("a #tag opens the tag view: everything that carries it, newest first, with a snippet", async ({ page }) => {
  await open(page, "journal/notes");
  await page.getByRole("navigation", { name: "Notebook" }).getByRole("link", { name: /^#ep/ }).click();
  const view = page.getByRole("article", { name: "Tag ep" });
  await expect(view.getByRole("heading", { name: "#ep" })).toBeVisible();
  const hits = view.locator(".nb-hit");
  await expect(hits.filter({ hasText: "Chop in the afternoon" })).toHaveCount(1);
  const dates = await hits.locator(".nb-sub").allTextContents();
  expect(dates).toEqual([...dates].sort().reverse()); // newest first
  expect(dates.length).toBeGreaterThanOrEqual(2);
  await hits.filter({ hasText: "Clean breakout" }).click();
  await expect(page.getByRole("article").first().locator(".ed-h1")).toHaveText("Clean breakout");
});

test("$TICKER links to the stock page and shows a hover card", async ({ page }) => {
  const t = TICKERS[0];
  await open(page, "journal/notes");
  await page.getByRole("navigation", { name: "Notebook" }).getByRole("link", { name: /Trading rules/ }).click();
  const ref = body(page).locator(".nb-ref", { hasText: `$${t}` });
  await ref.hover();
  const card = ref.getByRole("tooltip");
  await expect(card).toContainText(t);
  await expect(card).toContainText(/\d+\.\d\d/); // last
  await ref.getByRole("link").click();
  await expect(page.getByRole("article", { name: `$${t}` })).toBeVisible();
  await expect(page.getByLabel("Stock chart").locator("canvas").first()).toBeVisible();
  await expect(page.getByRole("region", { name: "Linked mentions" })).toContainText("Trading rules");
});

test("a note on a stock is written on its page and saved as a stock note", async ({ page, request }) => {
  const t = TICKERS[3];
  await open(page, `journal/notes?p=stock:${t}`);
  const text = `e2e stock note ${Date.now()} #flag`;
  await body(page).first().locator(".ed-tail").click();
  await page.keyboard.type(text);
  await saved(page);
  const notes = await json<{ notes: { text: string }[] }>(request, `/api/chart/${t}/notes`);
  expect(notes.notes.map((n) => n.text)).toContain(text);
  await expect(page.getByRole("navigation", { name: "Notebook" }).getByRole("link", { name: `$${t}` })).toBeVisible();
});

test("today's note is written on the notebook's Today page and saved through the daily-note route", async ({ page, request }) => {
  await open(page, "journal/notes?p=today");
  const text = `e2e: today ${Date.now()}`;
  await body(page).locator(".ed-tail").click();
  await page.keyboard.type(text);
  await saved(page);
  // Added to the day's note if the Trades tab test made one first (a note per day is edited, not duplicated)
  expect((await json<{ text: string }>(request, "/api/journal/daily-notes/today")).text).toContain(text);
  const index = await json<Index>(request, "/api/notebook");
  expect(index.daily.filter((d) => d.text.includes(text))).toHaveLength(1);
});

test("search filters as you type, and the trades filter by grade and result", async ({ page, request }) => {
  const trades = (await json<Index>(request, "/api/notebook")).trades; // the fixture's, and any a test before added
  await open(page, "journal/notes");
  const side = page.getByRole("navigation", { name: "Notebook" });
  const search = side.getByRole("searchbox", { name: "Search notes" });
  await search.fill("breakout");
  const results = side.getByLabel("Search results");
  await expect(results.getByRole("link")).toHaveCount(1);
  await expect(results).toContainText("Clean breakout");
  await search.fill("zzzzzzz");
  await expect(results).toContainText("No note matches");
  await search.fill("");
  const list = side.getByRole("region", { name: "Trades" });
  const n = (keep: (t: Index["trades"][number]) => boolean) => trades.filter(keep).length;
  await expect(list.getByRole("link")).toHaveCount(trades.length);
  await list.getByRole("button", { name: "Filter trades" }).click();
  await list.getByLabel("Grade").selectOption("A");
  await expect(list.getByRole("link")).toHaveCount(n((t) => t.grade === "A"));
  await list.getByLabel("Grade").selectOption("");
  await list.getByLabel("Result").selectOption("open");
  await expect(list.getByRole("link")).toHaveCount(n((t) => t.status === "open"));
  await list.getByLabel("Result").selectOption("");
  await list.getByLabel("Tag").selectOption("winner");
  await expect(list.getByRole("link")).toHaveCount(n((t) => t.tags.includes("winner")));
  expect(n((t) => t.tags.includes("winner"))).toBeLessThan(trades.length); // it narrows
});

test("a pasted image is saved as an attachment and drawn in the note", async ({ page, request }) => {
  await open(page, "journal/notes");
  await page.getByRole("button", { name: "New page" }).click();
  await page.getByLabel("Page title").fill(`E2E image ${Date.now()}`);
  await body(page).locator(".ed-tail").click();
  const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==", "base64");
  await page.evaluate(async (b64) => {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const file = new File([bytes], "shot.png", { type: "image/png" });
    const data = new DataTransfer();
    data.items.add(file);
    const area = document.querySelector(".ed-input") as HTMLTextAreaElement;
    area.dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true }));
  }, png.toString("base64"));
  await expect(body(page).locator("img.nb-img")).toBeVisible();
  await saved(page);
  const made = (await json<Index>(request, "/api/notebook")).pages.find((p) => p.text.includes("/api/attachments/"))!;
  expect(made.text).toMatch(/^!\[shot\]\(\/api\/attachments\/data\/journal\/attachments\/.+shot\.png\)$/);
});

test("a free page can be deleted", async ({ page, request }) => {
  await open(page, "journal/notes");
  await page.getByRole("button", { name: "New page" }).click();
  const name = `E2E delete ${Date.now()}`;
  await page.getByLabel("Page title").fill(name);
  await saved(page);
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete this page" }).click();
  await expect(page.getByRole("navigation", { name: "Notebook" }).getByText(name)).toHaveCount(0);
  expect((await json<Index>(request, "/api/notebook")).pages.some((p) => p.title === name)).toBe(false);
});

test.describe("phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("the sidebar is the first screen; a note opens full screen with a back arrow and a format bar", async ({ page }) => {
    await open(page, "journal/notes");
    const side = page.getByRole("navigation", { name: "Notebook" });
    await expect(side).toBeVisible();
    await expect(page.getByRole("region", { name: "Page", exact: true })).toHaveCount(0);
    const row = side.locator('a[href*="p=trade"]', { hasText: TICKERS[4] }).first();
    expect((await row.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await row.click();
    const main = page.getByRole("region", { name: "Page", exact: true });
    await expect(main).toBeVisible();
    await expect(side).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await main.locator(".ed-tail").click();
    const bar = page.getByRole("toolbar", { name: "Format" });
    await expect(bar).toBeVisible();
    for (const name of ["Bold", "List", "Checklist", "Tag", "Stock", "Image"]) await expect(bar.getByRole("button", { name, exact: true })).toBeVisible();
    await bar.getByRole("button", { name: "Checklist" }).click();
    await page.keyboard.type("phone item");
    await saved(page);
    await page.getByRole("link", { name: "Back to the notebook" }).click();
    await expect(page.getByRole("navigation", { name: "Notebook" })).toBeVisible();
  });
});
