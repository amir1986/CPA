/**
 * Download both English and Hebrew PDFs via the real ExportMemoButton.
 * Reports each status, byte count, and any 4xx/5xx body so the user
 * sees exactly what's failing.
 */

import { expect, test } from "@playwright/test";

test.use({ ignoreHTTPSErrors: true });

test("download EN + HE PDFs through the UI", async ({ page }) => {
  test.setTimeout(600_000);

  // Capture every export response so a failure body is visible.
  const wire: string[] = [];
  page.on("response", async (r) => {
    const u = r.url();
    if (u.includes("/comparison/runs") && u.includes("/export")) {
      let body = "";
      try {
        const ct = r.headers()["content-type"] || "";
        if (!ct.includes("pdf") && !ct.includes("octet")) body = (await r.text()).slice(0, 600);
        else body = `(binary, ${r.headers()["content-length"] ?? "?"} bytes)`;
      } catch {
        body = "(body unreadable)";
      }
      wire.push(`${r.status()} ${r.request().method()} ${u}\n  ${body}`);
    }
  });

  // Login is removed → go straight to the most recent done run.
  await page.goto("/usgaap-ifrs");
  const runs = await page.evaluate(
    async () => (await (await fetch("/api/comparison/runs")).json()) as Array<{ id: string; status: string }>,
  );
  const done = runs.find((r) => r.status === "done");
  expect(done, "no done run found to export").toBeDefined();
  await page.goto(`/usgaap-ifrs/${done!.id}`);
  await expect(page.getByTestId("run-detail")).toBeVisible();

  // ---- English ----
  // Make sure locale is EN.
  await page.evaluate(() => {
    document.cookie = "cpa_locale=en; path=/; SameSite=Lax";
  });
  await page.reload();
  await expect(page.getByTestId("export-md")).toBeVisible();
  const enPdfBtn = page.getByRole("button", { name: /^PDF$/ });
  const [enDl] = await Promise.all([
    page.waitForEvent("download", { timeout: 360_000 }).catch(() => null),
    enPdfBtn.click(),
  ]);
  if (enDl) {
    const p = await enDl.path();
    console.log(`[EN] downloaded: ${enDl.suggestedFilename()} path=${p}`);
    if (p) {
      const fs = await import("node:fs");
      const head = fs.readFileSync(p).slice(0, 8).toString("ascii");
      console.log(`[EN] head bytes: ${head}`);
      expect(head.startsWith("%PDF")).toBeTruthy();
    }
  } else {
    console.log("[EN] no download fired — inspecting the error pill on the page");
    const err = await page.locator('[data-testid="export-controls"] .text-danger').innerText().catch(() => "");
    console.log(`[EN] error pill: ${err}`);
  }

  // ---- Hebrew ----
  await page.evaluate(() => {
    document.cookie = "cpa_locale=he; path=/; SameSite=Lax";
  });
  await page.reload();
  await expect(page.getByTestId("export-md")).toBeVisible();
  const hePdfBtn = page.getByRole("button", { name: /^PDF$/ });
  const [heDl] = await Promise.all([
    page.waitForEvent("download", { timeout: 360_000 }).catch(() => null),
    hePdfBtn.click(),
  ]);
  if (heDl) {
    const p = await heDl.path();
    console.log(`[HE] downloaded: ${heDl.suggestedFilename()} path=${p}`);
    if (p) {
      const fs = await import("node:fs");
      const head = fs.readFileSync(p).slice(0, 8).toString("ascii");
      console.log(`[HE] head bytes: ${head}`);
      expect(head.startsWith("%PDF")).toBeTruthy();
    }
  } else {
    console.log("[HE] no download fired — inspecting the error pill on the page");
    const err = await page.locator('[data-testid="export-controls"] .text-danger').innerText().catch(() => "");
    console.log(`[HE] error pill: ${err}`);
  }

  console.log("\n=== export wire log ===");
  wire.forEach((line) => console.log(line));
});
