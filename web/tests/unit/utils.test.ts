import { describe, expect, it } from "vitest";

import { cn } from "@/lib/utils";

describe("cn", () => {
  it("merges class names, prefers later Tailwind classes on conflict", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
    expect(cn("text-fg", null, undefined, "text-fg-muted", false)).toBe("text-fg-muted");
  });

  it("accepts conditional class values", () => {
    expect(cn("base", { active: true, hidden: false })).toBe("base active");
  });
});
