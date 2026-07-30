import "./styles.css";

const API_BASE = "https://support-copilot.example.com/v1";
const APP_TOKEN = "{{setting.api_token}}";

type Route = "draft" | "escalate" | "block";
type HandoffStatus = "approved" | "dispatched" | "completed" | "failed";

interface Citation {
  document_id: string;
  title: string;
  score: number;
  excerpt: string;
}

interface RiskFinding {
  code: string;
  severity: string;
  message: string;
}

interface Suggestion {
  route: Route;
  draft: string | null;
  confidence: number;
  citations: Citation[];
  risks: RiskFinding[];
  review_required: boolean;
}

interface Handoff {
  status: HandoffStatus;
  jira_issue_key: string | null;
  jira_issue_url: string | null;
}

interface SidebarState {
  suggestion: Suggestion | null;
  handoff: Handoff | null;
}

interface TicketContext {
  ticketId: string;
  subject: string;
  body: string;
  actorId: string;
}

interface AppState {
  ticket: TicketContext | null;
  suggestion: Suggestion | null;
  handoff: Handoff | null;
  loading: boolean;
  error: string | null;
}

export function buildRequest(
  path: string,
  method: "GET" | "POST",
  body?: unknown,
): ZAFRequestOptions {
  return {
    url: `${API_BASE}${path}`,
    type: method,
    contentType: "application/json",
    ...(body === undefined ? {} : { data: JSON.stringify(body) }),
    headers: {
      "X-Copilot-App-Token": APP_TOKEN,
    },
    secure: true,
    timeout: 30_000,
  };
}

function escapeHtml(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
      })[character] ?? character,
  );
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function routeLabel(route: Route): string {
  return route === "draft" ? "Draft ready" : route === "escalate" ? "Escalate" : "Blocked";
}

function handoffMarkup(handoff: Handoff | null): string {
  if (!handoff) {
    return `
      <button class="primary" data-action="approve">
        Approve Jira escalation
      </button>
      <p class="boundary">Adds one private note and one Zendesk tag. No customer reply.</p>
    `;
  }
  if (handoff.status === "completed" && handoff.jira_issue_url) {
    return `
      <a class="primary link-button" href="${escapeHtml(handoff.jira_issue_url)}"
         target="_blank" rel="noreferrer">
        Open ${escapeHtml(handoff.jira_issue_key ?? "Jira issue")}
      </a>
      <p class="success">Jira issue key verified and recorded.</p>
    `;
  }
  if (handoff.status === "failed") {
    return `<p class="error-copy">Dispatch stopped safely. Operator reconciliation is required.</p>`;
  }
  return `<p class="success">Zendesk dispatch verified. Waiting for Jira issue-key callback.</p>`;
}

function render(root: HTMLElement, state: AppState): void {
  if (state.loading) {
    root.innerHTML = `<div class="loading">Working…</div>`;
    return;
  }
  if (state.error) {
    root.innerHTML = `
      <section class="shell">
        <header><span class="eyebrow">AI operations</span><h1>Support Copilot</h1></header>
        <div class="error-copy" role="alert">${escapeHtml(state.error)}</div>
        <button class="secondary" data-action="retry">Retry</button>
      </section>
    `;
    return;
  }
  if (!state.ticket) {
    root.innerHTML = `<div class="error-copy" role="alert">Ticket context is unavailable.</div>`;
    return;
  }

  const suggestion = state.suggestion;
  root.innerHTML = `
    <section class="shell">
      <header>
        <span class="eyebrow">Human-reviewed AI</span>
        <h1>Support Copilot</h1>
        <p>Grounded guidance inside the ticket workspace.</p>
      </header>

      ${
        suggestion
          ? `
            <section class="decision">
              <div class="decision-top">
                <span class="route route-${suggestion.route}">
                  ${routeLabel(suggestion.route)}
                </span>
                <span class="confidence">${percent(suggestion.confidence)}</span>
              </div>
              ${
                suggestion.draft
                  ? `<div class="draft"><strong>Private draft</strong><p>${escapeHtml(suggestion.draft)}</p></div>`
                  : `<p class="no-draft">No customer-facing draft was produced.</p>`
              }
              ${
                suggestion.citations.length
                  ? `<div class="evidence"><strong>Knowledge evidence</strong>${suggestion.citations
                      .slice(0, 2)
                      .map(
                        (citation) => `
                          <article>
                            <span>${escapeHtml(citation.document_id)} · ${percent(citation.score)}</span>
                            <strong>${escapeHtml(citation.title)}</strong>
                            <p>${escapeHtml(citation.excerpt)}</p>
                          </article>
                        `,
                      )
                      .join("")}</div>`
                  : ""
              }
              ${
                suggestion.risks.length
                  ? `<div class="risks"><strong>Safety signals</strong>${suggestion.risks
                      .map(
                        (risk) => `
                          <article>
                            <span>${escapeHtml(risk.severity)}</span>
                            <p>${escapeHtml(risk.message)}</p>
                          </article>
                        `,
                      )
                      .join("")}</div>`
                  : ""
              }
            </section>
            ${
              suggestion.route === "escalate"
                ? `<section class="handoff"><span class="eyebrow">Human approval</span>
                    <h2>Engineering handoff</h2>${handoffMarkup(state.handoff)}</section>`
                : ""
            }
          `
          : `
            <section class="ready">
              <div class="shield">✓</div>
              <h2>Ready to review</h2>
              <p>Analyse the current ticket for a grounded decision, citations, and safety signals.</p>
              <button class="primary" data-action="analyse">Analyse ticket</button>
            </section>
          `
      }
    </section>
  `;
}

