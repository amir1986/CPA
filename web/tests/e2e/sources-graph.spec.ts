import { expect, test } from "@playwright/test";

import { registerFreshUser } from "./helpers";

test.describe("knowledge graph", () => {
  test("Sources page renders the Cytoscape canvas and the catalog", async ({ page }) => {
    await registerFreshUser(page);
    await page.goto("/sources");
    await expect(page.getByRole("heading", { name: /knowledge sources/i })).toBeVisible();

    // Canvas mounts after the dynamic import resolves.
    const canvas = page.locator("canvas").first();
    await expect(canvas).toBeVisible({ timeout: 30_000 });

    // Curated graph (empty corpus) → these labels appear.
    await expect(page.locator("text=Revenue recognition").first()).toBeVisible();

    // Catalog renders at least one source.
    await expect(page.getByRole("heading", { name: /sources catalog/i })).toBeVisible();
  });
});
