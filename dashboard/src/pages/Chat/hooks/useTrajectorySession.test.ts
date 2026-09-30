import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TrajectoryEvent } from "../../../api/modules/trajectory";
import { useTrajectorySession } from "./useTrajectorySession";

const historyMock = vi.fn();
const metricsMock = vi.fn();
const streamMock = vi.fn();

vi.mock("../../../api/modules/trajectory", () => ({
  trajectoryApi: {
    history: (...args: unknown[]) => historyMock(...args),
    metrics: (...args: unknown[]) => metricsMock(...args),
    stream: (...args: unknown[]) => streamMock(...args),
  },
}));

class MockTrajectoryStream {
  static instances: MockTrajectoryStream[] = [];
  close = vi.fn();
  private onFrame: (type: string, data: string) => void;
  private onDisconnect: () => void;

  constructor(
    onFrame: (type: string, data: string) => void,
    onDisconnect: () => void,
  ) {
    this.onFrame = onFrame;
    this.onDisconnect = onDisconnect;
    MockTrajectoryStream.instances.push(this);
  }

  emit(type: string, data: unknown): void {
    this.onFrame(type, JSON.stringify(data));
  }

  disconnect(): void {
    this.onDisconnect();
  }
}

function event(
  overrides: Partial<TrajectoryEvent> &
    Pick<TrajectoryEvent, "event_id" | "kind">,
): TrajectoryEvent {
  return {
    thread_id: "T1",
    agent_id: "A1",
    seq: 1,
    ts: 1,
    turn_id: null,
    request_seq: null,
    is_error: false,
    summary: "",
    payload: {},
    ...overrides,
  };
}

const toolEvent = event({
  event_id: "tool-1",
  kind: "tool",
  seq: 1,
  payload: { name: "read_file" },
});

const assistantEvent = event({
  event_id: "asst-1",
  kind: "assistant",
  seq: 2,
  request_seq: 1,
  summary: "ok",
});

