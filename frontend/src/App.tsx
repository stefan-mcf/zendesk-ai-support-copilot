import { useEffect, useMemo, useState } from "react";
import {
  Badge,
  Button,
  FluentProvider,
  Skeleton,
  SkeletonItem,
  Tab,
  TabList,
  Text,
  Textarea,
  webDarkTheme,
  webLightTheme,
  type TabValue,
} from "@fluentui/react-components";
import {
  ArrowClockwise24Regular,
  Beaker24Regular,
  Clipboard24Regular,
  DocumentSearch24Regular,
  Open24Regular,
  PlugConnected24Regular,
  ShieldCheckmark24Regular,
  WeatherMoon24Regular,
  WeatherSunny24Regular,
} from "@fluentui/react-icons";

import { api } from "./api";
import type {
  EngineeringHandoff,
  EvaluationReport,
  Route,
  Suggestion,
  SupportCase,
  ZendeskStatus,
} from "./types";

type View = "queue" | "evaluation" | "integrations";
type ThemeMode = "light" | "dark";

const routeLabel: Record<Route, string> = {
  draft: "Draft ready",
  escalate: "Escalate",
  block: "Blocked",
};

const lightTheme = {
  ...webLightTheme,
  colorBrandBackground: "#0d5345",
  colorBrandBackgroundHover: "#0a463a",
  colorBrandBackgroundPressed: "#08382f",
  colorBrandForeground1: "#0d5345",
  colorBrandForeground2: "#176b5a",
  colorCompoundBrandForeground1: "#0d5345",
  colorCompoundBrandStroke: "#0d5345",
  colorCompoundBrandStrokeHover: "#0a463a",
};

const darkTheme = {
  ...webDarkTheme,
  colorBrandBackground: "#176b5a",
  colorBrandBackgroundHover: "#20806b",
  colorBrandBackgroundPressed: "#0d5345",
  colorBrandForeground1: "#77c8b2",
  colorBrandForeground2: "#58b69e",
  colorCompoundBrandForeground1: "#77c8b2",
  colorCompoundBrandStroke: "#77c8b2",
  colorCompoundBrandStrokeHover: "#9bdac8",
};

