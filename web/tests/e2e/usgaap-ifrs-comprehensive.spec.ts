/**
 * Comprehensive live test for USGAAP <> IFRS against the deployed stack.
 *
 *   BASE_URL=https://cpa-web-01mj.onrender.com \
 *     pnpm exec playwright test tests/e2e/usgaap-ifrs-comprehensive.spec.ts \
 *     --project=chromium --workers=1
 *
 * Coverage:
 *   1. Sidebar + landing page chrome
 *   2. List endpoint returns 200 + array
 *   3. Single-DOCX upload → status transitions → terminal state
 *   4. CSV-only upload — exercises a non-DOCX extractor path
 *   5. Multi-file (DOCX + CSV) upload + memo export when terminal=done
 *   6. Framework override endpoint round-trip
 *   7. Stream endpoint emits SSE frames
 *   8. Validation: empty upload → 400; unsupported file → 400
 *
 * The orchestrator's "done" outcome depends on the live LLM + standards
 * corpus, so happy-path assertions branch on terminal status. The
 * structural assertions (run created, status cycles, error surfaced when
 * needed, memo download starts when done) are the deterministic guarantees.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES = path.resolve(HERE, "..", "fixtures", "comparison");

// Sandbox clock skew rejects the deployed cert; allow at the spec level.
test.use({ ignoreHTTPSErrors: true });

// Live deploy uses the shared Skip → Demo User account. Reuse it across
// tests; serial execution (workers=1) keeps things stable.
async function skipLogin(page: Page): Promise<void> {
  // Already signed in?
  const dest = await page.goto("/usgaap-ifrs", { waitUntil: "domcontentloaded" });
  if (dest && !page.url().includes("/login")) return;

  await page.goto("/login", { waitUntil: "domcontentloaded" });
  const skip = page.getByRole("button", { name: /Skip.*Demo User/i });
  await expect(skip).toBeVisible({ timeout: 30_000 });
  await Promise.all([
    page.waitForURL(/\/engagements/, { timeout: 90_000 }),
    skip.click(),
  ]);
}

async function uploadAndWait(
  page: Page,
  fixtures: string[],
  { terminalTimeoutMs = 180_000 }: { terminalTimeoutMs?: number } = {},
): Promise<{ runId: string; terminal: string; errorText: string | null }> {
  await page.goto("/usgaap-ifrs");
  await expect(page.getByRole("heading", { name: /USGAAP <> IFRS/i })).toBeVisible();

  // Capture every /comparison/* response for failure diagnostics.
  const wire: string[] = [];
  page.on("response", async (r) => {
    const u = r.url();
    if (u.includes("/comparison/")) {
      const body = await r.text().catch(() => "");
      wire.push(`${r.status()} ${r.request().method()} ${u} :: ${body.slice(0, 160)}`);
    }
  });

  await page.locator('input[type="file"]').setInputFiles(fixtures);

  try {
    await page.waitForURL(/\/usgaap-ifrs\/[0-9a-f-]{36}$/, { timeout: 60_000 });
  } catch (err) {
    console.log("\n=== /comparison wire log ===");
    wire.forEach((l) => console.log(l));
    throw err;
  }

  const runId = page.url().split("/").pop()!;
  const pill = page.getByTestId("run-status");
  await expect(pill).toBeVisible();

  await expect
    .poll(async () => pill.getAttribute("data-status"), {
      timeout: terminalTimeoutMs,
      intervals: [1000, 2000, 4000, 8000],
    })
    .toMatch(/^(done|failed)$/);

  const terminal = (await pill.getAttribute("data-status")) ?? "";
  let errorText: string | null = null;
  const errEl = page.getByTestId("run-error");
  if (await errEl.count()) {
    errorText = (await errEl.innerText()).trim();
  }
  console.log(`[run ${runId}] terminal=${terminal} error=${errorText ?? "(none)"}`);
  return { runId, terminal, errorText };
}

test.describe("USGAAP <> IFRS — comprehensive live", () => {
  test("01 sidebar entry visible + landing chrome", async ({ page }) => {
    await skipLogin(page);
    const link = page.getByRole("link", { name: /USGAAP <> IFRS/i });
    await expect(link).toBeVisible();
    await link.click();
    await page.waitForURL("**/usgaap-ifrs");
    await expect(page.getByRole("heading", { name: /USGAAP <> IFRS/i })).toBeVisible();
    await expect(page.getByText(/Drop a policy, contract, FS, TB or GL/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /Choose files/i })).toBeVisible();
    // Recent-runs section header is always present.
    await expect(page.getByRole("heading", { name: /Recent runs/i })).toBeVisible();
  });

  test("02 listing endpoint returns 200 + array via the rewrite", async ({ page }) => {
    await skipLogin(page);
    const out = await page.evaluate(async () => {
      const r = await fetch("/api/comparison/runs");
      const t = await r.text();
      let parsed: unknown = null;
      try { parsed = JSON.parse(t); } catch { /* keep null */ }
      return { status: r.status, snippet: t.slice(0, 200), parsed };
    });
    expect(out.status).toBe(200);
    expect(Array.isArray(out.parsed)).toBe(true);
  });

  test("03 single-DOCX upload reaches a terminal status", async ({ page }) => {
    test.setTimeout(240_000);
    await skipLogin(page);
    const r = await uploadAndWait(page, [path.join(FIXTURES, "policy.docx")]);
    expect(["done", "failed"]).toContain(r.terminal);
    if (r.terminal === "failed") {
      expect(r.errorText).not.toBeNull();
      // The python-docx missing-extras error must NOT reappear — that was the bug fd3b382 fixed.
      expect(r.errorText).not.toMatch(/python-docx not installed/i);
    }
  });

  test("04 CSV-only upload reaches a terminal status (non-DOCX extractor path)", async ({ page }) => {
    test.setTimeout(240_000);
    await skipLogin(page);
    const r = await uploadAndWait(page, [path.join(FIXTURES, "gl.csv")]);
    expect(["done", "failed"]).toContain(r.terminal);
    if (r.terminal === "failed" && r.errorText) {
      // CSV path doesn't need python-docx or pdfplumber.
      expect(r.errorText).not.toMatch(/python-docx not installed|pdfplumber not installed/i);
    }
  });

  test("05 multi-file (DOCX + CSV) upload + memo export when done", async ({ page }) => {
    test.setTimeout(300_000);
    await skipLogin(page);
    const r = await uploadAndWait(page, [
      path.join(FIXTURES, "policy.docx"),
      path.join(FIXTURES, "gl.csv"),
    ]);

    if (r.terminal === "done") {
      // FrameworkConfirm renders whenever detection completes.
      await expect(page.getByTestId("framework-confirm")).toBeVisible();

      const issueCount = await page.locator('[data-testid="issue-card"]').count();
      if (issueCount > 0) {
        await expect(page.getByTestId("pane-current").first()).toBeVisible();
        await expect(page.getByTestId("pane-other").first()).toBeVisible();

        const exportBtn = page.getByTestId("export-md");
        await expect(exportBtn).toBeVisible();
        const [download] = await Promise.all([
          page.waitForEvent("download"),
          exportBtn.click(),
        ]);
        expect(download.suggestedFilename()).toMatch(/\.md$/);
        const dl = await download.path();
        if (dl) {
          const body = fs.readFileSync(dl, "utf-8");
          expect(body).toContain("DRAFT — REQUIRES PARTNER REVIEW");
          expect(body).toContain("US GAAP");
          expect(body).toContain("IFRS");
        }
      } else {
        // No issues identified is a tolerated outcome on empty standards corpus.
        await expect(page.getByText(/didn't identify any accounting issues/i)).toBeVisible();
      }
    } else {
      // Failed with a reason that's NOT the python-docx regression.
      expect(r.errorText).not.toBeNull();
      expect(r.errorText).not.toMatch(/python-docx not installed/i);
    }
  });

  test("06 framework override endpoint round-trips", async ({ page }) => {
    test.setTimeout(180_000);
    await skipLogin(page);
    // Start a tiny run so we have one to override against.
    await page.goto("/usgaap-ifrs");
    await page.locator('input[type="file"]').setInputFiles(path.join(FIXTURES, "gl.csv"));
    await page.waitForURL(/\/usgaap-ifrs\/[0-9a-f-]{36}$/, { timeout: 60_000 });
    const runId = page.url().split("/").pop()!;

    const out = await page.evaluate(async (rid) => {
      const r = await fetch(`/api/comparison/runs/${rid}/framework`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ framework: "IFRS" }),
      });
      const body = await r.json().catch(() => ({}));
      return { status: r.status, body };
    }, runId);
    expect(out.status).toBe(200);
    expect((out.body as { override_framework?: string }).override_framework).toBe("IFRS");
  });

  test("07 stream endpoint emits SSE frames", async ({ page }) => {
    test.setTimeout(120_000);
    await skipLogin(page);
    // Re-use the most recent run (or create one).
    await page.goto("/usgaap-ifrs");
    await page.locator('input[type="file"]').setInputFiles(path.join(FIXTURES, "gl.csv"));
    await page.waitForURL(/\/usgaap-ifrs\/[0-9a-f-]{36}$/, { timeout: 60_000 });
    const runId = page.url().split("/").pop()!;

    // Read SSE events with a hard per-chunk deadline. The previous version
    // blocked on reader.read() when the stream stayed open between events;
    // race the read against a timer so the loop always makes progress.
    const events = await page.evaluate(async (rid) => {
      const r = await fetch(`/api/comparison/runs/${rid}/stream`, {
        headers: { Accept: "text/event-stream" },
      });
      if (!r.body) return [];
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      const out: { event: string; data: string }[] = [];
      const overallDeadline = Date.now() + 30_000;

      const readWithTimeout = (ms: number) =>
        Promise.race<{ done: boolean; value?: Uint8Array; timedOut?: boolean }>([
          reader.read().then((v) => ({ ...v })),
          new Promise((resolve) =>
            setTimeout(() => resolve({ done: false, timedOut: true }), ms),
          ),
        ]);

      while (Date.now() < overallDeadline && out.length < 3) {
        const remaining = overallDeadline - Date.now();
        const r2 = await readWithTimeout(Math.min(remaining, 6_000));
        if (r2.timedOut) continue;
        if (r2.done) break;
        buf += dec.decode(r2.value!, { stream: true });
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          let event = "message";
          let data = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (data) out.push({ event, data });
          if (out.length >= 3) break;
        }
      }
      try { await reader.cancel(); } catch { /* ignore */ }
      return out;
    }, runId);

    expect(events.length).toBeGreaterThan(0);
    const statusEvts = events.filter((e) => e.event === "status");
    expect(statusEvts.length).toBeGreaterThan(0);
    const first = JSON.parse(statusEvts[0].data) as { status?: string };
    expect(["parsing", "detecting", "comparing", "done", "failed"]).toContain(first.status);
  });

  test("08 validation: empty upload returns 400; unsupported file returns 400", async ({ page }) => {
    await skipLogin(page);
    const empty = await page.evaluate(async () => {
      const fd = new FormData();
      const r = await fetch("/api/comparison/runs", { method: "POST", body: fd });
      return { status: r.status, body: await r.text().catch(() => "") };
    });
    expect([400, 422]).toContain(empty.status);

    const bad = await page.evaluate(async () => {
      const fd = new FormData();
      const blob = new Blob(["fake exe contents"], { type: "application/octet-stream" });
      fd.append("files", blob, "malware.exe");
      const r = await fetch("/api/comparison/runs", { method: "POST", body: fd });
      return { status: r.status, body: await r.text().catch(() => "") };
    });
    expect(bad.status).toBe(400);
    expect(bad.body.toLowerCase()).toMatch(/unsupported|file/);
  });

  test("09 run detail page renders for a known-good run id", async ({ page }) => {
    await skipLogin(page);
    // Pull the latest run from the list and visit its detail page.
    const runs = await page.evaluate(async () => {
      const r = await fetch("/api/comparison/runs");
      return (await r.json()) as { id: string; status: string }[];
    });
    if (runs.length === 0) test.skip(true, "no prior runs to inspect");
    const id = runs[0].id;
    await page.goto(`/usgaap-ifrs/${id}`);
    await expect(page.getByTestId("run-detail")).toBeVisible();
    await expect(page.getByTestId("run-status")).toBeVisible();
  });
});
