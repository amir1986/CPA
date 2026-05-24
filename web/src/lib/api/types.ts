/**
 * Hand-rolled subset of the backend types. Once Phase 10 lands the
 * generated openapi-typescript output, this file is replaced by
 * `import type { components } from "./generated/openapi.d";`.
 */

export type User = {
  id: string;
  email: string;
  name: string | null;
  role: string;
  locale: string;
  firm_id: string;
  email_verified: boolean;
};

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
};

export type LoginOut = {
  tokens: TokenPair;
  user: User;
};

export type Engagement = {
  id: string;
  client_id: string;
  name: string;
  type: string;
  period_start: string | null;
  period_end: string | null;
  materiality: number | null;
  performance_materiality: number | null;
  status: string;
  created_at: string;
};

export type Client = {
  id: string;
  name: string;
  jurisdiction: string | null;
  base_currency: string | null;
  fy_end: string | null;
  created_at: string;
};

export type FileOut = {
  id: string;
  engagement_id: string;
  kind: string;
  original_name: string;
  s3_uri: string;
  sha256: string;
  mime: string | null;
  size: number;
  parsed_status: string;
  parsed_summary: Record<string, unknown> | null;
  created_at: string;
};

export type Citation = {
  standard: string | null;
  paragraph: string | null;
  url: string;
  quote: string;
};

export type Retrieved = {
  standard: string | null;
  paragraph: string | null;
  url: string;
  jurisdiction: string;
  corpus_type: string;
  language: string;
  score: number;
};

export type QueryOut = {
  answer: string;
  citations: Citation[];
  refused: boolean;
  language: string;
  retrieved: Retrieved[];
};

export type Source = {
  id: string;
  name: string;
  url: string;
  corpus_type: string;
  jurisdiction: string;
  language: string;
  licence: string;
};

export type Ratio = {
  name: string;
  period_end: string;
  value: number | null;
  numerator: number;
  denominator: number;
};

export type RatioRun = {
  period_end: string;
  ratios: Ratio[];
};

export type Sample = {
  id: string;
  method: string;
  seed: number;
  sample_size: number;
  sample_ids: string[];
};

export type JETestHit = {
  entry_id: string;
  amount: number;
  reason: string;
  extra: Record<string, unknown> | null;
};

export type JETestRun = {
  id: string;
  test_kind: string;
  hits_count: number;
  hits: JETestHit[];
};

export type AgentToolCall = {
  tool: string;
  arguments: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error?: string | null;
};

export type AgentRun = {
  id: string;
  request: string;
  final_answer: string | null;
  citations: unknown[];
  tool_calls: AgentToolCall[];
  created_at: string;
};

export type TrialBalanceRow = {
  id: string;
  period_end: string;
  account_id: string | null;
  account_code: string | null;
  account_name: string | null;
  opening: number;
  debit_total: number;
  credit_total: number;
  closing: number;
};

export type CoaAccount = {
  id: string;
  code: string;
  name: string;
  type: string;
  parent_id: string | null;
  currency: string | null;
  active: boolean;
};

export type GLEntry = {
  id: string;
  je_number: string | null;
  je_date: string | null;
  posting_date: string | null;
  account_id: string | null;
  debit: number;
  credit: number;
  currency: string | null;
  description: string | null;
  preparer: string | null;
  approver: string | null;
};

export type RotatorStatus = {
  backend: string;
  cursor: number;
  keys: Array<{
    key: string;
    status: "active" | "cooling" | "disabled";
    cooldown_remaining: number;
    consecutive_failures: number;
    last_error: string | null;
    requests: number;
  }>;
};

export type Tweaks = {
  top_k: number | null;
  min_score: number | null;
  lang_strict: boolean | null;
  ratio_overrides: Record<string, unknown> | null;
  sampling_overrides: Record<string, unknown> | null;
};

export type ComparisonRunSummary = {
  id: string;
  status: string;
  detected_framework: "US" | "IFRS" | null;
  override_framework: "US" | "IFRS" | null;
  issue_count: number;
  file_names: string[];
  created_at: string;
};

export type ComparisonUserCite = {
  ref: string;
  anchor: string;
  quote: string;
};

export type ComparisonIssue = {
  id: string;
  seq: number;
  topic: string;
  current_summary: string;
  current_user_cites: ComparisonUserCite[];
  gaap_summary: string | null;
  gaap_citations: Citation[];
  ifrs_summary: string | null;
  ifrs_citations: Citation[];
  differences: string | null;
  conversion_impact: string | null;
  gaap_verification: string | null;
  ifrs_verification: string | null;
};

export type ComparisonRunDetail = {
  id: string;
  status: string;
  detected_framework: "US" | "IFRS" | null;
  override_framework: "US" | "IFRS" | null;
  confidence: number | null;
  rationale: string | null;
  error: string | null;
  file_ids: string[];
  file_names: string[];
  issues: ComparisonIssue[];
  created_at: string;
};
