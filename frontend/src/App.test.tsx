import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const cases = [
  {
    id: "S1",
    subject: "Password reset still failing",
    body: "I reset my password two minutes ago and still see error E401.",
    source: "fixture",
    source_ref: "dataset:S1",
    created_at: "2026-07-28T00:00:00Z",
  },
];

const suggestion = {
  case_id: "S1",
  route: "draft",
  draft: "Follow the password reset guidance. [A1]",
  confidence: 0.82,
  citations: [
    {
      document_id: "A1",
      chunk_id: "A1:C1",
      title: "Resetting account credentials",
      score: 0.82,
      excerpt: "After a password reset, wait up to five minutes.",
    },
  ],
  risks: [],
  review_required: true,
  policy_version: "support-safety-v1",
  generated_at: "2026-07-28T00:00:00Z",
};

describe("App", () => {
  beforeEach(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: string) => {
        if (input.endsWith("/v1/cases")) {
          return Promise.resolve(
            new Response(JSON.stringify(cases), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        if (input.endsWith("/v1/cases/S1/suggestions")) {
          return Promise.resolve(
            new Response(JSON.stringify(suggestion), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        return Promise.reject(new Error(`Unexpected request: ${input}`));
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads cases and generates a review-only suggestion", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Password reset still failing" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Human-approved provider writes")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Generate suggestion" }));

    expect(await screen.findByText("Draft ready")).toBeInTheDocument();
    expect(screen.getByLabelText("Private draft")).toHaveValue(
      "Follow the password reset guidance. [A1]",
    );
    expect(screen.queryByRole("button", { name: /send/i })).not.toBeInTheDocument();
  });

  it("shows a retryable API error", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("Backend unavailable"));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Backend unavailable");
    });
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("requires an explicit approval before dispatching a Zendesk-backed escalation", async () => {
    const user = userEvent.setup();
    const zendeskCase = {
      ...cases[0],
      id: "ZD-41",
      subject: "Widespread service incident",
      body: "Every team member reports an outage.",
      source: "zendesk_sidebar",
      source_ref: "example:ticket:41",
    };
    const escalation = {
      ...suggestion,
      case_id: "ZD-41",
      route: "escalate",
      draft: null,
      risks: [
        {
          code: "incident",
          severity: "high",
          message: "Possible multi-user incident requires incident routing.",
          blocks_draft: false,
        },
      ],
    };
    vi.mocked(fetch).mockImplementation(
      (input: string | URL | Request, init?: RequestInit) => {
        const url =
          typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        if (url.endsWith("/v1/cases")) {
        return Promise.resolve(
          new Response(JSON.stringify([zendeskCase]), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
        if (url.endsWith("/v1/cases/ZD-41/handoffs/engineering") && !init?.method) {
        return Promise.resolve(new Response(null, { status: 404 }));
      }
        if (url.endsWith("/v1/cases/ZD-41/suggestions")) {
        return Promise.resolve(
          new Response(JSON.stringify(escalation), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (
        url.endsWith("/v1/cases/ZD-41/handoffs/engineering") &&
        init?.method === "POST"
      ) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              id: "handoff_1",
              case_id: "ZD-41",
              provider_ticket_id: "41",
              status: "dispatched",
              approved_by: "agent-7",
              approval_source: "copilot_web",
              zendesk_receipt_state: "completed",
              jira_issue_key: null,
              jira_issue_url: null,
              failure_code: null,
              created_at: "2026-07-29T00:00:00Z",
              updated_at: "2026-07-29T00:00:01Z",
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      }
        return Promise.reject(new Error(`Unexpected request: ${url}`));
      },
    );

    render(<App />);
    await screen.findByRole("heading", { name: "Widespread service incident" });
    await user.click(screen.getByRole("button", { name: "Generate suggestion" }));
    expect(await screen.findByText("Zendesk → Jira engineering handoff")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Approve Jira escalation" }));

    expect(
      await screen.findByText(
        "Zendesk accepted the private note and escalation tag. Waiting for Jira readback.",
      ),
    ).toBeInTheDocument();
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/v1/cases/ZD-41/handoffs/engineering",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
