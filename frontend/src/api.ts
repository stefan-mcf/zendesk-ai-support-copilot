import type {
  EngineeringHandoff,
  EvaluationReport,
  Suggestion,
  SupportCase,
  ZendeskStatus,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}/v1${path}`, { ...init, headers });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(payload?.detail ?? `Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

async function requestOrNull<T>(path: string): Promise<T | null> {
  const response = await fetch(`${API_BASE}/v1${path}`, {
    headers: { "Content-Type": "application/json" },
  });
  if (response.status === 404) return null;
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(payload?.detail ?? `Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export const api = {
  listCases: () => request<SupportCase[]>("/cases"),
  createSuggestion: (caseId: string) =>
    request<Suggestion>(`/cases/${encodeURIComponent(caseId)}/suggestions`, {
      method: "POST",
    }),
  runEvaluation: () =>
    request<EvaluationReport>("/evaluations/golden", { method: "POST" }),
  zendeskStatus: () =>
    request<ZendeskStatus>("/integrations/zendesk/status"),
  engineeringHandoff: (caseId: string) =>
    requestOrNull<EngineeringHandoff>(
      `/cases/${encodeURIComponent(caseId)}/handoffs/engineering`,
    ),
  approveEngineeringHandoff: (caseId: string) =>
    request<EngineeringHandoff>(
      `/cases/${encodeURIComponent(caseId)}/handoffs/engineering`,
      {
        method: "POST",
        body: JSON.stringify({
          decision: "approve",
          actor_id: "authenticated-operator",
        }),
      },
    ),
};
