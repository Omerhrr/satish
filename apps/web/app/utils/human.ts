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


/** "22 Oct, 09:00" (this year) or "22 Oct 2025, 09:00": day-first, no seconds. */
export function niceDate(unixSecs: number): string {
  const d = new Date(unixSecs * 1000);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  const day = d.toLocaleDateString("en-GB", { day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }) });
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  return `${day}, ${time}`;
}
