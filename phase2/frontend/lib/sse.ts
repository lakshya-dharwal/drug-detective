/**
 * Thin wrapper around the browser EventSource for our named SSE events.
 * The backend emits `progress`, `complete`, and `failed` events (plus keep-alive
 * comments). This helper wires typed callbacks and centralizes teardown.
 *
 * EventSource is used (not fetch) because our stream is an unauthenticated GET
 * and native EventSource gives automatic reconnection semantics we then bound.
 */
import { streamUrl, type PipelineResult } from "./api";

export interface ProgressPayload {
  stage: string;
  status: "started" | "done";
  message: string;
  counts: Record<string, number | string | null>;
}

export interface SseHandlers {
  onProgress: (p: ProgressPayload) => void;
  onComplete: (result: PipelineResult) => void;
  onFailed: (error: string) => void;
  onError: () => void; // transport-level error (disconnect); caller may fall back to polling
}

export function openSearchStream(searchId: string, handlers: SseHandlers): () => void {
  const es = new EventSource(streamUrl(searchId));
  let closed = false;

  const close = () => {
    if (!closed) {
      closed = true;
      es.close();
    }
  };

  es.addEventListener("progress", (e) => {
    try {
      handlers.onProgress(JSON.parse((e as MessageEvent).data));
    } catch {
      /* ignore malformed frame */
    }
  });

  es.addEventListener("complete", (e) => {
    try {
      const data = JSON.parse((e as MessageEvent).data);
      handlers.onComplete(data.result as PipelineResult);
    } catch {
      handlers.onFailed("Malformed completion payload");
    }
    close();
  });

  es.addEventListener("failed", (e) => {
    try {
      const data = JSON.parse((e as MessageEvent).data);
      handlers.onFailed(data.error ?? "Pipeline failed");
    } catch {
      handlers.onFailed("Pipeline failed");
    }
    close();
  });

  es.onerror = () => {
    // Native EventSource retries automatically; we treat a persistent error as a
    // disconnect and let the caller poll /result instead. Close to stop retries.
    if (!closed) {
      handlers.onError();
      close();
    }
  };

  return close;
}
