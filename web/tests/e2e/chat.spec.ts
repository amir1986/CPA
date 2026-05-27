import { expect, test } from "@playwright/test";

import { createEngagement, registerFreshUser } from "./helpers";

test.describe("chat streaming + refusal", () => {
  test("out-of-corpus question returns a polite refusal", async ({ page }) => {
    // The default test stack ships with an empty Qdrant corpus, so any
    // question is out-of-corpus → /query/stream emits a refusal.
    await registerFreshUser(page);
    const eid = await createEngagement(page, { clientName: "Chat Co", name: "Chat E2E" });

    await page.goto(`/engagements/${eid}/chat`);
    await expect(page.getByRole("heading", { name: "Chat" })).toBeVisible();

    const composer = page.locator("textarea");
    await composer.fill("When is revenue recognized under ASC 606?");
    await page.getByRole("button").last().click();

    // We expect the assistant message to contain the refusal text.
    await expect(page.getByText(/can't answer this from the available standards/i)).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.locator("text=refused — out of corpus").first()).toBeVisible();
  });
});
