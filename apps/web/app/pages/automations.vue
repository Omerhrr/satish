<template>
  <div>
    <h1 class="page-title">⏱ Automations</h1>
    <p class="page-sub">
      Repeat a task on a schedule. Each run takes TK only for what it uses;
      if something fails it pauses instead of retrying, and emails always wait
      for your approval.
    </p>

    <section class="card">
      <h2>New automation</h2>
      <div class="form-grid">
        <label>What should it do?<input v-model="form.objective" placeholder="Monitor supplier prices daily" /></label>
      </div>
      <div class="sched">
        <div class="seg">
          <button v-for="k in kinds" :key="k.key" type="button" :class="{ on: sched.kind === k.key }" @click="sched.kind = k.key">{{ k.label }}</button>
        </div>
        <div v-if="sched.kind === 'every'" class="sched-row">
          Every <input v-model="sched.n" class="num" inputmode="numeric" />
          <select v-model="sched.unit"><option value="m">minutes</option><option value="h">hours</option><option value="d">days</option></select>
        </div>
        <div v-if="sched.kind === 'weekly'" class="days">
          <button v-for="d in weekdays" :key="d" type="button" :class="{ on: sched.days.includes(d) }" @click="toggleDay(d)">{{ d }}</button>
        </div>
        <div v-if="sched.kind === 'monthly'" class="sched-row">
          On day <input v-model="sched.dom" class="num" inputmode="numeric" /> of each month
        </div>
        <div v-if="['daily', 'weekly', 'monthly'].includes(sched.kind)" class="sched-row times">
          At
          <span v-for="(t, i) in sched.times" :key="i" class="time">
            <input v-model="sched.times[i]" type="time" />
            <button v-if="sched.times.length > 1" type="button" class="x" aria-label="Remove time" @click="sched.times.splice(i, 1)">×</button>
          </span>
          <button v-if="sched.times.length < 12" type="button" class="btn ghost small-btn" @click="sched.times.push('18:00')">+ time</button>
        </div>
        <div v-if="sched.kind === 'custom'" class="sched-row">
          <input v-model="sched.custom" placeholder="weekly mon,fri 09:00,17:00" style="flex: 1" />
        </div>
        <p class="small dim">{{ describe(scheduleExpr) }}<span v-if="sched.kind !== 'every'"> · your time ({{ tz }})</span></p>
      </div>
      <button class="btn" :disabled="creating || !form.objective" @click="create">
        <span v-if="creating" class="spinner" /> Create automation
      </button>
      <span v-if="note" class="small" style="margin-left: 10px">{{ note }}</span>
      <p v-if="createError" class="small" style="color: #f59e0b">{{ createError }}</p>
    </section>

    <section class="card">
      <h2>Your automations</h2>
      <p v-if="loadError" class="small" style="color: #f59e0b">{{ loadError }}</p>
      <p v-else-if="!jobs.length" class="small dim">No automations yet.</p>
      <div v-for="j in jobs" :key="j.id" class="job">
        <div class="job-head">
          <div>
            <div class="small"><b>{{ j.objective }}</b></div>
            <div class="small dim">
              {{ describe(j.schedule) }} · {{ human(j.status) }}
              <span v-if="j.auto_paused_reason"> (paused: {{ j.auto_paused_reason }})</span>
              · next: {{ fmt(j.next_run_at) }}
              · {{ j.total_spent_xp.toLocaleString() }} TK used
              · {{ j.run_count }} runs
            </div>
            <div v-if="j.last_run_status" class="small dim">
              last run: <span class="badge" :data-status="j.last_run_status">{{ j.last_run_status }}</span>
            </div>
          </div>
          <div class="job-actions">
            <button v-if="j.status === 'active'" class="btn ghost" @click="pause(j.id)">Pause</button>
            <button v-if="j.status === 'paused'" class="btn ghost" @click="resume(j.id)">Resume</button>
            <button v-if="j.status !== 'cancelled'" class="btn ghost" @click="run(j.id)">Run now</button>
            <button v-if="j.status !== 'cancelled'" class="btn ghost sensitive-action" @click="cancel(j.id)">Cancel</button>
            <button class="btn ghost" @click="showRuns(j.id)">{{ openRuns === j.id ? "Hide runs" : "Runs" }}</button>
          </div>
        </div>
        <div v-if="openRuns === j.id" class="runs">
          <p v-if="!runs.length" class="small dim">No runs recorded yet.</p>
          <div v-for="r in runs" :key="r.id" class="small run-row">
            <span>Run {{ r.run_number }} · {{ human(r.trigger) }} ·
              <span class="badge" :data-status="r.status">{{ r.status }}</span>
              · {{ r.xp_charged }} TK
            </span>
            <span class="dim"> {{ fmt(r.started_at) }}<span v-if="r.error"> · {{ r.error }}</span></span>
          </div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Notifications</h2>
      <p class="small dim">
        Updates from your automations, like finished runs or a low balance.
        Each one is also sent to you on Telegram.
      </p>
      <p v-if="!notifications.length" class="small dim">Nothing yet.</p>
      <div v-for="n in notifications" :key="n.id" class="row-list">
        <div>
          <div class="small">
            <b>{{ n.kind }}</b>
            <span v-if="!n.read_at" class="badge">unread</span>
            <span v-if="n.relay_status" class="badge">Telegram: {{ human(n.relay_status) }}</span>
          </div>
          <div class="small dim">{{ fmt(n.created_at) }} · {{ JSON.stringify(n.payload) }}</div>
        </div>
        <button v-if="!n.read_at" class="btn ghost" @click="markRead(n.id)">Mark read</button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import type { AutomationRunOut, JobOut, NotificationOut } from "@xp/shared-types";