function usePreferredTheme(): ThemeMode {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function percentage(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function RouteBadge({ route }: { route: Route }) {
  const color = route === "draft" ? "success" : route === "block" ? "danger" : "warning";
  return (
    <Badge appearance="filled" color={color} size="medium">
      {routeLabel[route]}
    </Badge>
  );
}

function LoadingQueue() {
  return (
    <div className="loading-grid" aria-label="Loading support cases">
      <Skeleton className="loading-list">
        {Array.from({ length: 5 }, (_, index) => (
          <div className="loading-row" key={index}>
            <SkeletonItem size={16} />
            <SkeletonItem size={12} />
          </div>
        ))}
      </Skeleton>
      <Skeleton className="loading-workspace">
        <SkeletonItem size={32} />
        <SkeletonItem size={16} />
        <SkeletonItem className="loading-block" />
      </Skeleton>
    </div>
  );
}

function DraftEditor({ suggestion }: { suggestion: Suggestion }) {
  const [draft, setDraft] = useState(suggestion.draft ?? "");
  const [copied, setCopied] = useState(false);

  async function copyDraft() {
    if (!draft) return;
    await navigator.clipboard.writeText(draft);
    setCopied(true);
  }

  return (
    <div className="draft-field">
      <label htmlFor="review-draft">Private draft</label>
      <p id="draft-helper">Edit locally, then copy for an approved downstream workflow.</p>
      <Textarea
        id="review-draft"
        aria-describedby="draft-helper"
        value={draft}
        onChange={(_, data) => {
          setDraft(data.value);
          setCopied(false);
        }}
        resize="vertical"
        size="large"
      />
      <Button
        appearance="secondary"
        icon={<Clipboard24Regular />}
        onClick={copyDraft}
        disabled={!draft}
      >
        {copied ? "Copied" : "Copy draft"}
      </Button>
    </div>
  );
}

function EngineeringHandoffPanel({
  supportCase,
  handoff,
  loading,
  onApprove,
}: {
  supportCase: SupportCase;
  handoff: EngineeringHandoff | null;
  loading: boolean;
  onApprove: () => void;
}) {
  const providerBacked = ["zendesk_live_controlled", "zendesk_sidebar"].includes(
    supportCase.source,
  );

  return (
    <section className="handoff-panel" aria-label="Engineering handoff">
      <div>
        <span className="section-label">Human approval</span>
        <h3>Zendesk → Jira engineering handoff</h3>
        {!providerBacked ? (
          <p>Provider dispatch is available only for a Zendesk-backed case.</p>
        ) : handoff?.status === "completed" ? (
          <p>
            Jira returned a verified issue key. The Zendesk approval and Jira completion are both
            recorded in the audit trail.
          </p>
        ) : handoff?.status === "dispatched" ? (
          <p>Zendesk accepted the private note and escalation tag. Waiting for Jira readback.</p>
        ) : handoff?.status === "failed" ? (
          <p>
            Dispatch failed safely. An operator must reconcile the provider state before retrying.
          </p>
        ) : (
          <p>
            This action adds one private Zendesk audit note and the approved escalation tag. It
            never sends a customer reply.
          </p>
        )}
      </div>
      {handoff?.status === "completed" && handoff.jira_issue_url ? (
        <Button
          as="a"
          appearance="primary"
          icon={<Open24Regular />}
          href={handoff.jira_issue_url}
          target="_blank"
          rel="noreferrer"
        >
          Open {handoff.jira_issue_key}
        </Button>
      ) : (
        <Button
          appearance="primary"
          icon={<PlugConnected24Regular />}
          onClick={onApprove}
          disabled={!providerBacked || loading || handoff !== null}
        >
          {loading ? "Dispatching" : "Approve Jira escalation"}
        </Button>
      )}
    </section>
  );
}

function QueueView({
  cases,
  selected,
  suggestion,
  handoff,
  loadingSuggestion,
  loadingHandoff,
  onSelect,
  onSuggest,
  onApproveHandoff,
}: {
  cases: SupportCase[];
  selected: SupportCase | null;
  suggestion: Suggestion | null;
  handoff: EngineeringHandoff | null;
  loadingSuggestion: boolean;
  loadingHandoff: boolean;
  onSelect: (supportCase: SupportCase) => void;
  onSuggest: () => void;
  onApproveHandoff: () => void;
}) {
  if (!selected) {
    return (
      <section className="empty-state">
        <DocumentSearch24Regular />
        <h2>No cases available</h2>
        <p>Load the synthetic fixture set to start a safe review session.</p>
      </section>
    );
  }

  return (
    <div className="queue-layout">
      <aside className="case-list" aria-label="Support cases">
        <div className="panel-heading">
          <div>
            <span className="section-label">Review queue</span>
            <h2>{cases.length} review cases</h2>
          </div>
        </div>
        <div className="case-scroll">
          {cases.map((supportCase) => (
            <button
              type="button"
              key={supportCase.id}
              className={`case-row ${selected.id === supportCase.id ? "selected" : ""}`}
              onClick={() => onSelect(supportCase)}
              aria-pressed={selected.id === supportCase.id}
            >
              <span className="case-id">{supportCase.id}</span>
              <span className="case-subject">{supportCase.subject}</span>
              <span className="case-preview">{supportCase.body}</span>
            </button>
          ))}
        </div>
      </aside>

      <main className="review-workspace">
        <section className="case-context">
          <div className="case-title-row">
            <div>
              <span className="case-id">{selected.id}</span>
              <h1>{selected.subject}</h1>
            </div>
            <Badge
              appearance="outline"
              color={selected.source === "zendesk_live_controlled" ? "success" : "informative"}
            >
              {selected.source === "zendesk_live_controlled"
                ? "Controlled Zendesk ticket"
                : "Synthetic fixture"}
            </Badge>
          </div>
          <p>{selected.body}</p>
        </section>

        <section className="suggestion-panel" aria-live="polite">
          <div className="panel-heading">
            <div>
              <span className="section-label">Copilot output</span>
              <h2>Grounded response review</h2>
            </div>
            <Button
              appearance="primary"
              icon={<Beaker24Regular />}
              onClick={onSuggest}
              disabled={loadingSuggestion}
            >
              {loadingSuggestion ? "Generating" : "Generate suggestion"}
            </Button>
          </div>

          {loadingSuggestion && (
            <Skeleton className="suggestion-skeleton" aria-label="Generating suggestion">
              <SkeletonItem size={24} />
              <SkeletonItem className="loading-block" />
              <SkeletonItem size={16} />
            </Skeleton>
          )}

          {!loadingSuggestion && !suggestion && (
            <div className="not-generated">
              <ShieldCheckmark24Regular />
              <div>
                <h3>Human review starts here</h3>
                <p>
                  Generate a private suggestion. This workspace has no send or ticket-write
                  action.
                </p>
              </div>
            </div>
          )}

          {!loadingSuggestion && suggestion && (
            <div className="suggestion-content">
              <div className="decision-strip">
                <RouteBadge route={suggestion.route} />
                <div>
                  <span>Confidence</span>
                  <strong>{percentage(suggestion.confidence)}</strong>
                </div>
                <div>
                  <span>Policy</span>
                  <strong>{suggestion.policy_version}</strong>
                </div>
                <div>
                  <span>Review</span>
                  <strong>{suggestion.review_required ? "Required" : "Not required"}</strong>
                </div>
              </div>

              {suggestion.draft ? (
                <DraftEditor
                  key={`${suggestion.case_id}:${suggestion.generated_at}`}
                  suggestion={suggestion}
                />
              ) : (
                <div className="no-draft">
                  <ShieldCheckmark24Regular />
                  <div>
                    <h3>No draft was produced</h3>
                    <p>The routing decision requires specialist handling or blocks generation.</p>
                  </div>
                </div>
              )}

              {suggestion.route === "escalate" && (
                <EngineeringHandoffPanel
                  supportCase={selected}
                  handoff={handoff}
                  loading={loadingHandoff}
                  onApprove={onApproveHandoff}
                />
              )}

              <div className="evidence-grid">
                <section>
                  <h3>Knowledge evidence</h3>
                  {suggestion.citations.length ? (
                    <div className="evidence-list">
                      {suggestion.citations.map((citation) => (
                        <article key={citation.chunk_id}>
                          <header>
                            <strong>
                              {citation.document_id}: {citation.title}
                            </strong>
                            <span>{percentage(citation.score)}</span>
                          </header>
                          <p>{citation.excerpt}</p>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="muted">No relevant knowledge passed retrieval.</p>
                  )}
                </section>

                <section>
                  <h3>Safety findings</h3>
                  {suggestion.risks.length ? (
                    <div className="risk-list">
                      {suggestion.risks.map((risk) => (
                        <article key={risk.code}>
                          <Badge
                            appearance="tint"
                            color={
                              risk.severity === "critical" || risk.severity === "high"
                                ? "danger"
                                : "warning"
                            }
                          >
                            {risk.severity}
                          </Badge>
                          <div>
                            <strong>{risk.code.replaceAll("_", " ")}</strong>
                            <p>{risk.message}</p>
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="muted">No policy risks detected in this fixture.</p>
                  )}
                </section>
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

function EvaluationView({
  report,
  loading,
  onRun,
}: {
  report: EvaluationReport | null;
  loading: boolean;
  onRun: () => void;
}) {
  return (
    <main className="page-panel">
      <div className="page-intro">
        <span className="section-label">Release gate</span>
        <h1>Golden-set evaluation</h1>
        <p>
          Validate routing, retrieval, and guardrail behavior before deployment.
        </p>
        <Button appearance="primary" icon={<Beaker24Regular />} onClick={onRun} disabled={loading}>
          {loading ? "Evaluating" : "Run evaluation"}
        </Button>
      </div>

      {loading && (
        <Skeleton className="evaluation-skeleton">
          <SkeletonItem className="metric-skeleton" />
          <SkeletonItem className="metric-skeleton" />
          <SkeletonItem className="metric-skeleton" />
        </Skeleton>
      )}

      {!loading && !report && (
        <section className="empty-state embedded">
          <Beaker24Regular />
          <h2>No evaluation run yet</h2>
          <p>
            The 40-case synthetic suite is ready to test routing, grounding, safety, and the
            configured model provider.
          </p>
        </section>
      )}

      {!loading && report && (
        <>
          <div className="evidence-note">
            <strong>{report.total} cases</strong>
            <span>{report.provider}</span>
            <span>{report.dataset_id}</span>
          </div>
          <section className="metric-grid" aria-label="Evaluation metrics">
            <article>
              <span>Route accuracy</span>
              <strong>{percentage(report.route_accuracy)}</strong>
              <Text>{percentage(report.thresholds.route_accuracy)} required</Text>
            </article>
            <article>
              <span>Citation recall</span>
              <strong>{percentage(report.citation_recall)}</strong>
              <Text>{percentage(report.thresholds.citation_recall)} required</Text>
            </article>
            <article>
              <span>Risk recall</span>
              <strong>{percentage(report.risk_recall)}</strong>
              <Text>{percentage(report.thresholds.risk_recall)} required</Text>
            </article>
            <article>
              <span>Unsafe draft rate</span>
              <strong>{percentage(report.unsafe_draft_rate)}</strong>
              <Text>{percentage(report.thresholds.unsafe_draft_rate)} maximum</Text>
            </article>
            <article>
              <span>Grounded drafts</span>
              <strong>{percentage(report.grounded_draft_rate)}</strong>
              <Text>{percentage(report.thresholds.grounded_draft_rate)} required</Text>
            </article>
            <article>
              <span>Human-review gate</span>
              <strong>{percentage(report.review_gate_rate)}</strong>
              <Text>{percentage(report.thresholds.review_gate_rate)} required</Text>
            </article>
            <article>
              <span>Sensitive-data leaks</span>
              <strong>{percentage(report.sensitive_data_leak_rate)}</strong>
              <Text>{percentage(report.thresholds.sensitive_data_leak_rate)} maximum</Text>
            </article>
            <article>
              <span>Latency p95</span>
              <strong>{Math.round(report.latency_ms_p95)} ms</strong>
              <Text>p50 {Math.round(report.latency_ms_p50)} ms</Text>
            </article>
            <article className={report.passed ? "metric-pass" : "metric-fail"}>
              <span>Release decision</span>
              <strong>{report.passed ? "Pass" : "Hold"}</strong>
              <Text>{report.total} fixture cases checked</Text>
            </article>
          </section>

          <section className="evaluation-results">
            <h2>Case decisions</h2>
            <div className="result-grid">
              {report.items.map((item) => (
                <article key={item.case_id}>
                  <header>
                    <strong>{item.case_id}</strong>
                    <Badge
                      appearance="filled"
                      color={item.route_correct ? "success" : "danger"}
                    >
                      {item.route_correct ? "Correct" : "Mismatch"}
                    </Badge>
                  </header>
                  <dl>
                    <div>
                      <dt>Expected</dt>
                      <dd>{item.expected_route}</dd>
                    </div>
                    <div>
                      <dt>Actual</dt>
                      <dd>{item.actual_route}</dd>
                    </div>
                    <div>
                      <dt>Citation recall</dt>
                      <dd>{percentage(item.citation_recall)}</dd>
                    </div>
                    <div>
                      <dt>Risk recall</dt>
                      <dd>{percentage(item.risk_recall)}</dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>
          </section>
        </>
      )}
    </main>
  );
}

function IntegrationView({
  status,
  loading,
  onCheck,
}: {
  status: ZendeskStatus | null;
  loading: boolean;
  onCheck: () => void;
}) {
  return (
    <main className="page-panel">
      <div className="page-intro">
        <span className="section-label">Provider boundary</span>
        <h1>Zendesk integration</h1>
        <p>
          Confirm OAuth identity and the deliberately narrow provider-write boundary used for
          human-approved engineering escalation.
        </p>
        <Button
          appearance="primary"
          icon={<PlugConnected24Regular />}
          onClick={onCheck}
          disabled={loading}
        >
          {loading ? "Checking" : "Check Zendesk"}
        </Button>
      </div>

      <section className="boundary-panel">
        <div>
          <ShieldCheckmark24Regular />
          <div>
            <h2>Mutation boundary scoped</h2>
            <p>
              Routine access remains read-only. An authenticated approval can add one private note
              and one escalation tag; Zendesk Automation creates Jira work and returns its issue
              key.
            </p>
          </div>
        </div>
        {status ? (
          <dl>
            <div>
              <dt>State</dt>
              <dd>{status.state}</dd>
            </div>
            <div>
              <dt>Account</dt>
              <dd>{status.subdomain}.zendesk.com</dd>
            </div>
            <div>
              <dt>Role</dt>
              <dd>{status.role}</dd>
            </div>
            <div>
              <dt>Verified</dt>
              <dd>{status.verified ? "Yes" : "No"}</dd>
            </div>
            <div>
              <dt>Secret source</dt>
              <dd>{status.secret_source}</dd>
            </div>
          </dl>
        ) : (
          <p className="muted">
            Live status is not loaded automatically. Use the check only when read-only provider
            verification is intended.
          </p>
        )}
      </section>
    </main>
  );
}

export default function App() {
  const [themeMode, setThemeMode] = useState<ThemeMode>(usePreferredTheme);
  const [view, setView] = useState<View>("queue");
  const [cases, setCases] = useState<SupportCase[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<Record<string, Suggestion>>({});
  const [handoffs, setHandoffs] = useState<Record<string, EngineeringHandoff>>({});
  const [evaluation, setEvaluation] = useState<EvaluationReport | null>(null);
  const [zendesk, setZendesk] = useState<ZendeskStatus | null>(null);
  const [loadingCases, setLoadingCases] = useState(true);
  const [loadingAction, setLoadingAction] = useState<
    "suggestion" | "handoff" | "evaluation" | "zendesk" | null
  >(null);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(
    () => cases.find((supportCase) => supportCase.id === selectedId) ?? cases[0] ?? null,
    [cases, selectedId],
  );
  const suggestion = selected ? suggestions[selected.id] ?? null : null;
  const handoff = selected ? handoffs[selected.id] ?? null : null;

  async function loadCases() {
    setLoadingCases(true);
    setError(null);
    try {
      const items = await api.listCases();
      setCases(items);
      setSelectedId((current) => current ?? items[0]?.id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load cases");
    } finally {
      setLoadingCases(false);
    }
  }

  useEffect(() => {
    let active = true;
    api
      .listCases()
      .then((items) => {
        if (!active) return;
        setCases(items);
        setSelectedId(items[0]?.id ?? null);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "Unable to load cases");
      })
      .finally(() => {
        if (active) setLoadingCases(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (
      !selected ||
      !["zendesk_live_controlled", "zendesk_sidebar"].includes(selected.source)
    ) {
      return;
    }
    let active = true;
    api
      .engineeringHandoff(selected.id)
      .then((value) => {
        if (active && value) {
          setHandoffs((current) => ({ ...current, [selected.id]: value }));
        }
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(reason instanceof Error ? reason.message : "Unable to load handoff state");
        }
      });
    return () => {
      active = false;
    };
  }, [selected]);

  async function generateSuggestion() {
    if (!selected) return;
    setLoadingAction("suggestion");
    setError(null);
    try {
      const value = await api.createSuggestion(selected.id);
      setSuggestions((current) => ({ ...current, [selected.id]: value }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to generate suggestion");
    } finally {
      setLoadingAction(null);
    }
  }

  async function runEvaluation() {
    setLoadingAction("evaluation");
    setError(null);
    try {
      setEvaluation(await api.runEvaluation());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to run evaluation");
    } finally {
      setLoadingAction(null);
    }
  }

  async function approveHandoff() {
    if (!selected) return;
    setLoadingAction("handoff");
    setError(null);
    try {
      const value = await api.approveEngineeringHandoff(selected.id);
      setHandoffs((current) => ({ ...current, [selected.id]: value }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to approve Jira escalation");
    } finally {
      setLoadingAction(null);
    }
  }

  async function checkZendesk() {
    setLoadingAction("zendesk");
    setError(null);
    try {
      setZendesk(await api.zendeskStatus());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to verify Zendesk");
    } finally {
      setLoadingAction(null);
    }
  }

  function changeView(_: unknown, data: { value: TabValue }) {
    setView(data.value as View);
  }

  return (
    <FluentProvider theme={themeMode === "dark" ? darkTheme : lightTheme}>
      <div className="app-shell" data-theme={themeMode}>
        <header className="topbar">
          <div className="brand-block">
            <div className="brand-mark" aria-hidden="true">
              SM
            </div>
            <div>
              <strong>Support Copilot</strong>
              <span>Human-reviewed AI operations</span>
            </div>
          </div>
          <div className="header-actions">
            <Badge appearance="tint" color="informative">
              Controlled production
            </Badge>
            <Button
              appearance="subtle"
              icon={themeMode === "dark" ? <WeatherSunny24Regular /> : <WeatherMoon24Regular />}
              aria-label={`Use ${themeMode === "dark" ? "light" : "dark"} theme`}
              onClick={() => setThemeMode(themeMode === "dark" ? "light" : "dark")}
            />
          </div>
        </header>

        <nav className="primary-nav" aria-label="Copilot sections">
          <TabList className="primary-tabs" selectedValue={view} onTabSelect={changeView}>
            <Tab value="queue" icon={<DocumentSearch24Regular />}>
              Review queue
            </Tab>
            <Tab value="evaluation" icon={<Beaker24Regular />}>
              Evaluation
            </Tab>
            <Tab value="integrations" icon={<PlugConnected24Regular />}>
              Integrations
            </Tab>
          </TabList>
          <div className="safety-lock">
            <ShieldCheckmark24Regular />
            <span>Human-approved provider writes</span>
          </div>
        </nav>

        {error && (
          <div className="error-banner" role="alert">
            <span>{error}</span>
            <Button
              appearance="transparent"
              icon={<ArrowClockwise24Regular />}
              onClick={() => void loadCases()}
            >
              Retry
            </Button>
          </div>
        )}

        {view === "queue" &&
          (loadingCases ? (
            <LoadingQueue />
          ) : (
            <QueueView
              cases={cases}
              selected={selected}
              suggestion={suggestion}
              handoff={handoff}
              loadingSuggestion={loadingAction === "suggestion"}
              loadingHandoff={loadingAction === "handoff"}
              onSelect={(supportCase) => setSelectedId(supportCase.id)}
              onSuggest={() => void generateSuggestion()}
              onApproveHandoff={() => void approveHandoff()}
            />
          ))}
        {view === "evaluation" && (
          <EvaluationView
            report={evaluation}
            loading={loadingAction === "evaluation"}
            onRun={() => void runEvaluation()}
          />
        )}
        {view === "integrations" && (
          <IntegrationView
            status={zendesk}
            loading={loadingAction === "zendesk"}
            onCheck={() => void checkZendesk()}
          />
        )}
      </div>
    </FluentProvider>
  );
}
