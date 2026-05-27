/**
 * Live smoke test for the USGAAP <> IFRS feature against the deployed
 * Render stack. Uses the demo "Skip" button instead of /register because
 * registration is currently rate-limited on the live deploy.
 *
 *   BASE_URL=https://cpa-web-01mj.onrender.com \
 *     pnpm exec playwright test tests/e2e/usgaap-ifrs-live.spec.ts \
 *     --project=chromium --workers=1
 */

import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES = path.resolve(HERE, "..", "fixtures", "comparison");

// Sandbox clock skew rejects the deployed cert; allow at spec level.
test.use({ ignoreHTTPSErrors: true });

async function skipLogin(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  const skip = page.getByRole("button", { name: /Skip.*Demo User/i });
  await expect(skip).toBeVisible({ timeout: 30_000 });
  await Promise.all([
    page.waitForURL(/\/engagements/, { timeout: 60_000 }),
    skip.click(),
  ]);
}

test.describe("USGAAP <> IFRS — live", () => {
  test("sidebar entry visible and landing page renders", async ({ page }) => {
    await skipLogin(page);
    const navLink = page.getByRole("link", { name: /USGAAP <> IFRS/i });
    await expect(navLink).toBeVisible();
    await navLink.click();
    await page.waitForURL("**/usgaap-ifrs", { timeout: 30_000 });
    await expect(page.getByRole("heading", { name: /USGAAP <> IFRS/i })).toBeVisible();
  });

  test("listing endpoint returns 200 + an array (no 'Not Found')", async ({ page }) => {
    await skipLogin(page);
    const out = await page.evaluate(async () => {
      const r = await fetch("/api/comparison/runs");
      const text = await r.text();
      let parsed: unknown = null;
      try {
        parsed = JSON.parse(text);
      } catch {
        /* keep as null */
      }
      return { status: r.status, text: text.slice(0, 300), parsed };
    });
    console.log("/comparison/runs →", out.status, out.text);
    expect(out.status).toBe(200);
    expect(Array.isArray(out.parsed)).toBe(true);
  });

  test("upload → status transitions → terminal state", async ({ page }) => {
    test.setTimeout(180_000);
    await skipLogin(page);
    await page.goto("/usgaap-ifrs");
    await expect(page.getByRole("heading", { name: /USGAAP <> IFRS/i })).toBeVisible();

    // Capture network so we can diagnose if upload returns "Not Found" again.
    const interesting: string[] = [];
    page.on("response", async (r) => {
      const u = r.url();
      if (u.includes("/comparison/")) {
        const body = await r.text().catch(() => "");
        interesting.push(`${r.status()} ${r.request().method()} ${u} :: ${body.slice(0, 200)}`);
      }
    });

    await page.locator('input[type="file"]').setInputFiles([
      path.join(FIXTURES, "policy.docx"),
      path.join(FIXTURES, "gl.csv"),
    ]);

    // The dropzone redirects to /usgaap-ifrs/{runId} on success.
    // If we instead end up with a "Not Found" error, surface the network log.
    try {
      await page.waitForURL(/\/usgaap-ifrs\/[0-9a-f-]{36}$/, { timeout: 60_000 });
    } catch (err) {
      console.log("\n=== /comparison network ===");
      interesting.forEach((line) => console.log(line));
      throw err;
    }

    const pill = page.getByTestId("run-status");
    await expect(pill).toBeVisible();

    await expect
      .poll(async () => await pill.getAttribute("data-status"), {
        timeout: 120_000,
        intervals: [1000, 2000, 4000, 8000],
      })
      .toMatch(/^(done|failed)$/);

    const finalStatus = await pill.getAttribute("data-status");
    console.log("final status =", finalStatus);

    if (finalStatus === "done") {
      await expect(page.getByTestId("framework-confirm")).toBeVisible();
    } else {
      // Failed runs must show the user a reason rather than going silent.
      const err = page.getByTestId("run-error");
      await expect(err).toBeVisible();
      const reason = await err.innerText();
      console.log("failure reason =", reason);
    }
  });
});