const api = useXpApi();

const jobs = ref<JobOut[]>([]);
const notifications = ref<NotificationOut[]>([]);
const runs = ref<AutomationRunOut[]>([]);
const openRuns = ref<string | null>(null);
const loadError = ref("");
const createError = ref("");
const note = ref("");
const creating = ref(false);

const form = reactive({
  objective: "",
});

const tz = (() => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
})();
const kinds = [
  { key: "every", label: "Repeat" },
  { key: "daily", label: "Daily" },
  { key: "weekly", label: "Weekly" },
  { key: "monthly", label: "Monthly" },
  { key: "custom", label: "Custom" },
];
const weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const sched = reactive({
  kind: "daily",
  n: "30",
  unit: "m",
  days: ["mon", "fri"] as string[],
  dom: "1",
  times: ["09:00"] as string[],
  custom: "",
});
function toggleDay(d: string) {
  const i = sched.days.indexOf(d);
  if (i >= 0) {
    if (sched.days.length > 1) sched.days.splice(i, 1);
  } else sched.days.push(d);
}
const scheduleExpr = computed(() => {
  const times = [...new Set(sched.times.filter(Boolean))].sort().join(",");
  const zone = tz && tz !== "UTC" ? ` tz ${tz}` : "";
  switch (sched.kind) {
    case "every":
      return `every ${Math.max(1, Number(sched.n) || 1)}${sched.unit}`;
    case "daily":
      return `daily ${times}${zone}`;
    case "weekly":
      return `weekly ${weekdays.filter((d) => sched.days.includes(d)).join(",")} ${times}${zone}`;
    case "monthly":
      return `monthly ${Math.min(28, Math.max(1, Number(sched.dom) || 1))} ${times}${zone}`;
    default:
      return sched.custom.trim();
  }
});
function describe(expr: string): string {
  const e = (expr || "").trim();
  const zone = / tz (\S+)$/.exec(e);
  const body = zone ? e.slice(0, zone.index) : e;
  const at = (t: string) => t.split(",").join(", ");
  let m: RegExpExecArray | null;
  if (body === "hourly") return "Every hour";
  if ((m = /^every (\d+)([smhd])$/.exec(body))) {
    const n = Number(m[1]);
    const unit = { s: "second", m: "minute", h: "hour", d: "day" }[m[2] as "s" | "m" | "h" | "d"];
    return n === 1 ? `Every ${unit}` : `Every ${n} ${unit}s`;
  }
  if ((m = /^daily (.+)$/.exec(body))) return `Every day at ${at(m[1])}${zone ? "" : " UTC"}`;
  if ((m = /^weekly (\S+) (.+)$/.exec(body))) return `Every ${m[1].split(",").join(", ")} at ${at(m[2])}${zone ? "" : " UTC"}`;
  if ((m = /^monthly (\d+) (.+)$/.exec(body))) return `Day ${m[1]} of each month at ${at(m[2])}${zone ? "" : " UTC"}`;
  return e || "Pick a schedule";
}

