"use client";

import { useEffect } from "react";

// Last-resort error boundary. Triggers when the root layout itself
// throws (rare — usually only when the cookies()/auth() handshake fails
// during cold start), or before any (app)/error.tsx can catch. Renders
// its own <html><body> because the normal layout is no longer in the
// tree. Locale-aware via the same cookie the root layout reads.
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[global-error.tsx]", error);
  }, [error]);

  // Can't call cookies() from a client component — best-effort lang via
  // document.documentElement which the root layout already set. Hebrew is
  // the app default, so anything other than an explicit "en" is treated
  // as Hebrew (covers the case where the lang attr isn't set yet).
  const isHebrew =
    typeof document === "undefined" || document.documentElement.lang !== "en";
  const title = isHebrew ? "משהו השתבש" : "Something went wrong";
  const hint = isHebrew
    ? "ייתכן שה־API עדיין מתחמם לאחר פריסה — נסו שוב בעוד 30–60 שניות."
    : "The API may still be warming up — try again in 30-60 seconds.";
  const retryLabel = isHebrew ? "נסה שוב" : "Retry";

  return (
    <html lang={isHebrew ? "he" : "en"} dir={isHebrew ? "rtl" : "ltr"}>
      <body
        style={{
          margin: 0,
          padding: "3rem 1rem",
          fontFamily:
            "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
          background: "#fafafa",
          color: "#171717",
          minHeight: "100vh",
        }}
      >
        <div
          style={{
            maxWidth: "32rem",
            margin: "0 auto",
            padding: "1.25rem",
            border: "1px solid #fecaca",
            background: "#fef2f2",
            borderRadius: "0.5rem",
          }}
        >
          <p
            style={{
              fontSize: "1rem",
              fontWeight: 600,
              color: "#b91c1c",
              margin: 0,
            }}
          >
            {title}
          </p>
          <p
            style={{ marginTop: "0.5rem", color: "#525252", fontSize: "0.875rem" }}
          >
            {hint}
          </p>
          {error.digest ? (
            <p
              style={{
                marginTop: "0.75rem",
                fontFamily: "ui-monospace, monospace",
                fontSize: "0.75rem",
                color: "#737373",
              }}
            >
              digest: {error.digest}
            </p>
          ) : null}
          <button
            onClick={() => reset()}
            style={{
              marginTop: "1rem",
              padding: "0.5rem 1rem",
              fontSize: "0.875rem",
              fontWeight: 500,
              color: "#fff",
              background: "#171717",
              border: "none",
              borderRadius: "0.375rem",
              cursor: "pointer",
            }}
          >
            {retryLabel}
          </button>
        </div>
      </body>
    </html>
  );
}
