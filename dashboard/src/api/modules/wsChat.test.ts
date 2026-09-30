import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../request", () => ({
  getAuthToken: () => "header.payload.signature",
}));

import {
  buildDashboardChatWsUrl,
  createDashboardChatWebSocket,
} from "./wsChat";

describe("dashboard chat WebSocket authentication", () => {
  const RealWebSocket = globalThis.WebSocket;

  afterEach(() => {
    globalThis.WebSocket = RealWebSocket;
  });

  it("keeps the login token out of the URL and offers it as a subprotocol", () => {
    const calls: unknown[][] = [];
    globalThis.WebSocket = class {
      constructor(...args: unknown[]) {
        calls.push(args);
      }
    } as unknown as typeof WebSocket;

    expect(buildDashboardChatWsUrl("agent-b")).not.toContain("token=");
    createDashboardChatWebSocket("agent-b");

    expect(calls[0]?.[0]).not.toContain("token=");
    expect(calls[0]?.[1]).toEqual([
      "octop.chat",
      "octop.auth.header.payload.signature",
    ]);
  });
});