function fmt(iso: string | null): string {
  if (!iso) return "-";
  try {
    // The API sends UTC without a zone marker; read it as UTC.
    const utc = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + "Z";
    return new Date(utc).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function flash(msg: string) {
  note.value = msg;
  setTimeout(() => (note.value = ""), 3500);
}

async function load() {
  loadError.value = "";
  try {
    jobs.value = await api.listJobs();
    notifications.value = (await api.listNotifications()).notifications;
  } catch (err) {
    loadError.value = String(err instanceof Error ? err.message : err);
  }
}

async function create() {
  createError.value = "";
  creating.value = true;
  try {
    await api.createJob({
      objective: form.objective,
      schedule: scheduleExpr.value,
      budget_per_run_xp: 1000, // cap per run; only what's used is charged
      budget_total_xp: null,
    });
    form.objective = "";
    flash("Job created.");
    await load();
  } catch (err) {
    createError.value = String(err instanceof Error ? err.message : err);
  } finally {
    creating.value = false;
  }
}

async function act(fn: () => Promise<unknown>, done: string) {
  try {
    await fn();
    flash(done);
    await load();
  } catch (err) {
    createError.value = String(err instanceof Error ? err.message : err);
  }
}

const pause = (id: string) => act(() => api.pauseJob(id), "Job paused.");
const resume = (id: string) => act(() => api.resumeJob(id), "Job resumed.");
const cancel = (id: string) => {
  if (window.confirm("Stop this automation for good?")) {
    return act(() => api.cancelJob(id), "Job cancelled.");
  }
  return Promise.resolve();
};
const run = (id: string) => act(() => api.triggerJob(id), "Run triggered (executes inline).");

async function showRuns(jobId: string) {
  if (openRuns.value === jobId) {
    openRuns.value = null;
    return;
  }
  runs.value = await api.jobRuns(jobId);
  openRuns.value = jobId;
}

async function markRead(id: string) {
  await api.markNotificationRead(id);
  await load();
}

onMounted(load);
</script>

<style scoped>
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  min-width: 0;
  gap: 10px;
  margin: 12px 0;
}
.form-grid label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--dim, #8899aa);
}
.form-grid label:first-child {
  grid-column: 1 / -1;
}
.form-grid input {
  min-width: 0;
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 8px;
  background: transparent;
  color: inherit;
}
.sched {
  margin: 4px 0 14px;
}
.seg,
.days {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.seg button,
.days button {
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  background: transparent;
  color: inherit;
  font-size: 13px;
  text-transform: capitalize;
}
.seg button.on,
.days button.on {
  background: var(--accent, #f7931a);
  border-color: transparent;
  color: #111;
  font-weight: 600;
}
.sched-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
  font-size: 14px;
}
.sched-row input,
.sched-row select {
  padding: 7px 9px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 8px;
  background: transparent;
  color: inherit;
}
.sched-row .num {
  width: 64px;
}
.time {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}
.x {
  border: 0;
  background: none;
  color: inherit;
  font-size: 18px;
  padding: 0 4px;
  opacity: 0.6;
}
.small-btn {
  height: auto;
  min-height: 0;
  padding: 5px 10px;
  font-size: 12px;
}
.job {
  padding: 12px 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
}
.job-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}
.job-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.runs {
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(148, 163, 184, 0.08);
}
.run-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 4px 0;
  flex-wrap: wrap;
}
.row-list {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}
.badge {
  margin-left: 6px;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  border: 1px solid rgba(148, 163, 184, 0.4);
}
</style>
