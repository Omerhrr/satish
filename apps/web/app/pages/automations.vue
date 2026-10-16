<template>
  <div>
    <h1 class="page-title">⏱ Automations</h1>
    <p class="page-sub">
      Scheduled jobs run within hard XP budgets - per run and in total. Every attempt
      is recorded, failures pause the job instead of silently repeating, and anything
      consequential (like email) always waits for your approval.
    </p>

    <section class="card">
      <h2>New scheduled job</h2>
      <div class="form-grid">
        <label>Objective (task goal)<input v-model="form.objective" placeholder="Monitor supplier prices daily" /></label>
        <label>Schedule<input v-model="form.schedule" placeholder="every 1h · daily 09:30 · hourly" /></label>
        <label>Budget per run (XP)<input v-model="form.budgetPerRun" inputmode="numeric" /></label>
        <label>Total budget (XP, optional)<input v-model="form.budgetTotal" inputmode="numeric" placeholder="-" /></label>
      </div>
      <p class="small dim">
        Supported schedules: <code>every &lt;n&gt;&lt;s|m|h|d&gt;</code> (≥ 60s),
        <code>daily HH:MM</code> (UTC), <code>hourly</code>, <code>daily</code>.
      </p>
      <button class="btn" :disabled="creating || !form.objective" @click="create">
        <span v-if="creating" class="spinner" /> Create job
      </button>
      <span v-if="note" class="small" style="margin-left: 10px">{{ note }}</span>
      <p v-if="createError" class="small" style="color: #f59e0b">{{ createError }}</p>
    </section>

    <section class="card">
      <h2>Jobs</h2>
      <p v-if="loadError" class="small" style="color: #f59e0b">{{ loadError }}</p>
      <p v-else-if="!jobs.length" class="small dim">No automations yet.</p>
      <div v-for="j in jobs" :key="j.id" class="job">
        <div class="job-head">
          <div>
            <div class="small"><b>{{ j.objective }}</b></div>
            <div class="small dim">
              {{ j.schedule }} · {{ j.status }}
              <span v-if="j.auto_paused_reason"> ({{ j.auto_paused_reason }})</span>
              · next: {{ fmt(j.next_run_at) }}
              · spent {{ j.total_spent_xp }}/{{ j.budget_total_xp ?? "∞" }} XP
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
            <span>#{{ r.run_number }} · {{ r.trigger }} ·
              <span class="badge" :data-status="r.status">{{ r.status }}</span>
              · {{ r.xp_charged }}/{{ r.xp_budget_per_run }} XP
            </span>
            <span class="dim"> {{ fmt(r.started_at) }}<span v-if="r.error"> · {{ r.error }}</span></span>
          </div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Notifications</h2>
      <p class="small dim">
        Condition-based alerts from your jobs (run outcomes, balance thresholds).
        Persisted here; Telegram relay is a planned addition - this page is the
        delivery surface for now.
      </p>
      <p v-if="!notifications.length" class="small dim">Nothing yet.</p>
      <div v-for="n in notifications" :key="n.id" class="row-list">
        <div>
          <div class="small">
            <b>{{ n.kind }}</b>
            <span v-if="!n.read_at" class="badge">unread</span>
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
  schedule: "daily 09:30",
  budgetPerRun: "20",
  budgetTotal: "",
});

function fmt(iso: string | null): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString();
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
      schedule: form.schedule,
      budget_per_run_xp: Math.max(1, Number(form.budgetPerRun) || 20),
      budget_total_xp: form.budgetTotal ? Number(form.budgetTotal) : null,
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
  if (window.confirm("Cancel this job permanently?")) {
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
.form-grid input {
  padding: 8px 10px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 8px;
  background: transparent;
  color: inherit;
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
