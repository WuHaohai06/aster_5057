import type { Snapshot } from "./types";

export async function loadSnapshot(): Promise<Snapshot> {
  const response = await fetch("./data/snapshot.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Snapshot request failed: ${response.status}`);
  }
  return response.json() as Promise<Snapshot>;
}
