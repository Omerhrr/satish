<template>
  <div>
    <div class="ask-head">
      <h1 class="page-title">Ask Satish AI</h1>
      <NuxtLink to="/billing" class="credit-chip">{{ balance !== null ? balance.toLocaleString() + " TK" : "… TK" }}</NuxtLink>
    </div>
    <p class="page-sub">
      Research, price comparisons and written reports with sources. You set a budget;
      you only pay for what it uses and the rest comes back.
      <NuxtLink to="/ai">What can it do?</NuxtLink>
    </p>

    <div v-if="aiStatus && !aiStatus.online" class="offline" role="status">
      Satish AI is offline right now. Tasks you start will wait for it, and if it doesn't start
      within 3 minutes your TK is returned.
    </div>

    <section class="card">
      <h2>New task</h2>
      <p class="sub">Nothing runs until you approve the budget.</p>
      <form @submit.prevent="submit">
        <label class="field">
          What do you need?
          <textarea
            v-model="objective"
            rows="3"
            placeholder="e.g. Compare prices of a 50kg bag of rice in Kaduna markets and make me a PDF report"
            required
            minlength="2"
            maxlength="4000"
          />
        </label>
        <label class="field">
          Budget (TK)
          <input v-model.number="budget" type="number" min="1" max="100000" required />
          <span v-if="budgetWorth" class="small dim">That's up to {{ budgetWorth }}. Unused TK comes back.</span>
        </label>
        <button class="btn primary" type="submit" :disabled="creating">
          <span v-if="creating" class="spinner" /> Create task
        </button>
        <span v-if="createError" class="small" style="color: var(--red); margin-left: 10px">{{ createError }}</span>
      </form>
    </section>

    <section class="card">
      <h2>Tasks <span class="dim">({{ tasks.length }})</span></h2>
      <p v-if="loading" class="small dim" style="margin-top: 8px"><span class="spinner" /> Loading…</p>
      <p v-else-if="tasks.length === 0" class="small dim" style="margin-top: 8px">No tasks yet. Ask for something above, or try a free sample report on <NuxtLink to="/ai">What can it do?</NuxtLink></p>
      <div v-for="t in tasks" :key="t.id" class="task">
        <div class="task-top">
          <span class="badge" :class="t.status">{{ human(t.status) }}</span>
          <span class="small dim">{{ shortTime(t.created_at) }}</span>
        </div>
        <p class="task-obj">{{ t.objective }}</p>
        <div v-if="t.status === 'running' && t.queued" class="small working">
          <span class="spinner" /> Waiting to start…<template v-if="aiStatus && !aiStatus.online"> Satish AI is offline right now.</template>
        </div>
        <div v-else-if="t.status === 'running'" class="small working"><span class="spinner" /> Working on it…</div>
        <div v-if="t.error" class="small task-err">{{ t.error }}</div>
        <div class="task-foot">
          <span class="small dim">{{ t.actual_xp.toLocaleString() }} of {{ t.budget_xp.toLocaleString() }} TK used</span>
          <span class="task-acts">
            <button
              v-if="['planned', 'awaiting_approval'].includes(t.status)"
              class="btn primary small"
              :disabled="running === t.id"
              @click="run(t.id)"
            >
              <span v-if="running === t.id" class="spinner" />
              {{ t.status === "awaiting_approval" ? "Resume" : "Run" }}
            </button>
            <button v-if="['planned', 'running'].includes(t.status)" class="btn small" @click="showEvents(t.id)">Progress</button>
            <button v-if="['completed', 'failed', 'cancelled'].includes(t.status)" class="btn small" @click="showResult(t.id)">Result</button>
            <button v-if="!['completed', 'failed', 'cancelled'].includes(t.status)" class="btn sensitive-action small ghost" @click="cancel(t.id)">Cancel</button>
          </span>
        </div>
      </div>
      <div class="notice small">
        The assistant plans the work, uses only approved tools, and never goes
        over your budget. If it needs your OK for something (like sending an
        email), it pauses here until you approve.
      </div>
    </section>

    <section v-if="eventTask" class="card">
      <h2>Progress <span class="dim small">{{ human(eventStatus) }}</span></h2>
      <div class="table-wrap" style="margin-top: 10px">
        <table class="ledger">
          <thead>
            <tr><th>#</th><th>Step</th><th>Details</th></tr>
          </thead>
          <tbody>
            <tr v-for="e in events" :key="e.seq">
              <td class="mono small">{{ e.seq }}</td>
              <td class="small">{{ human(e.event_type) }}</td>
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
      <h2>Result</h2>
      <p class="small" style="margin: 6px 0">
        <div class="answer">{{ result.answer || result.deliverable || "-" }}</div>
      </p>

      <h3 class="small" style="margin: 14px 0 4px">Your files (private)</h3>
      <ul class="small">
        <li v-for="a in result.artifacts" :key="a.id">
          <a href="#" @click.prevent="download(a.download_url, a.filename)">{{ a.filename }}</a>
          · {{ (a.size_bytes / 1024).toFixed(1) }} KB
        </li>
        <li v-if="result.artifacts.length === 0" class="dim">No files were created.</li>
      </ul>

      <h3 class="small" style="margin: 14px 0 4px">Sources</h3>
      <ul class="small">
        <li v-for="(s, i) in result.sources" :key="i">
          [{{ i + 1 }}] <span class="badge" :class="s.status">{{ s.status }}</span>
          {{ s.title || "(untitled)" }} - <span class="mono small">{{ s.url }}</span>
          · <span class="dim">{{ human(s.confidence) }} confidence</span>
        </li>
        <li v-if="result.sources.length === 0" class="dim">No sources were used.</li>
      </ul>

      <div v-if="result.conflicts.length" class="notice small" style="border-left-color: var(--red)">
        <strong>Where sources disagree</strong>
        <div v-for="(c, i) in result.conflicts" :key="i">{{ c.subject }} - {{ c.detail }}</div>
      </div>
      <div v-if="result.gaps.length" class="notice small">
        <strong>What we couldn't find:</strong> {{ result.gaps.join(", ") }}
      </div>

      <div v-if="result.scored" class="notice small">
        <strong>{{ result.scored.product }}: {{ result.scored.score }} / 100</strong>
        <div class="dim small" style="margin: 4px 0">
          A guide based on listing details. It doesn't measure real demand or
          stock. How the score was built:
        </div>
        <table class="small" style="width: 100%; border-collapse: collapse; margin-top: 4px">
          <thead>
            <tr style="text-align: left">
              <th style="padding: 2px 6px 2px 0">What we looked at</th>
              <th style="padding: 2px 6px">Importance</th>
              <th style="padding: 2px 6px">Found</th>
              <th style="padding: 2px 6px">Score</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="f in result.scored.factors" :key="f.name" :class="{ dim: !f.included }">
              <td style="padding: 2px 6px 2px 0">{{ f.name }}<span v-if="!f.included"> (not counted)</span></td>
              <td style="padding: 2px 6px">{{ f.weight }}</td>
              <td style="padding: 2px 6px">{{ f.signal }}</td>
              <td style="padding: 2px 6px">{{ f.normalized ?? "-" }}</td>
            </tr>
          </tbody>
        </table>
        <div v-for="(d, i) in result.scored.disclosures" :key="i" class="dim small">• {{ d }}</div>
      </div>

      <h3 class="small" style="margin: 14px 0 4px">Good to know</h3>
      <ul class="small dim">
        <li v-for="(l, i) in result.limitations" :key="i">{{ l }}</li>
      </ul>

      <h3 class="small" style="margin: 14px 0 4px">TK used</h3>
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
const budget = ref(1000);
const balance = ref<number | null>(null);
const tkPerSat = ref<number | null>(null);
const { naira } = usePrice();
const budgetWorth = computed(() => {
  if (!tkPerSat.value || !budget.value) return "";
  const sats = Math.ceil(budget.value / tkPerSat.value);
  return `${sats.toLocaleString()} sats` + (naira(sats) ? ` (${naira(sats)})` : "");
});
async function loadCredits() {
  try {
    const b = await api.balance();
    balance.value = b.balance_xp;
    tkPerSat.value = b.xp_per_sat;
  } catch {
    /* shown as "… TK" */
  }
}
const running = ref<string | null>(null);
const eventTask = ref<string | null>(null);
const eventStatus = ref("");
const events = ref<TaskEventOut[]>([]);
const pendingApprovals = ref<ApprovalOut[]>([]);
const result = ref<TaskResultOut | null>(null);

