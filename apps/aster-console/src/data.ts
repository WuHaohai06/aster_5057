import type { ReplaySession, Snapshot } from "./types";

export type SnapshotSource = "live" | "static";

const configuredBase = (import.meta.env.VITE_ASTER_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";

function apiUrl(path: string) {
  return `${configuredBase}${path}`;
}

async function fetchJson(url: string): Promise<Snapshot> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`Snapshot request failed: ${response.status}`);
  return response.json() as Promise<Snapshot>;
}

export async function loadSnapshot(): Promise<{ snapshot: Snapshot; source: SnapshotSource }> {
  try {
    return { snapshot: await fetchJson(apiUrl("/api/snapshot")), source: "live" };
  } catch (liveError) {
    try {
      const staticUrl = new URL("data/snapshot.json", document.baseURI).toString();
      return { snapshot: await fetchJson(staticUrl), source: "static" };
    } catch {
      throw liveError;
    }
  }
}

export function subscribeToSnapshotEvents(
  onSnapshot: () => void,
  onOpen: () => void,
  onError: () => void,
) {
  if (!("EventSource" in window)) return () => undefined;
  const source = new EventSource(apiUrl("/api/events"));
  source.addEventListener("snapshot", onSnapshot);
  source.onopen = onOpen;
  source.onerror = onError;
  return () => source.close();
}

async function replayRequest(path: string, body?: unknown): Promise<ReplaySession> {
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail ?? `Replay request failed: ${response.status}`);
  return payload as ReplaySession;
}

export const createReplaySession = (automatic = false, startNode?: string) =>
  replayRequest(
    `/api/replay/sessions?automatic=${automatic ? "true" : "false"}${
      startNode ? `&start_node=${encodeURIComponent(startNode)}` : ""
    }`,
  );
export const rethinkReplayNode = (sessionId: string, nodeId: string, instruction: string) =>
  replayRequest(`/api/replay/${sessionId}/nodes/${nodeId}/rethink`, { instruction });
export const acceptReplayNode = (sessionId: string, nodeId: string) =>
  replayRequest(`/api/replay/${sessionId}/nodes/${nodeId}/accept`);
export const runReplayNode = (sessionId: string, nodeId: string) =>
  replayRequest(`/api/replay/${sessionId}/nodes/${nodeId}/run`);
export const setReplayPlayback = (sessionId: string, nodeId: string, state: "play" | "pause") =>
  replayRequest(`/api/replay/${sessionId}/nodes/${nodeId}/${state}`);

export function subscribeToReplayEvents(
  sessionId: string,
  onReplay: (session: ReplaySession) => void,
  onError: () => void,
) {
  const source = new EventSource(apiUrl(`/api/replay/${sessionId}/events`));
  source.addEventListener("replay", (event) => {
    onReplay(JSON.parse((event as MessageEvent).data) as ReplaySession);
  });
  source.onerror = onError;
  return () => source.close();
}
