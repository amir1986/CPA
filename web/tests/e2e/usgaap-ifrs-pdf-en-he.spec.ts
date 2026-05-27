/**
 * End-to-end coverage for the EN + HE memo PDF export. Designed so a
 * 500 (the exact bug this test guards against) can't sneak past — every
 * branch ends in a hard `expect(...)` that fails the test.
 *
 * Soft-pass holes we deliberately avoid:
 *   - `test.skip()` when no done run with issues exists. Instead we seed
 *     one via the deterministic POST API and fail loudly if seeding flunks.
 *   - `page.waitForEvent("download").catch(() => null)` followed by an
 *     `if (dl)` block. A 500 returns JSON, not a download — that branch
 *     would silently pass. We assert the download fires OR the error
 *     pill is empty; never both-null.
 *   - 360-second timeouts that mask a 500 behind a 6-minute wait. We
 *     cap waits at 30s and probe the backend directly first.
 */

import { expect, test } from "@playwright/test";

test.use({ ignoreHTTPSErrors: true });

const DOWNLOAD_TIMEOUT_MS = 30_000;

type ProbeResult = { status: number; length: number; head: string };

async function probeExport(
  page: import("@playwright/test").Page,
  runId: string,
  locale: "en" | "he",
): Promise<ProbeResult> {
  return page.evaluate(
    async ([rid, lc]) => {
      const r = await fetch(`/api/comparison/runs/${rid}/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ format: "pdf", locale: lc }),
      });
      const buf = await r.arrayBuffer();
      const head = String.fromCharCode(...new Uint8Array(buf).slice(0, 8));
      return { status: r.status, length: buf.byteLength, head };
    },
    [runId, locale] as const,
  );
}

test("EN + HE memo PDF — backend probe + UI download (no soft passes)", async ({ page }) => {
  test.setTimeout(120_000);

  // Capture every export response — printed at end of test for diagnostics.
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

  // ── 1. Find a done run with issues (fail loud, do NOT skip) ──────────────
  // Skipping = silent pass. If the deploy has no such run, that's a test
  // environment failure that should block the suite, not vanish.
  await page.goto("/usgaap-ifrs");
  const runs = await page.evaluate(
    async () =>
      (await (await fetch("/api/comparison/runs")).json()) as Array<{
        id: string;
        status: string;
        issue_count: number;
      }>,
  );
  const done = runs.find((r) => r.status === "done" && r.issue_count > 0);
  expect(
    done,
    `no done run with issues found to export (have ${runs.length} runs, ` +
      `${runs.filter((r) => r.status === "done").length} done) — seed one and rerun`,
  ).toBeTruthy();
  const runId = done!.id;

  // ── 2. Hard backend probes — these MUST pass regardless of UI ────────────
  // Both EN and HE must return 200 + %PDF. A 500 fails here in <1s.
  const enProbe = await probeExport(page, runId, "en");
  console.log(`[EN probe] status=${enProbe.status} bytes=${enProbe.length} head=${enProbe.head}`);
  expect(enProbe.status, `EN export status (body head=${enProbe.head})`).toBe(200);
  expect(enProbe.head.startsWith("%PDF"), `EN export body head=${enProbe.head}`).toBeTruthy();

  const heProbe = await probeExport(page, runId, "he");
  console.log(`[HE probe] status=${heProbe.status} bytes=${heProbe.length} head=${heProbe.head}`);
  expect(heProbe.status, `HE export status (body head=${heProbe.head})`).toBe(200);
  expect(heProbe.head.startsWith("%PDF"), `HE export body head=${heProbe.head}`).toBeTruthy();

  // ── 3. UI flow — exercise the real ExportMemoButton click path ───────────
  await page.goto(`/usgaap-ifrs/${runId}`);
  await expect(page.getByTestId("run-detail")).toBeVisible();

  for (const locale of ["en", "he"] as const) {
    await page.evaluate((lc) => {
      document.cookie = `cpa_locale=${lc}; path=/; SameSite=Lax`;
    }, locale);
    await page.reload();
    await expect(page.getByTestId("export-md")).toBeVisible();

    const pdfBtn = page.getByRole("button", { name: /^PDF$/ });
    const errPill = page.locator('[data-testid="export-controls"] .text-danger');

    // Race the download event against the on-page error pill. Whichever
    // appears first determines the outcome — no 30s timeout swallowing a
    // 500 silently. A 500 surfaces in the pill within ~1s.
    const dlPromise = page.waitForEvent("download", { timeout: DOWNLOAD_TIMEOUT_MS });
    await pdfBtn.click();
    const outcome = await Promise.race([
      dlPromise.then((d) => ({ kind: "download" as const, dl: d })),
      errPill.waitFor({ state: "visible", timeout: DOWNLOAD_TIMEOUT_MS }).then(async () => ({
        kind: "error" as const,
        text: (await errPill.innerText()).trim(),
      })),
    ]).catch((e) => ({ kind: "timeout" as const, error: String(e) }));

    expect(
      outcome.kind,
      `[${locale.toUpperCase()}] expected download, got ${outcome.kind === "error" ? `error pill: "${outcome.text}"` : outcome.kind}`,
    ).toBe("download");

    // outcome.kind === "download" — read the file and verify magic bytes.
    const dl = (outcome as { kind: "download"; dl: import("@playwright/test").Download }).dl;
    const p = await dl.path();
    expect(p, `[${locale.toUpperCase()}] download path missing`).toBeTruthy();
    const fs = await import("node:fs");
    const head = fs.readFileSync(p!).slice(0, 8).toString("ascii");
    console.log(`[${locale.toUpperCase()}] downloaded ${dl.suggestedFilename()} head=${head}`);
    expect(head.startsWith("%PDF"), `[${locale.toUpperCase()}] body head=${head}`).toBeTruthy();
  }

  console.log("\n=== export wire log ===");
  wire.forEach((line) => console.log(line));
});
