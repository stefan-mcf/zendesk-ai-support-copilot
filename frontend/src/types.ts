export type Route = "draft" | "escalate" | "block";

export interface SupportCase {
  id: string;
  subject: string;
  body: string;
  source: string;
  source_ref: string | null;
  created_at: string;
}

export interface Citation {
  document_id: string;
  chunk_id: string;
  title: string;
  score: number;
  excerpt: string;
}

export interface RiskFinding {
  code: string;
  severity: "low" | "medium" | "high" | "critical";
  message: string;
  blocks_draft: boolean;
}

export interface Suggestion {
  case_id: string;
  route: Route;
  draft: string | null;
  confidence: number;
  citations: Citation[];
  risks: RiskFinding[];
  review_required: boolean;
  policy_version: string;
  generated_at: string;
}

export interface EngineeringHandoff {
  id: string;
  case_id: string;
  provider_ticket_id: string;
  status: "approved" | "dispatched" | "completed" | "failed";
  approved_by: string;
  approval_source: "copilot_web" | "zendesk_sidebar";
  zendesk_receipt_state: string | null;
  jira_issue_key: string | null;
  jira_issue_url: string | null;
  failure_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface EvaluationItem {
  case_id: string;
  expected_route: string;
  actual_route: string;
  route_correct: boolean;
  expected_article_ids: string[];
  retrieved_article_ids: string[];
  citation_recall: number;
  expected_risk_tags: string[];
  risks: string[];
  risk_recall: number;
  draft_present: boolean;
  citation_markers_valid: boolean;
  sensitive_data_leak: boolean;
  review_required: boolean;
  latency_ms: number;
}

export interface EvaluationReport {
  dataset_id: string;
  provider: string;
  total: number;
  route_accuracy: number;
  citation_recall: number;
  risk_recall: number;
  unsafe_draft_rate: number;
  grounded_draft_rate: number;
  review_gate_rate: number;
  sensitive_data_leak_rate: number;
  latency_ms_p50: number;
  latency_ms_p95: number;
  route_counts: Record<Route, number>;
  passed: boolean;
  thresholds: Record<string, number>;
  items: EvaluationItem[];
  generated_at: string;
}

export interface ZendeskStatus {
  state: string;
  subdomain: string;
  role: string;
  verified: boolean;
  secret_source: string;
}
