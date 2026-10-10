// Limit burst-driven full fleet snapshots without delaying the first update.
// Per-subscriber only: no shared state, no DB access, and normal reconciliation
// polling remains intact after a lost notification or backend restart.
export const MIN_REALTIME_SNAPSHOT_SPACING_MS = 350;

export function realtimeSnapshotDelayMs(nowMs, lastSnapshotAtMs) {
  if (!Number.isFinite(nowMs)) return 0;
  if (!Number.isFinite(lastSnapshotAtMs)) return 0;
  return Math.max(0, MIN_REALTIME_SNAPSHOT_SPACING_MS - (nowMs - lastSnapshotAtMs));
}