function messageFromError(reason: unknown): string {
  if (reason instanceof Error) return reason.message;
  if (typeof reason === "object" && reason !== null) {
    const response = reason as { responseJSON?: { detail?: string }; statusText?: string };
    return response.responseJSON?.detail ?? response.statusText ?? "Request failed";
  }
  return "Request failed";
}

async function loadTicket(client: ZAFClientInstance): Promise<TicketContext> {
  const [context, values] = await Promise.all([
    client.context(),
    client.get(["ticket.subject", "ticket.description", "currentUser.id"]),
  ]);
  const ticketId = String(context.ticketId ?? "");
  const subject = String(values["ticket.subject"] ?? "").trim();
  const body = String(values["ticket.description"] ?? "").trim();
  const actorId = String(values["currentUser.id"] ?? "").trim();
  if (!/^[1-9][0-9]*$/.test(ticketId) || !subject || !body || !actorId) {
    throw new Error("Save the ticket subject and description before running Support Copilot.");
  }
  return { ticketId, subject, body, actorId };
}

async function initialize(): Promise<void> {
  const root = document.querySelector<HTMLElement>("#app");
  if (!root) return;
  const appRoot = root;
  const client = ZAFClient.init();
  const state: AppState = {
    ticket: null,
    suggestion: null,
    handoff: null,
    loading: true,
    error: null,
  };

  async function refresh(): Promise<void> {
    state.loading = true;
    state.error = null;
    render(appRoot, state);
    try {
      state.ticket = await loadTicket(client);
      try {
        const current = await client.request<SidebarState>(
          buildRequest(`/sidebar/tickets/${state.ticket.ticketId}`, "GET"),
        );
        state.suggestion = current.suggestion;
        state.handoff = current.handoff;
      } catch (reason) {
        const status = (reason as { status?: number }).status;
        if (status !== 404) throw reason;
      }
    } catch (reason) {
      state.error = messageFromError(reason);
    } finally {
      state.loading = false;
      render(appRoot, state);
      await client.invoke("resize", { height: Math.min(document.body.scrollHeight + 16, 720) });
    }
  }

  appRoot.addEventListener("click", (event) => {
    const target = (event.target as HTMLElement).closest<HTMLElement>("[data-action]");
    if (!target || !state.ticket) return;
    const action = target.dataset.action;
    if (action === "retry") {
      void refresh();
      return;
    }
    state.loading = true;
    state.error = null;
    render(appRoot, state);
    if (action === "analyse") {
      void client
        .request<SidebarState>(
          buildRequest(`/sidebar/tickets/${state.ticket.ticketId}/suggestions`, "POST", {
            subject: state.ticket.subject,
            body: state.ticket.body,
          }),
        )
        .then((response) => {
          state.suggestion = response.suggestion;
          state.handoff = response.handoff;
        })
        .catch((reason: unknown) => {
          state.error = messageFromError(reason);
        })
        .finally(() => {
          state.loading = false;
          render(appRoot, state);
          void client.invoke("resize", {
            height: Math.min(document.body.scrollHeight + 16, 720),
          });
        });
      return;
    }
    if (action === "approve") {
      void client
        .request<Handoff>(
          buildRequest(
            `/sidebar/tickets/${state.ticket.ticketId}/handoffs/engineering`,
            "POST",
            {
              decision: "approve",
              actor_id: state.ticket.actorId,
            },
          ),
        )
        .then((response) => {
          state.handoff = response;
        })
        .catch((reason: unknown) => {
          state.error = messageFromError(reason);
        })
        .finally(() => {
          state.loading = false;
          render(appRoot, state);
        });
    }
  });

  await refresh();
}

if (typeof ZAFClient !== "undefined") {
  void initialize();
}
