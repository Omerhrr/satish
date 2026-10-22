/** Turn internal status/event codes into words people understand. */
const LABELS: Record<string, string> = {
  purchase: "Bought TK",
  purchase_credit: "Bought TK",
  reserve: "Held for task",
  reservation: "Held for task",
  release: "Returned",
  charge: "Spent",
  refund: "Refunded",
  grant: "Bonus",
  planned: "Ready",
  active: "On",
  paused: "Paused",
  revoked: "Disconnected",
  connected: "Connected",
  pending: "Waiting",
  settled: "Paid",
  expired: "Expired",
  failed: "Failed",
  running: "Working",
  completed: "Done",
  cancelled: "Cancelled",
  canceled: "Cancelled",
  awaiting_approval: "Needs your OK",
  unknown_outcome: "Not sure if sent",
  sent: "Sent",
  refused: "Not delivered",
  skipped: "Not sent",
  unknown: "Unknown",
  manual: "You ran it",
  schedule: "On schedule",
  scheduled: "On schedule",
};

export function human(code?: string | null): string {
  if (!code) return "";
  const key = code.toLowerCase();
  if (LABELS[key]) return LABELS[key];
  const words = key.replace(/[._:]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
