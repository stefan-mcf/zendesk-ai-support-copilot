import { describe, expect, it } from "vitest";

import { buildRequest } from "./app";

describe("Zendesk proxy request boundary", () => {
  it("uses the secure header placeholder and the fixed Copilot domain", () => {
    const request = buildRequest("/sidebar/tickets/41", "GET");

    expect(request).toEqual({
      url: "https://support-copilot.example.com/v1/sidebar/tickets/41",
      type: "GET",
      contentType: "application/json",
      headers: {
        "X-Copilot-App-Token": "{{setting.api_token}}",
      },
      secure: true,
      timeout: 30_000,
    });
  });

  it("serializes only the explicit approval payload", () => {
    const request = buildRequest("/sidebar/tickets/41/handoffs/engineering", "POST", {
      decision: "approve",
      actor_id: "agent-7",
    });

    expect(JSON.parse(request.data ?? "{}")).toEqual({
      decision: "approve",
      actor_id: "agent-7",
    });
    expect(request.headers).not.toHaveProperty("Authorization");
  });
});