function shortTime(iso: string) {
  return niceDate(new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").getTime() / 1000);
}

function compact(payload: Record<string, unknown>): string {
  return JSON.stringify(payload).slice(0, 220);
}

let poller: ReturnType<typeof setTimeout> | null = null;

const aiStatus = ref<{ online: boolean; queued: number; running: number } | null>(null);
async function loadAiStatus() {
  try {
    aiStatus.value = await api.aiStatus();
  } catch {
    /* unknown: show nothing */
  }
}

async function refresh() {
  void loadCredits();
  void loadAiStatus();
  loading.value = true;
  try {
    tasks.value = await api.listTasks();
  } finally {
    loading.value = false;
  }
  schedulePoll();
}

/** Tasks run in the background: keep checking while any is still working. */
function schedulePoll() {
  if (poller) clearTimeout(poller);
  poller = null;
  if (!tasks.value.some((t) => t.status === "running")) return;
  poller = setTimeout(async () => {
    try {
      const before = new Map(tasks.value.map((t) => [t.id, t.status]));
      tasks.value = await api.listTasks();
      void loadAiStatus();
      if (eventTask.value) await loadEvents(eventTask.value);
      const finished = tasks.value.find((t) => before.get(t.id) === "running" && t.status === "completed");
      if (finished) await showResult(finished.id);
    } catch {
      /* try again next tick */
    }
    schedulePoll();
  }, 3000);
}

async function download(url: string, filename: string) {
  try {
    const token = sessionStorage.getItem("xp_session_token") ?? localStorage.getItem("xp_session_token");
    const res = await fetch(api.artifactDownloadUrl({ id: url.split("/").slice(-2)[0] } as any), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error();
    const href = URL.createObjectURL(await res.blob());
    const link = document.createElement("a");
    link.href = href;
    link.download = filename || "report.pdf";
    link.click();
    setTimeout(() => URL.revokeObjectURL(href), 10_000);
  } catch {
    alert("Couldn't download that file. Please try again.");
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
    createError.value = String(e);
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
    alert(e instanceof Error ? e.message : String(e));
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
    alert(e instanceof Error ? e.message : String(e));
  }
}


const receiptLine = computed(() => {
  const r = result.value?.xp_receipt;
  if (!r) return "";
  const base = `budget ${r.budget_xp.toLocaleString()} TK · charged ${r.actual_xp.toLocaleString()} TK · released ${r.released_xp.toLocaleString()} TK · ${r.status.replace("_", " ")}`;
  const balance = r.balance_after !== null ? ` · balance after ${r.balance_after.toLocaleString()} TK` : "";
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
    alert(e instanceof Error ? e.message : String(e));
  }
}

onMounted(refresh);
onBeforeUnmount(() => poller && clearTimeout(poller));
</script>

<style scoped>
.answer { white-space: pre-wrap; line-height: 1.6; font-size: 15px; margin: 4px 0 10px; }
.offline { background: var(--orange-soft); color: var(--orange); border-radius: 12px; padding: 10px 14px; margin-bottom: 12px; font-size: 14px; }
.ask-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.credit-chip { flex: none; font-size: 13px; font-weight: 700; color: var(--orange); background: var(--orange-soft); border-radius: 999px; padding: 4px 12px; }
.task { padding: 12px 0; border-bottom: 1px solid var(--border); }
.task:last-of-type { border-bottom: 0; }
.task-top { display: flex; justify-content: space-between; align-items: center; }
.task-obj { margin: 6px 0; font-size: 14px; }
.task-foot { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
.task-acts { display: flex; gap: 6px; flex-wrap: wrap; }
.working { color: var(--orange); display: flex; gap: 6px; align-items: center; margin-top: 4px; }
.task-err { color: var(--red); margin-top: 4px; }
</style>
