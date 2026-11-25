import type { Snapshot } from "./types";

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
