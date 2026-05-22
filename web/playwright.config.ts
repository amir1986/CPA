import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config — runs against the full docker-compose stack.
 *
 * CI bootstraps the stack BEFORE invoking Playwright (see
 * .github/workflows/e2e.yml), so we don't use webServer here.
 *
 * BASE_URL defaults to localhost:8080 (the Caddy front door); override in
 * CI to point at the staging URL.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  outputDir: "test-results",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  fullyParallel: false, // serial — we mutate shared backend state
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:8080",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
