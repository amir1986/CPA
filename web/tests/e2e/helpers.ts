import { expect, type Page } from "@playwright/test";

/** Sign in as the seeded dev user. Idempotent — short-circuits when already signed in. */
export async function signIn(
  page: Page,
  { email = "dev@cpa.local", password = "devpassword1234" }: { email?: string; password?: string } = {},
): Promise<void> {
  await page.goto("/login");
  // If we're already signed in, /login bounces.
  if (!page.url().endsWith("/login")) return;
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await Promise.all([
    page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 }),
    page.getByRole("button", { name: /sign in/i }).click(),
  ]);
}

/** Register a fresh firm + admin user using a unique email. Returns the credentials. */
export async function registerFreshUser(page: Page): Promise<{ email: string; password: string; firm: string }> {
  const stamp = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  const email = `e2e+${stamp}@cpa.local`;
  const password = "playwright-e2e-pass-1234";
  const firm = `E2E Firm ${stamp}`;
  await page.goto("/register");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Your name").fill("E2E Bot");
  await page.getByLabel("Firm name").fill(firm);
  await page.getByLabel("Password").fill(password);
  await Promise.all([
    page.waitForURL("**/engagements", { timeout: 30_000 }),
    page.getByRole("button", { name: /create account/i }).click(),
  ]);
  await expect(page.getByRole("heading", { name: /engagements/i })).toBeVisible();
  return { email, password, firm };
}

/** Create an engagement and return its UUID. */
export async function createEngagement(
  page: Page,
  { clientName, name }: { clientName: string; name: string },
): Promise<string> {
  await page.goto("/engagements");
  await page.getByPlaceholder("Client name").fill(clientName);
  await page.getByPlaceholder("Engagement name").fill(name);
  await Promise.all([
    page.waitForURL(/\/engagements\/[0-9a-f-]{36}$/, { timeout: 30_000 }),
    page.getByRole("button", { name: /^create$/i }).click(),
  ]);
  return page.url().split("/").pop() ?? "";
}