describe("useTrajectorySession", () => {
  beforeEach(() => {
    MockTrajectoryStream.instances = [];
    historyMock.mockReset();
    metricsMock.mockReset();
    streamMock.mockReset();
    streamMock.mockImplementation(
      (
        _agentId: string,
        _threadId: string,
        _afterSeq: number | undefined,
        onFrame: (type: string, data: string) => void,
        onDisconnect: () => void,
      ) => new MockTrajectoryStream(onFrame, onDisconnect),
    );
    historyMock.mockResolvedValue({
      thread_id: "T1",
      events: [toolEvent],
      next_before_seq: null,
      has_more: false,
    });
    metricsMock.mockResolvedValue({
      turns: 1,
      steps: 1,
      llm_duration_ms: null,
      tool_duration_ms: null,
      ttft_avg_ms: null,
      tok_per_s: null,
      cache_hit_ratio: null,
      input_tokens: null,
      output_tokens: null,
      cache_read_tokens: null,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("loads history and appends live SSE events while visible", async () => {
    const { result } = renderHook(() =>
      useTrajectorySession({
        agentId: "A1",
        threadId: "T1",
        visible: true,
      }),
    );

    await waitFor(() => expect(result.current.events).toHaveLength(1));
    expect(historyMock).toHaveBeenCalledWith("A1", "T1");
    expect(MockTrajectoryStream.instances).toHaveLength(1);
    expect(streamMock).toHaveBeenCalledWith(
      "A1",
      "T1",
      1,
      expect.any(Function),
      expect.any(Function),
    );

    act(() => {
      MockTrajectoryStream.instances[0].emit("event", assistantEvent);
    });

    expect(result.current.events.map((row) => row.event_id)).toEqual([
      "tool-1",
      "asst-1",
    ]);
  });

  it("upserts a live event with the same event_id", async () => {
    const { result } = renderHook(() =>
      useTrajectorySession({
        agentId: "A1",
        threadId: "T1",
        visible: true,
      }),
    );

    await waitFor(() => expect(result.current.events).toHaveLength(1));

    act(() => {
      MockTrajectoryStream.instances[0].emit("event", {
        ...assistantEvent,
        event_id: "tool-1",
        kind: "assistant",
        summary: "updated",
      });
    });

    expect(result.current.events).toHaveLength(1);
    expect(result.current.events[0]).toMatchObject({
      event_id: "tool-1",
      kind: "assistant",
      summary: "updated",
    });
  });

  it("applies live SSE metrics", async () => {
    const { result } = renderHook(() =>
      useTrajectorySession({
        agentId: "A1",
        threadId: "T1",
        visible: true,
      }),
    );

    await waitFor(() => expect(MockTrajectoryStream.instances).toHaveLength(1));
    await waitFor(() =>
      expect(result.current.metrics).toMatchObject({ turns: 1, steps: 1 }),
    );

    act(() => {
      MockTrajectoryStream.instances[0].emit("metrics", {
        turns: 3,
        steps: 8,
        llm_duration_ms: 120,
        tool_duration_ms: null,
        ttft_avg_ms: null,
        tok_per_s: null,
        cache_hit_ratio: null,
        input_tokens: 40,
        output_tokens: null,
        cache_read_tokens: null,
      });
    });

    expect(result.current.metrics).toMatchObject({
      turns: 3,
      steps: 8,
      llm_duration_ms: 120,
      input_tokens: 40,
    });
  });

  it("does not fetch or subscribe while the panel is hidden", async () => {
    renderHook(() =>
      useTrajectorySession({
        agentId: "A1",
        threadId: "T1",
        visible: false,
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(historyMock).not.toHaveBeenCalled();
    expect(MockTrajectoryStream.instances).toHaveLength(0);
  });

  it("clears events when the thread changes before the next page loads", async () => {
    const { result, rerender } = renderHook(
      ({ threadId }: { threadId: string }) =>
        useTrajectorySession({
          agentId: "A1",
          threadId,
          visible: true,
        }),
      { initialProps: { threadId: "T1" } },
    );

    await waitFor(() => expect(result.current.events).toHaveLength(1));

    let resolveNext: ((value: unknown) => void) | undefined;
    historyMock.mockReturnValue(
      new Promise((resolve) => {
        resolveNext = resolve;
      }),
    );

    rerender({ threadId: "T2" });

    await waitFor(() => expect(result.current.events).toEqual([]));
    expect(resolveNext).toBeTypeOf("function");
  });

  it("loadEarlier prepends older events and fetches with beforeSeq", async () => {
    const olderEvent = event({
      event_id: "tool-0",
      kind: "tool",
      seq: 0,
    });

    historyMock
      .mockResolvedValueOnce({
        thread_id: "T1",
        events: [toolEvent],
        next_before_seq: 5,
        has_more: true,
      })
      .mockResolvedValueOnce({
        thread_id: "T1",
        events: [olderEvent],
        next_before_seq: null,
        has_more: false,
      });

    const { result } = renderHook(() =>
      useTrajectorySession({
        agentId: "A1",
        threadId: "T1",
        visible: true,
      }),
    );

    await waitFor(() => expect(result.current.events).toHaveLength(1));
    expect(result.current.hasMore).toBe(true);

    await act(async () => {
      await result.current.loadEarlier();
    });

    expect(historyMock).toHaveBeenLastCalledWith("A1", "T1", { beforeSeq: 5 });
    expect(result.current.events.map((row) => row.event_id)).toEqual([
      "tool-0",
      "tool-1",
    ]);
    expect(result.current.hasMore).toBe(false);
  });

  it("loadEarlier ignores stale responses after thread change", async () => {
    const staleOlderEvent = event({
      event_id: "stale-old",
      kind: "tool",
      seq: 0,
    });
    const t2Event = event({
      event_id: "tool-t2",
      kind: "tool",
      seq: 1,
      thread_id: "T2",
    });

    let resolveEarlier: ((value: unknown) => void) | undefined;

    historyMock
      .mockResolvedValueOnce({
        thread_id: "T1",
        events: [toolEvent],
        next_before_seq: 5,
        has_more: true,
      })
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveEarlier = resolve;
          }),
      )
      .mockResolvedValueOnce({
        thread_id: "T2",
        events: [t2Event],
        next_before_seq: null,
        has_more: false,
      });

    const { result, rerender } = renderHook(
      ({ threadId }: { threadId: string }) =>
        useTrajectorySession({
          agentId: "A1",
          threadId,
          visible: true,
        }),
      { initialProps: { threadId: "T1" } },
    );

    await waitFor(() => expect(result.current.events).toHaveLength(1));

    let loadEarlierPromise: Promise<void> | undefined;
    act(() => {
      loadEarlierPromise = result.current.loadEarlier();
    });

    rerender({ threadId: "T2" });

    await waitFor(() =>
      expect(result.current.events.map((row) => row.event_id)).toEqual([
        "tool-t2",
      ]),
    );

    await act(async () => {
      resolveEarlier?.({
        thread_id: "T1",
        events: [staleOlderEvent],
        next_before_seq: null,
        has_more: false,
      });
      await loadEarlierPromise;
    });

    expect(result.current.events.map((row) => row.event_id)).toEqual([
      "tool-t2",
    ]);
  });

  it("closes the authenticated stream when the panel is hidden", async () => {
    const { rerender } = renderHook(
      ({ visible }: { visible: boolean }) =>
        useTrajectorySession({
          agentId: "A1",
          threadId: "T1",
          visible,
        }),
      { initialProps: { visible: true } },
    );

    await waitFor(() => expect(MockTrajectoryStream.instances).toHaveLength(1));

    rerender({ visible: false });

    expect(MockTrajectoryStream.instances[0].close).toHaveBeenCalled();
  });

  it("reconnects the authenticated stream after a disconnect using the last seq", async () => {
    renderHook(() =>
      useTrajectorySession({
        agentId: "A1",
        threadId: "T1",
        visible: true,
      }),
    );

    await waitFor(() => expect(MockTrajectoryStream.instances).toHaveLength(1));

    act(() => {
      MockTrajectoryStream.instances[0].disconnect();
    });

    await waitFor(() =>
      expect(MockTrajectoryStream.instances.length).toBeGreaterThanOrEqual(2),
    );
    expect(streamMock).toHaveBeenLastCalledWith(
      "A1",
      "T1",
      1,
      expect.any(Function),
      expect.any(Function),
    );
  });

  it("loadEarlier keeps current events when the older page fails", async () => {
    historyMock.mockImplementation(
      (
        _agentId: string,
        _threadId: string,
        params?: { beforeSeq?: number },
      ) => {
        if (params?.beforeSeq != null) {
          return Promise.reject(new Error("network"));
        }
        return Promise.resolve({
          thread_id: "T1",
          events: [toolEvent],
          next_before_seq: 5,
          has_more: true,
        });
      },
    );

    const { result } = renderHook(() =>
      useTrajectorySession({
        agentId: "A1",
        threadId: "T1",
        visible: true,
      }),
    );

    await waitFor(() => expect(result.current.hasMore).toBe(true));

    await act(async () => {
      await result.current.loadEarlier();
    });

    expect(result.current.events.map((row) => row.event_id)).toEqual([
      "tool-1",
    ]);
    expect(result.current.hasMore).toBe(true);
  });
});
