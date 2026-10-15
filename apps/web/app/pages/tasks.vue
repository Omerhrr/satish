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
              <td>
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
        Execution through the DSH agent runtime (plan → approve → typed tools →
        report) activates once the DSH integration spike pins an upstream
        revision. Reservations and cancellations already settle correctly today.
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import type { TaskOut } from "@xp/shared-types";

const api = useXpApi();
const tasks = ref<TaskOut[]>([]);
const loading = ref(true);
const creating = ref(false);
const createError = ref("");
const objective = ref("");
const budget = ref(100);

function shortTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
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
