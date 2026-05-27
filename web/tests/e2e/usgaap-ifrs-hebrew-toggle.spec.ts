/**
 * Verify that toggling Hebrew in /settings/profile actually flips the
 * page direction + translates the visible text. Runs against the live
 * deploy.
 */

import { expect, test } from "@playwright/test";

test.use({ ignoreHTTPSErrors: true });

test("Hebrew toggle flips dir + translates sidebar", async ({ page }) => {
  test.setTimeout(120_000);

  // Sign in via Skip → demo user.
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  const skip = page.getByRole("button", { name: /Skip.*Demo User/i });
  await expect(skip).toBeVisible({ timeout: 30_000 });
  await Promise.all([
    page.waitForURL(/\/engagements/, { timeout: 60_000 }),
    skip.click(),
  ]);

  // Capture PATCH response so we know if the api call succeeded.
  const apiResponses: { url: string; status: number; body: string }[] = [];
  page.on("response", async (r) => {
    const u = r.url();
    if (u.includes("/auth/me/locale")) {
      const body = await r.text().catch(() => "");
      apiResponses.push({ url: u, status: r.status(), body: body.slice(0, 200) });
    }
  });

  // Visit settings.
  await page.goto("/settings/profile");
  await expect(page.getByTestId("locale-select")).toBeVisible();

  // Confirm baseline: english LTR.
  const dirBefore = await page.locator("html").getAttribute("dir");
  const langBefore = await page.locator("html").getAttribute("lang");
  console.log(`baseline: lang=${langBefore} dir=${dirBefore}`);
  expect(dirBefore).toBe("ltr");

  // Switch to Hebrew + click Save.
  await page.locator('[data-testid="locale-select"] select').selectOption("he");
  await page.getByRole("button", { name: /^Save$/i }).click();

  // Wait briefly for the cookie + router.refresh dance.
  await page.waitForTimeout(2000);

  console.log("PATCH responses:", JSON.stringify(apiResponses));

  // The whole page should now be RTL.
  const dirAfter = await page.locator("html").getAttribute("dir");
  const langAfter = await page.locator("html").getAttribute("lang");
  console.log(`after save: lang=${langAfter} dir=${dirAfter}`);
  expect(dirAfter).toBe("rtl");
  expect(langAfter).toBe("he");

  // Sidebar should be translated — "Engagements" → "תיקים".
  const sidebarText = await page.locator("aside").innerText();
  console.log("sidebar (first 400 chars):", sidebarText.slice(0, 400));
  expect(sidebarText).toContain("תיקים");

  // Cookie should be persisted.
  const cookies = await page.context().cookies();
  const localeCookie = cookies.find((c) => c.name === "cpa_locale");
  console.log("cpa_locale cookie:", localeCookie);
  expect(localeCookie?.value).toBe("he");
});
