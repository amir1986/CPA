/**
 * E2E for the USGAAP <> IFRS feature.
 *
 * The deployed stack uses a real LLM and a (default-empty) standards corpus,
 * so the test asserts the *structural* flow that's deterministic — upload →
 * status transitions → framework-confirm UI → export — and tolerates both
 * "done with issues" and "done with no issues" / "failed" outcomes for the
 * LLM-dependent bits.
 */

import path from "node:path";

import { expect, test } from "@playwright/test";

import { registerFreshUser, signIn } from "./helpers";

const FIXTURES = path.resolve(__dirname, "..", "fixtures", "comparison");

test.describe("USGAAP <> IFRS", () => {
  test("sidebar entry visible and routes to the landing page", async ({ page }) => {
    await registerFreshUser(page);
    // Sidebar shows the new entry; clicking it loads the landing page.
    const navLink = page.getByRole("link", { name: /USGAAP <> IFRS/i });
    await expect(navLink).toBeVisible();
    await navLink.click();
    await page.waitForURL("**/usgaap-ifrs");
    await expect(page.getByRole("heading", { name: /USGAAP <> IFRS/i })).toBeVisible();
    await expect(page.getByText(/no runs yet/i)).toBeVisible();
  });

  test("upload → status transitions → framework confirm → export", async ({ page }) => {
    await registerFreshUser(page);
    await page.goto("/usgaap-ifrs");

    const input = page.locator('input[type="file"]');
    await input.setInputFiles([
      path.join(FIXTURES, "policy.docx"),
      path.join(FIXTURES, "gl.csv"),
    ]);

    // The dropzone redirects to /usgaap-ifrs/{runId} on success.
    await page.waitForURL(/\/usgaap-ifrs\/[0-9a-f-]{36}$/, { timeout: 60_000 });

    const pill = page.getByTestId("run-status");
    await expect(pill).toBeVisible();

    // Wait for a terminal status within 90s — done or failed are both acceptable;
    // the assertions below branch on outcome.
    await expect
      .poll(
        async () => await pill.getAttribute("data-status"),
        { timeout: 90_000, intervals: [1000, 2000, 4000] },
      )
      .toMatch(/^(done|failed)$/);

    const status = await pill.getAttribute("data-status");

    if (status === "done") {
      // FrameworkConfirm always renders once detection finishes — even if
      // the LLM couldn't confidently pick one (detected may be "—").
      const confirm = page.getByTestId("framework-confirm");
      await expect(confirm).toBeVisible();

      const issuesContainer = page.getByTestId("issues");
      const issueCount = await issuesContainer.locator('[data-testid="issue-card"]').count();

      if (issueCount > 0) {
        // Each card has both panes.
        await expect(page.getByTestId("pane-current").first()).toBeVisible();
        await expect(page.getByTestId("pane-other").first()).toBeVisible();

        // Memo export round-trips a .md file with both framework headings.
        const exportBtn = page.getByTestId("export-md");
        await expect(exportBtn).toBeVisible();
        const [download] = await Promise.all([
          page.waitForEvent("download"),
          exportBtn.click(),
        ]);
        expect(download.suggestedFilename()).toMatch(/\.md$/);
        const tmpPath = await download.path();
        if (tmpPath) {
          const fs = await import("node:fs");
          const body = fs.readFileSync(tmpPath, "utf-8");
          expect(body).toContain("DRAFT — REQUIRES PARTNER REVIEW");
          expect(body).toContain("US GAAP");
          expect(body).toContain("IFRS");
        }
      } else {
        // No issues found is a tolerated outcome on an empty standards
        // corpus or a hesitant LLM — render the empty-state copy.
        await expect(page.getByText(/didn't identify any accounting issues/i)).toBeVisible();
      }
    } else {
      // failed — make sure the user actually sees the reason.
      await expect(page.getByTestId("run-error")).toBeVisible();
    }
  });

  test("a second user cannot read the first user's run (cross-user isolation)", async ({ browser }) => {
    // User A uploads.
    const ctxA = await browser.newContext();
    const pageA = await ctxA.newPage();
    await registerFreshUser(pageA);
    await pageA.goto("/usgaap-ifrs");
    await pageA.locator('input[type="file"]').setInputFiles(path.join(FIXTURES, "gl.csv"));
    await pageA.waitForURL(/\/usgaap-ifrs\/[0-9a-f-]{36}$/, { timeout: 60_000 });
    const userARunId = pageA.url().split("/").pop()!;
    await ctxA.close();

    // User B fetches that run via the proxy → must 404.
    const ctxB = await browser.newContext();
    const pageB = await ctxB.newPage();
    await registerFreshUser(pageB);
    const status = await pageB.evaluate(async (rid) => {
      const r = await fetch(`/api/cpa/comparison/runs/${rid}`);
      return r.status;
    }, userARunId);
    expect(status).toBe(404);

    // And the UI route renders the Next.js notFound page.
    const navResp = await pageB.goto(`/usgaap-ifrs/${userARunId}`);
    expect([404, 200]).toContain(navResp?.status() ?? 0);
    // Either the 404 page or the routed empty-state — both are fine; the
    // important assertion is that the issue cards are not present.
    await expect(pageB.locator('[data-testid="issue-card"]')).toHaveCount(0);
    await ctxB.close();
  });
});

test.describe("USGAAP <> IFRS — back-end smoke (no upload)", () => {
  test("listing endpoint authorizes and returns an array", async ({ page }) => {
    await signIn(page).catch(async () => {
      await registerFreshUser(page);
    });
    const json = await page.evaluate(async () => {
      const r = await fetch("/api/cpa/comparison/runs");
      if (!r.ok) return { status: r.status, body: null };
      return { status: r.status, body: await r.json() };
    });
    expect(json.status).toBe(200);
    expect(Array.isArray(json.body)).toBe(true);
  });
});
