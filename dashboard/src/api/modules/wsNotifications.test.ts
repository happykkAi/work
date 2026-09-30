import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../request", () => ({
  getAuthToken: () => "header.payload.signature",
}));
vi.mock("../config", () => ({
  getWsUrl: (path: string) => `ws://dashboard.test/api${path}`,
}));

import {
  buildDashboardNotifyWsUrl,
  createDashboardNotifyWebSocket,
} from "./wsNotifications";

describe("dashboard notification WebSocket authentication", () => {
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

    expect(buildDashboardNotifyWsUrl()).not.toContain("token=");
    createDashboardNotifyWebSocket();

    expect(calls[0]?.[0]).not.toContain("token=");
    expect(calls[0]?.[1]).toEqual([
      "octop.chat",
      "octop.auth.header.payload.signature",
    ]);
  });
});
