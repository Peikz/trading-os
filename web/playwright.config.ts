// End-to-end tests: the real FastAPI app over a synthetic data repo (tests/e2e/make_repo.py)
// serving the built React app (npm run build) on one origin, as Caddy does on the server.
//   npm run build && npm run e2e
// The server writes a fresh repo each start; the tests share it and run one at a time.
import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.E2E_PORT ?? 8765);

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
    viewport: { width: 1400, height: 1000 },
  },
  webServer: {
    command: `uv run --group api python -m tests.e2e.serve --port ${PORT}`,
    cwd: "..",
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false, // a fresh repo each run: the tests write to it
    timeout: 120_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
