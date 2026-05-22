import { expect, test } from "@playwright/test";

import { createEngagement, registerFreshUser } from "./helpers";

test.describe("engagement workflow", () => {
  test("register → create engagement → see dashboard KPIs", async ({ page }) => {
    await registerFreshUser(page);
    const eid = await createEngagement(page, {
      clientName: "ACME Industries",
      name: "ACME 2024 Audit",
    });
    expect(eid).toMatch(/^[0-9a-f-]{36}$/);

    await expect(page.getByRole("heading", { name: /ACME 2024 Audit/i })).toBeVisible();
    await expect(page.getByText(/files uploaded/i)).toBeVisible();
    await expect(page.getByText(/materiality/i).first()).toBeVisible();
  });

  test("books → trial balance + GL + COA pages all render", async ({ page }) => {
    await registerFreshUser(page);
    const eid = await createEngagement(page, {
      clientName: "Books Co",
      name: "Books Engagement",
    });

    await page.goto(`/engagements/${eid}/books/coa`);
    await expect(page.getByRole("heading", { name: /chart of accounts/i })).toBeVisible();
    // Import the US-GAAP template.
    await page.getByRole("button", { name: /^import$/i }).click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("1000")).toBeVisible();
    await expect(page.getByText("Cash and cash equivalents")).toBeVisible();

    await page.goto(`/engagements/${eid}/books/gl`);
    await expect(page.getByRole("heading", { name: /general ledger/i })).toBeVisible();

    await page.goto(`/engagements/${eid}/books/trial-balance`);
    await expect(page.getByRole("heading", { name: /trial balance/i })).toBeVisible();
  });
});
