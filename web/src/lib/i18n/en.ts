/**
 * UI dictionaries for the USGAAP <> IFRS app.
 *
 * Adding a string:
 *   1. Add the key to the English dict below.
 *   2. Add the Hebrew translation to ./he.ts. Missing keys silently
 *      fall back to English (see ../i18n.ts::t).
 *   3. Use it in code:   `t("nav.engagements", locale)`
 *
 * Avoid:
 *   - Concatenating translated strings — pass interpolation via the
 *     second `vars` arg of t() instead.
 *   - Putting business logic in keys. Translations are leaf strings.
 */

// Plain object (no `as const`) so each leaf is typed as `string`, which
// lets the Hebrew dict supply any string — TS's `as const` literal-types
// would otherwise force the Hebrew translation to equal the English text.
export const en = {
  nav: {
    engagements: "Engagements",
    sources: "Sources",
    admin: "Admin",
    settings: "Settings",
    tweaks: "Tweaks",
    usgaap_ifrs: "USGAAP <> IFRS",
    dashboard: "Dashboard",
    chat: "Chat",
    documents: "Documents",
    books: "Books",
    analysis: "Analysis",
    audit: "Audit",
    compare: "Compare",
    traces: "Traces",
    skip_to_content: "Skip to content",
    search_placeholder: "Press ⌘K to search",
  },
  usgaap: {
    title: "USGAAP <> IFRS",
    landing_intro:
      "Upload an accounting policy, contract, financial statements, trial balance or GL. The model detects whether the content sits in US GAAP or IFRS, identifies the accounting issues inside it, then renders a per-issue side-by-side conversion with citations from the standards corpus.",
    drop_zone_title: "Drop a policy, contract, FS, TB or GL",
    drop_zone_hint: "PDF, DOCX, XLSX, CSV — up to 10 files, 50 MB each.",
    choose_files: "Choose files",
    uploading: "Uploading…",
    recent_runs: "Recent runs",
    no_runs_yet: "No runs yet — drop a file above to start your first comparison.",
    all_runs: "All runs",
    issue_count_one: "{n} issue",
    issue_count_many: "{n} issues",
    status_parsing: "Parsing files…",
    status_detecting: "Detecting framework…",
    status_comparing: "Comparing standards…",
    status_done: "Done",
    status_failed: "Failed",
    detected_framework: "Detected framework",
    confidence: "confidence",
    override_framework: "Override framework",
    confirm: "Confirm",
    confirmed: "Confirmed",
    us_gaap: "US GAAP",
    ifrs: "IFRS",
    current_treatment: "{fw} (current)",
    converted_to: "{fw} (converted to)",
    from_your_document: "From your document",
    from_standards: "From standards",
    source_paragraphs_verbatim: "Source paragraphs (verbatim)",
    verifier_agent: "Verifier agent",
    key_differences: "Key differences:",
    conversion_impact: "Conversion impact:",
    export_to_memo: "Export to memo",
    pdf: "PDF",
    no_standards_retrieved: "(no standards retrieved — corpus may be empty)",
    no_issues_identified: "The model didn't identify any accounting issues in the uploaded text. Try a more substantive policy or contract.",
    could_not_load: "Could not load run {id}",
  },
  settings: {
    profile_title: "Profile",
    profile_subtitle: "Your account on this firm.",
    language: "Language",
    language_hint:
      "Hebrew flips the page direction to right-to-left and is also used by the PDF memo export.",
    save: "Save",
    saved: "Saved",
    sign_out: "Sign out",
    email: "Email",
    name: "Name",
    role: "Role",
    firm_id: "Firm ID",
    email_verified: "Email verified",
    yes: "yes",
    no: "no",
  },
  common: {
    back: "Back",
    retry: "Retry",
    loading: "Loading…",
    error: "Error",
  },
};

export type Dict = typeof en;
