<template>
  <div>
    <h1 class="page-title">🗂 Agent tasks</h1>
    <p class="page-sub">
      Submit an objective, approve an XP budget, and the reservation is held
      atomically until the work settles or is cancelled.
    </p>

    <section class="card">
      <h2>New task</h2>
      <p class="sub">Budget approval is required before execution (task_charge_flow).</p>
      <form @submit.prevent="submit">
        <label class="field">
          Objective
          <textarea
            v-model="objective"
            rows="3"
            placeholder="e.g. Summarize recent cold-storage wallet security incidents and produce a PDF brief"
            required
            minlength="8"
            maxlength="4000"
          />
        </label>
        <label class="field">
          Budget (XP, reserved atomically)
          <input v-model.number="budget" type="number" min="1" max="100000" required />
        </label>
        <button class="btn primary" type="submit" :disabled="creating">
          <span v-if="creating" class="spinner" /> Create &amp; reserve budget
        </button>
        <span v-if="createError" class="small" style="color: var(--red); margin-left: 10px">{{ createError }}</span>
      </form>
    </section>

    <section class="card">
      <h2>Tasks <span class="dim">({{ tasks.length }})</span></h2>
      <div class="table-wrap" style="margin-top: 10px">
        <table class="ledger">
          <thead>
            <tr>
              <th>Created</th>
              <th>Objective</th>
              <th>Status</th>
              <th style="text-align: right">Budget</th>
              <th style="text-align: right">Actual</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading">
              <td colspan="6"><span class="spinner" /> Loading…</td>
            </tr>
            <tr v-else-if="tasks.length === 0">
              <td colspan="6" class="dim">No tasks yet.</td>
            </tr>
            <tr v-for="t in tasks" :key="t.id">
              <td class="mono small">{{ shortTime(t.created_at) }}</td>
              <td class="small" style="max-width: 280px">{{ t.objective }}</td>
              <td><span class="badge" :class="t.status">{{ t.status.replace("_", " ") }}</span></td>
              <td class="mono" style="text-align: right">{{ t.budget_xp.toLocaleString() }}</td>
              <td class="mono" style="text-align: right">{{ t.actual_xp.toLocaleString() }}</td>
              <td style="white-space: nowrap">
                <button
                  v-if="['planned', 'awaiting_approval'].includes(t.status)"
                  class="btn primary small"
                  :disabled="running === t.id"
                  @click="run(t.id)"
                >
                  <span v-if="running === t.id" class="spinner" />
                  {{ t.status === "awaiting_approval" ? "Resume" : "Run" }}
                </button>
                <button v-if="['planned', 'running'].includes(t.status)" class="btn small" @click="showEvents(t.id)">
                  Events
                </button>
                <button
                  v-if="['completed', 'failed', 'cancelled'].includes(t.status)"
                  class="btn small"
                  @click="showResult(t.id)"
                >
                  Result
                </button>
                <button
                  v-if="!['completed', 'failed', 'cancelled'].includes(t.status)"
                  class="btn sensitive-action small ghost"
                  @click="cancel(t.id)"
                >
                  Cancel
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="notice small">
        Execution runs through the DSH agent runtime: plan → typed allowlisted
        tools → evaluation → transparent report. Budget cap, tool timeouts, and
        approvals are enforced by deterministic backend code; pending tool
        approvals pause the run until you resume them here.
      </div>
    </section>

    <section v-if="eventTask" class="card">
      <h2>Event stream <span class="dim small">task {{ eventTask.slice(0, 8) }} · {{ eventStatus }}</span></h2>
      <div class="table-wrap" style="margin-top: 10px">
        <table class="ledger">
          <thead>
            <tr><th>#</th><th>Event</th><th>Detail</th></tr>
          </thead>
          <tbody>
            <tr v-for="e in events" :key="e.seq">
              <td class="mono small">{{ e.seq }}</td>
              <td class="mono small">{{ e.event_type }}</td>
              <td class="mono small dim" style="max-width: 480px; overflow-wrap: anywhere">{{ compact(e.payload) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="pendingApprovals.length" class="notice small">
        <strong>{{ pendingApprovals.length }} approval(s) pending.</strong>
        <div v-for="a in pendingApprovals" :key="a.id" style="margin-top: 8px">
          {{ a.action_type }} · digest {{ a.action_digest.slice(0, 12) }}…
          <button class="btn primary small" style="margin-left: 8px" @click="decide(a.id, true)">Approve</button>
          <button class="btn sensitive-action small ghost" style="margin-left: 6px" @click="decide(a.id, false)">Deny</button>
        </div>
      </div>
    </section>

    <section v-if="result" class="card">
      <h2>Result <span class="dim small">task {{ result.task_id.slice(0, 8) }}</span></h2>
      <p class="small" style="margin: 6px 0">
        <strong>Deliverable:</strong> {{ result.deliverable || "-" }}
      </p>

      <h3 class="small" style="margin: 14px 0 4px">Artifacts (validated, private)</h3>
      <ul class="small">
        <li v-for="a in result.artifacts" :key="a.id">
          <a :href="artifactHref(a.download_url)" target="_blank" rel="noopener">{{ a.filename }}</a>
          · {{ a.content_type }} · {{ (a.size_bytes / 1024).toFixed(1) }} KB
          · sha256 {{ (a.sha256 || "").slice(0, 12) }}…
        </li>
        <li v-if="result.artifacts.length === 0" class="dim">No artifacts were produced.</li>
      </ul>

      <h3 class="small" style="margin: 14px 0 4px">Sources &amp; provenance</h3>
      <ul class="small">
        <li v-for="(s, i) in result.sources" :key="i">
          [{{ i + 1 }}] <span class="badge" :class="s.status">{{ s.status }}</span>
          {{ s.title || "(untitled)" }} - <span class="mono small">{{ s.url }}</span>
          · {{ s.fact_count }} facts · {{ s.retrieval_mode }}
          · <span class="dim">freshness {{ s.freshness }}</span>
          · <span class="dim">confidence {{ s.confidence }}</span>
        </li>
        <li v-if="result.sources.length === 0" class="dim">No sources were collected.</li>
      </ul>

      <div v-if="result.conflicts.length" class="notice small" style="border-left-color: var(--red)">
        <strong>Conflicts between sources</strong>
        <div v-for="(c, i) in result.conflicts" :key="i">{{ c.subject }} - {{ c.detail }}</div>
      </div>
      <div v-if="result.gaps.length" class="notice small">
        <strong>Coverage gaps:</strong> {{ result.gaps.join(", ") }}
      </div>

      <div v-if="result.scored" class="notice small">
        <strong>Commerce score: {{ result.scored.product }} - {{ result.scored.score }} / 100</strong>
        <div class="dim small" style="margin: 4px 0">
          Structural signals only - this score does not measure demand, ad
          performance, or availability. Factors and weights are operator-configured:
        </div>
        <table class="small" style="width: 100%; border-collapse: collapse; margin-top: 4px">
          <thead>
            <tr style="text-align: left">
              <th style="padding: 2px 6px 2px 0">factor</th>
              <th style="padding: 2px 6px">weight</th>
              <th style="padding: 2px 6px">signal</th>
              <th style="padding: 2px 6px">normalized</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="f in result.scored.factors" :key="f.name" :class="{ dim: !f.included }">
              <td style="padding: 2px 6px 2px 0">{{ f.name }}<span v-if="!f.included"> (excluded)</span></td>
              <td style="padding: 2px 6px">{{ f.weight }}</td>
              <td style="padding: 2px 6px">{{ f.signal }}</td>
              <td style="padding: 2px 6px">{{ f.normalized ?? "-" }}</td>
            </tr>
          </tbody>
        </table>
        <div v-for="(d, i) in result.scored.disclosures" :key="i" class="dim small">• {{ d }}</div>
      </div>

      <h3 class="small" style="margin: 14px 0 4px">Limitations</h3>
      <ul class="small dim">
        <li v-for="(l, i) in result.limitations" :key="i">{{ l }}</li>
      </ul>

      <h3 class="small" style="margin: 14px 0 4px">XP receipt</h3>
      <p class="small mono">
        {{ receiptLine }}
      </p>
    </section>
  </div>
</template>

<script setup lang="ts">
import type { ApprovalOut, TaskEventOut, TaskOut, TaskResultOut } from "@xp/shared-types";

const api = useXpApi();
const tasks = ref<TaskOut[]>([]);
const loading = ref(true);
const creating = ref(false);
const createError = ref("");
const objective = ref("");
const budget = ref(100);
const running = ref<string | null>(null);
const eventTask = ref<string | null>(null);
const eventStatus = ref("");
const events = ref<TaskEventOut[]>([]);
const pendingApprovals = ref<ApprovalOut[]>([]);
const result = ref<TaskResultOut | null>(null);

function shortTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function compact(payload: Record<string, unknown>): string {
  return JSON.stringify(payload).slice(0, 220);
}

async function refresh() {
  loading.value = true;
  try {
    tasks.value = await api.listTasks();
  } finally {
    loading.value = false;
  }
}

async function submit() {
  creating.value = true;
  createError.value = "";
  try {
    await api.createTask({ objective: objective.value, budget_xp: budget.value });
    objective.value = "";
    await refresh();
  } catch (e) {
    createError.value = String(e).replace("XP API ", "");
  } finally {
    creating.value = false;
  }
}

async function run(id: string) {
  running.value = id;
  try {
    await api.runTask(id);
    await refresh();
    if (eventTask.value === id) await loadEvents(id);
  } catch (e) {
    alert(String(e).replace("XP API ", ""));
  } finally {
    running.value = null;
  }
}

async function loadEvents(id: string) {
  const page = await api.taskEvents(id);
  eventTask.value = page.task_id;
  eventStatus.value = page.status;
  events.value = page.events;
  pendingApprovals.value = (await api.listApprovals(id)).filter((a) => a.status === "pending");
}

async function showEvents(id: string) {
  await loadEvents(id);
}

async function showResult(id: string) {
  try {
    result.value = await api.taskResult(id);
  } catch (e) {
    alert(String(e).replace("XP API ", ""));
  }
}

function artifactHref(url: string): string {
  // download_url is already a same-origin API path; auth rides the session cookie
  // in gateway mode or the token query in direct mode (api-client buildUrl).
  return url;
}

const receiptLine = computed(() => {
  const r = result.value?.xp_receipt;
  if (!r) return "";
  const base = `budget ${r.budget_xp.toLocaleString()} XP · charged ${r.actual_xp.toLocaleString()} XP · released ${r.released_xp.toLocaleString()} XP · ${r.status.replace("_", " ")}`;
  const balance = r.balance_after !== null ? ` · balance after ${r.balance_after.toLocaleString()} XP` : "";
  const entry = r.charge_entry_id ? ` · entry ${r.charge_entry_id.slice(0, 8)}…` : "";
  return base + balance + entry;
});

async function decide(approvalId: string, approve: boolean) {
  if (!eventTask.value) return;
  await api.decideApproval(eventTask.value, approvalId, approve);
  await loadEvents(eventTask.value);
  await refresh();
}

async function cancel(id: string) {
  try {
    await api.cancelTask(id);
    await refresh();
  } catch (e) {
    alert(String(e));
  }
}

onMounted(refresh);
</script>
