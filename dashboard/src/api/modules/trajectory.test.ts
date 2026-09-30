import { expect, it, vi } from "vitest";

const { requestStream } = vi.hoisted(() => ({ requestStream: vi.fn() }));
vi.mock("../request", () => ({
  request: vi.fn(),
  requestBlob: vi.fn(),
  requestStream,
}));

import { trajectoryApi } from "./trajectory";

it("streams trajectory SSE with Authorization handled by requestStream and no URL token", async () => {
  const encoder = new TextEncoder();
  requestStream.mockResolvedValue({
    contentType: "text/event-stream",
    body: new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: event\ndata: {"seq":1'));
        controller.enqueue(
          encoder.encode('}\n\nevent: metrics\ndata: {"turns":1}\n\n'),
        );
        controller.close();
      },
    }),
  });
  const frames: Array<[string, string]> = [];
  const disconnected = vi.fn();

  trajectoryApi.stream(
    "agent-a",
    "thread-a",
    7,
    (type, data) => frames.push([type, data]),
    disconnected,
  );

  await vi.waitFor(() => expect(disconnected).toHaveBeenCalledOnce());
  expect(requestStream).toHaveBeenCalledWith(
    "/agents/agent-a/threads/thread-a/trajectory/stream?after_seq=7",
    expect.objectContaining({
      headers: { Accept: "text/event-stream" },
      signal: expect.any(AbortSignal),
    }),
  );
  expect(requestStream.mock.calls[0][0]).not.toContain("token");
  expect(frames).toEqual([
    ["event", '{"seq":1}'],
    ["metrics", '{"turns":1}'],
  ]);
});
