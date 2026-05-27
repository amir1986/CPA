/**
 * Live smoke test against the deployed Render stack.
 *
 *   BASE_URL=https://cpa-web-01mj.onrender.com \
 *     pnpm exec playwright test tests/e2e/live-skip.spec.ts --project=chromium
 */

import { expect, test } from "@playwright/test";

// Sandbox clock skew rejects the deployed cert; allow at the spec level.
test.use({ ignoreHTTPSErrors: true });

test.describe("live skip flow", () => {
  test("login page renders and shows Skip button", async ({ page }) => {
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: /Skip.*Demo User/i })).toBeVisible();
  });

  test("clicking Skip lands on /engagements (or shows the real error)", async ({ page }) => {
    const requests: string[] = [];
    const responses: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" || r.url().includes("/login") || r.url().includes("/engagements") || r.url().includes("/auth")) {
        requests.push(`${r.method()} ${r.url()}`);
      }
    });
    page.on("response", async (r) => {
      const u = r.url();
      if (u.includes("/login") || u.includes("/engagements") || u.includes("/auth")) {
        const h = r.headers();
        const interesting = Object.entries(h).filter(([k]) =>
          ["location", "x-action-redirect", "set-cookie", "x-nextjs-redirect", "x-nextjs-cache"].includes(k.toLowerCase()),
        );
        const hdrs = interesting.map(([k, v]) => `\n    ${k}: ${v.slice(0, 200)}`).join("");
        let body = "";
        if (r.request().method() === "POST") {
          try {
            const t = await r.text();
            body = `\n    body[first 500]: ${t.slice(0, 500)}`;
          } catch {
            body = "\n    body: <unavailable>";
          }
        }
        responses.push(`${r.status()} ${r.request().method()} ${u}${hdrs}${body}`);
      }
    });
    page.on("console", (m) => responses.push(`console.${m.type()}: ${m.text()}`));
    page.on("pageerror", (e) => responses.push(`pageerror: ${e.message}`));

    await page.goto("/login", { waitUntil: "domcontentloaded" });
    const skip = page.getByRole("button", { name: /Skip.*Demo User/i });
    await expect(skip).toBeVisible();

    await skip.click();
    await page.waitForTimeout(15_000);

    console.log("\n=== REQUESTS ===");
    requests.forEach((r) => console.log(r));
    console.log("\n=== RESPONSES / EVENTS ===");
    responses.forEach((r) => console.log(r));
    console.log("\n=== FINAL URL ===", page.url());
    console.log("=== FINAL TITLE ===", await page.title());

    const url = new URL(page.url());
    if (url.searchParams.has("error")) {
      const banner = await page.locator(".text-danger").first().innerText();
      throw new Error(`Skip failed: ${banner}`);
    }
    await expect(page).toHaveURL(/\/engagements/);
  });
});
