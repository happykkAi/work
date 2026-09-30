import { request, requestBlob, requestStream } from "../request";

export type TrajectoryKind =
  | "user"
  | "assistant"
  | "tool"
  | "context"
  | "compacted"
  | "system"
  | "unknown";

export interface TrajectoryEvent {
  event_id: string;
  thread_id: string;
  agent_id: string;
  seq: number;
  ts: number;
  kind: TrajectoryKind;
  turn_id: string | null;
  request_seq: number | null;
  is_error: boolean;
  summary: string;
  payload: Record<string, unknown>;
}

export interface TrajectoryHistory {
  thread_id: string;
  events: TrajectoryEvent[];
  next_before_seq: number | null;
  has_more: boolean;
}

export interface TrajectoryMetrics {
  turns: number;
  steps: number;
  llm_duration_ms: number | null;
  tool_duration_ms: number | null;
  ttft_avg_ms: number | null;
  tok_per_s: number | null;
  cache_hit_ratio: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cache_read_tokens: number | null;
}

export type TrajectoryExportFormat = "jsonl" | "json";

function emitSseFrames(
  buffer: string,
  onFrame: (type: string, data: string) => void,
): string {
  let separator = /\r?\n\r?\n/.exec(buffer);
  while (separator) {
    const block = buffer.slice(0, separator.index);
    buffer = buffer.slice(separator.index + separator[0].length);
    let type = "message";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) type = line.slice(6).trimStart();
      if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (data.length > 0) onFrame(type, data.join("\n"));
    separator = /\r?\n\r?\n/.exec(buffer);
  }
  return buffer;
}

function trajectoryBase(agentId: string, threadId: string): string {
  return `/agents/${encodeURIComponent(agentId)}/threads/${encodeURIComponent(
    threadId,
  )}/trajectory`;
}

export const trajectoryApi = {
  history: (
    agentId: string,
    threadId: string,
    params: {
      limit?: number;
      beforeSeq?: number;
      kinds?: string[];
    } = {},
  ) => {
    const search = new URLSearchParams();
    if (params.limit != null) search.set("limit", String(params.limit));
    if (params.beforeSeq != null) {
      search.set("before_seq", String(params.beforeSeq));
    }
    if (params.kinds != null && params.kinds.length > 0) {
      search.set("kinds", params.kinds.join(","));
    }
    const qs = search.toString();
    return request<TrajectoryHistory>(
      `${trajectoryBase(agentId, threadId)}${qs ? `?${qs}` : ""}`,
    );
  },

  event: (agentId: string, threadId: string, eventId: string) =>
    request<TrajectoryEvent>(
      `${trajectoryBase(agentId, threadId)}/events/${encodeURIComponent(
        eventId,
      )}`,
    ),

  metrics: (agentId: string, threadId: string) =>
    request<TrajectoryMetrics>(`${trajectoryBase(agentId, threadId)}/metrics`),

  export: (
    agentId: string,
    threadId: string,
    format: TrajectoryExportFormat = "jsonl",
  ) =>
    requestBlob(
      `${trajectoryBase(agentId, threadId)}/export?format=${encodeURIComponent(
        format,
      )}`,
    ),

  stream: (
    agentId: string,
    threadId: string,
    afterSeq: number | undefined,
    onFrame: (type: string, data: string) => void,
    onDisconnect: () => void,
  ) => {
    const search = new URLSearchParams();
    if (afterSeq != null) search.set("after_seq", String(afterSeq));
    const qs = search.toString();
    const controller = new AbortController();
    void (async () => {
      try {
        const { body } = await requestStream(
          `${trajectoryBase(agentId, threadId)}/stream${qs ? `?${qs}` : ""}`,
          {
            headers: { Accept: "text/event-stream" },
            signal: controller.signal,
          },
        );
        const reader = body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer = emitSseFrames(
            buffer + decoder.decode(value, { stream: true }),
            onFrame,
          );
        }
        emitSseFrames(buffer + decoder.decode(), onFrame);
      } catch {
        /* Reconnect below unless close() deliberately aborted the request. */
      }
      if (!controller.signal.aborted) onDisconnect();
    })();
    return { close: () => controller.abort() };
  },
};
