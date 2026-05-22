import { expect, test } from "@playwright/test";

import { registerFreshUser, signIn } from "./helpers";

test.describe("auth", () => {
  test("register → land on engagements → sign out → sign in again", async ({ page }) => {
    const creds = await registerFreshUser(page);

    // Sign out via the Settings page.
    await page.goto("/settings/profile");
    await expect(page.getByText(creds.email)).toBeVisible();
    await Promise.all([
      page.waitForURL("**/login", { timeout: 30_000 }),
      page.getByRole("button", { name: /sign out/i }).click(),
    ]);

    await signIn(page, { email: creds.email, password: creds.password });
    await expect(page.getByRole("heading", { name: /engagements/i })).toBeVisible();
  });

  test("invalid login surfaces an error", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill("nobody@cpa.local");
    await page.getByLabel("Password").fill("wrong-password-x12345");
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByText(/incorrect email or password/i)).toBeVisible({ timeout: 15_000 });
  });

  test("unauthenticated visit redirects to /login", async ({ page }) => {
    await page.goto("/engagements");
    await expect(page).toHaveURL(/\/login(\?|$)/);
  });
});
