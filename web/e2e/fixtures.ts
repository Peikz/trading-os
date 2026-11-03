// The shared guard of every end-to-end test: a console error, an uncaught page error or a
// failed API request (HTTP 4xx/5xx, or no answer) fails the test, unless the test said it
// provokes that answer with `allow()`. Tickers are synthetic: sym("W") is W + "ZQ" + W, like
// tests/e2e/make_repo.py, so no real symbol appears here.
import { test as base, expect, type Page } from "@playwright/test";

export const sym = (c: string) => [c, "Z", "Q", c].join("");
export const TICKERS = "WXYVUTSR".split("").map(sym);
export const WATCHLISTS = ["Earnings soon", "Leaders"];

type Allowed = { path: RegExp; status: number };
type Guard = { allow: (path: RegExp, status: number) => void; problems: string[] };

export const test = base.extend<{ guard: Guard }>({
  guard: [
    async ({ page }, use) => {
      const allowed: Allowed[] = [];
      const problems: string[] = [];
      const isAllowed = (pathname: string, status: number) =>
        allowed.some((a) => a.status === status && a.path.test(pathname));
      page.on("console", (m) => {
        if (m.type() !== "error") return;
        // The browser logs each 4xx/5xx it loads; an answer the test provoked is not an error
        const status = /status of (\d{3})/.exec(m.text());
        const url = m.location().url;
        if (status && url && isAllowed(new URL(url).pathname, Number(status[1]))) return;
        problems.push(`console: ${m.text()}${url ? ` (${new URL(url).pathname})` : ""}`);
      });
      page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
      page.on("response", (r) => {
        const url = new URL(r.url());
        if (!url.pathname.startsWith("/api/") || r.status() < 400) return;
        if (isAllowed(url.pathname, r.status())) return;
        problems.push(`HTTP ${r.status()} ${r.request().method()} ${url.pathname}${url.search}`);
      });
      page.on("requestfailed", (r) => {
        const url = new URL(r.url());
        // a request the page itself dropped (a newer one replaced it) is not a failure
        if (url.pathname.startsWith("/api/") && r.failure()?.errorText !== "net::ERR_ABORTED") {
          problems.push(`failed: ${r.method()} ${url.pathname} (${r.failure()?.errorText})`);
        }
      });
      await use({ allow: (path, status) => allowed.push({ path, status }), problems });
      expect(problems, "console errors or failed API requests").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

/** Open a page by its hash route and wait for the API calls it starts to settle. */
export async function open(page: Page, route: string) {
  await page.goto(`/#/${route}`);
  await page.waitForLoadState("networkidle");
}
