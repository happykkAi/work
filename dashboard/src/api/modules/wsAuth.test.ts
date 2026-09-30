import { beforeEach, describe, expect, it, vi } from "vitest";

const { getAuthToken } = vi.hoisted(() => ({ getAuthToken: vi.fn() }));
vi.mock("../request", () => ({ getAuthToken }));

import { createAuthenticatedWebSocket } from "./wsAuth";

describe("createAuthenticatedWebSocket", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    getAuthToken.mockReturnValue("header.payload.signature");
  });

  it("keeps the login token out of the URL and offers it as a subprotocol", () => {
    const socket = vi.fn();
    vi.stubGlobal("WebSocket", socket);

    createAuthenticatedWebSocket("wss://example.test/stream?width=1");

    expect(socket).toHaveBeenCalledWith("wss://example.test/stream?width=1", [
      "octop.chat",
      "octop.auth.header.payload.signature",
    ]);
    expect(socket.mock.calls[0][0]).not.toContain("token");
  });
});
