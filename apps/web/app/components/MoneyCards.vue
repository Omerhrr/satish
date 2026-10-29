<template>
  <!-- Bitcoin price + alerts -->
  <section class="card">
    <div class="head">
      <h2>Bitcoin price</h2>
      <select class="cur" :value="currency" aria-label="Currency" @change="setCurrency(($event.target as HTMLSelectElement).value)">
        <option v-for="c in currencies" :key="c" :value="c">{{ c }}</option>
      </select>
    </div>
    <div v-if="btcPrice" class="price">{{ format(btcPrice, currency) }}</div>
    <p v-else class="dim small">Price not available right now.</p>
    <p v-if="btcPrice" class="dim small">1 sat ≈ {{ format(btcPrice / 1e8, currency) }}</p>

    <ul v-if="alerts.length" class="rows">
      <li v-for="a in alerts" :key="a.id" :class="{ done: !a.active }">
        <span>🔔 {{ a.direction === "above" ? "Above" : "Below" }} {{ format(a.target, a.currency) }}<template v-if="!a.active"> · sent ✓</template></span>
        <button class="x" :aria-label="'Remove alert'" @click="removeAlert(a.id)">✕</button>
      </li>
    </ul>
    <form class="row-form" @submit.prevent="addAlert">
      <select v-model="alertDir" aria-label="Direction">
        <option value="above">Tell me above</option>
        <option value="below">Tell me below</option>
      </select>
      <input v-model="alertTarget" inputmode="decimal" :placeholder="btcPrice ? Math.round(btcPrice * 1.05).toLocaleString() : 'price'" aria-label="Alert price" />
      <button class="btn small" :disabled="busy">Alert me</button>
    </form>
    <p v-if="alertError" class="small err">{{ alertError }}</p>
    <p v-else-if="alertNote" class="small ok">{{ alertNote }}</p>
    <p class="dim small">We'll message you in Telegram once, as soon as it happens.</p>
  </section>

  <!-- Savings goals -->
  <section class="card">
    <div class="head"><h2>Savings goals</h2></div>
    <p v-if="!goals.length" class="dim small">Save towards something: school fees, rent, a phone. Your whole Satish balance counts.</p>
    <div v-for="g in goals" :key="g.id" class="goal">
      <div class="goal-top">
        <b>{{ g.name }}</b>
        <button class="x" :aria-label="`Remove goal ${g.name}`" @click="removeGoal(g.id)">✕</button>
      </div>
      <div class="bar" role="progressbar" :aria-valuenow="pct(g)" aria-valuemin="0" aria-valuemax="100"><span :style="{ width: pct(g) + '%' }" /></div>
      <div class="dim small">
        {{ progressText(g) }}<template v-if="g.deadline"> · by {{ new Date(g.deadline).toLocaleDateString() }}</template>
        <template v-if="pct(g) >= 100"> · 🎉 reached</template>
      </div>
      <div v-if="pct(g) < 100 && planText(g)" class="small plan">{{ planText(g) }}</div>
    </div>
    <form class="goal-form" @submit.prevent="addGoal">
      <input v-model="goalName" maxlength="80" placeholder="Goal, e.g. School fees" aria-label="Goal name" />
      <div class="row-form">
        <input v-model="goalAmount" inputmode="decimal" placeholder="Amount" aria-label="Goal amount" />
        <select v-model="goalCur" aria-label="Goal currency">
          <option value="SAT">sats</option>
          <option v-for="c in currencies" :key="c" :value="c">{{ c }}</option>
        </select>
      </div>
      <label class="dim small">By (optional) <input v-model="goalDate" type="date" /></label>
      <button class="btn small" :disabled="goalBusy">Add goal</button>
    </form>
    <p v-if="goalError" class="small err">{{ goalError }}</p>
  </section>
</template>

<script setup lang="ts">
import type { PriceAlert, SavingsGoal } from "@xp/api-client";

/** Total sats the user holds (Bitcoin + Lightning), from the wallet page. */
const props = defineProps<{ totalSats: number; hidden?: boolean }>();
const api = useXpApi();
const { rates, currency, setCurrency, currencies, format, toFiat } = usePrice();

const btcPrice = computed(() => rates.rates[currency.value] || 0);
const alerts = ref<PriceAlert[]>([]);
const goals = ref<SavingsGoal[]>([]);
const alertDir = ref<"above" | "below">("above");
const alertTarget = ref("");
const goalName = ref("");
const goalAmount = ref("");
const goalCur = ref(currency.value);
const goalDate = ref("");

async function load() {
  try {
    [alerts.value, goals.value] = await Promise.all([api.priceAlerts(), api.goals()]);
  } catch {
    /* signed out or older server */
  }
}

const busy = ref(false);
const alertError = ref("");
const alertNote = ref("");

/** "170,000,000", "₦170m", "170 million", "95k" -> a number (or NaN). */
function parseMoney(text: string): number {
  const t = text.trim().toLowerCase().replace(/[₦$€£,\s]/g, "").replace(/million$/, "m").replace(/thousand$/, "k");
  const m = /^(\d+(?:\.\d+)?)([kmb])?$/.exec(t);
  if (!m) return NaN;
  const mult = { k: 1e3, m: 1e6, b: 1e9 }[m[2] as "k" | "m" | "b"] ?? 1;
  return Number(m[1]) * mult;
}

async function addAlert() {
  alertError.value = alertNote.value = "";
  // An empty box uses the suggested price shown in it.
  const target = alertTarget.value.trim() ? parseMoney(alertTarget.value) : Math.round(btcPrice.value * (alertDir.value === "above" ? 1.05 : 0.95));
  if (!(target > 0)) {
    alertError.value = "Type a price like 170,000,000 or 170m.";
    return;
  }
  busy.value = true;
  try {
    await api.addPriceAlert({ currency: currency.value, direction: alertDir.value, target });
    alertTarget.value = "";
    alertNote.value = `Done. We'll tell you when bitcoin goes ${alertDir.value} ${format(target, currency.value)}.`;
    await load();
  } catch (e) {
    alertError.value = e instanceof Error ? e.message : "Couldn't save the alert. Try again.";
  } finally {
    busy.value = false;
  }
}
async function removeAlert(id: string) {
  await api.deletePriceAlert(id);
  await load();
}
const goalBusy = ref(false);
const goalError = ref("");
async function addGoal() {
  goalError.value = "";
  const target = parseMoney(goalAmount.value);
  if (!goalName.value.trim()) return void (goalError.value = "Give your goal a name, like School fees.");
  if (!(target > 0)) return void (goalError.value = "Type an amount like 500,000 or 500k.");
  if (goalDate.value && new Date(goalDate.value + "T23:59:59") < new Date()) return void (goalError.value = "Pick a date in the future.");
  goalBusy.value = true;
  try {
    await api.addGoal({
      name: goalName.value.trim(),
      target_amount: target,
      currency: goalCur.value,
      deadline: goalDate.value ? new Date(goalDate.value + "T23:59:59").toISOString() : null,
    });
    goalName.value = goalAmount.value = goalDate.value = "";
    await load();
  } catch (e) {
    goalError.value = e instanceof Error ? e.message : "Couldn't save the goal.";
  } finally {
    goalBusy.value = false;
  }
}
async function removeGoal(id: string) {
  await api.deleteGoal(id);
  await load();
}

function saved(g: SavingsGoal): number {
  if (g.currency === "SAT") return props.totalSats;
  return toFiat(props.totalSats, g.currency) ?? 0;
}
function amount(v: number, cur: string): string {
  return cur === "SAT" ? `${Math.round(v).toLocaleString()} sats` : format(v, cur);
}
/** "Save about ₦25,000 a week to make it by 1 Dec." */
function planText(g: SavingsGoal): string {
  if (props.hidden) return "";
  const left = g.target_amount - saved(g);
  if (left <= 0) return "";
  if (!g.deadline) return `${amount(left, g.currency)} to go.`;
  const days = (new Date(g.deadline).getTime() - Date.now()) / 86_400_000;
  if (days < 0) return `The date has passed; ${amount(left, g.currency)} to go.`;
  const weeks = Math.max(1, Math.ceil(days / 7));
  return `${amount(left, g.currency)} to go: about ${amount(left / weeks, g.currency)} a week for ${weeks} week${weeks === 1 ? "" : "s"}.`;
}
function pct(g: SavingsGoal): number {
  return Math.max(0, Math.min(100, Math.floor((saved(g) / g.target_amount) * 100)));
}
function progressText(g: SavingsGoal): string {
  if (props.hidden) return `${pct(g)}% of ${amount(g.target_amount, g.currency)}`;
  if (g.currency !== "SAT" && toFiat(props.totalSats, g.currency) === null) return `Price for ${g.currency} not available right now`;
  const have = saved(g);
  if (g.currency === "SAT") return `${Math.round(have).toLocaleString()} of ${g.target_amount.toLocaleString()} sats (${pct(g)}%)`;
  return `${format(have, g.currency)} of ${format(g.target_amount, g.currency)} (${pct(g)}%)`;
}

// Celebrate once (in Telegram) when the balance first reaches a goal.
watch(
  () => goals.value.map((g) => [g.id, pct(g), g.reached_at] as const),
  async (list) => {
    for (const [id, p, reached] of list) {
      if (p >= 100 && !reached) {
        try {
          const g = await api.goalReached(id);
          goals.value = goals.value.map((x) => (x.id === id ? g : x));
        } catch {
          /* try again next time */
        }
      }
    }
  },
);

onMounted(load);
</script>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.cur, .row-form select { padding: 6px 8px; border-radius: 10px; border: 1px solid var(--border); background: var(--bg-elev); color: var(--text); }
.err { color: var(--red, #ef4444); }
.ok { color: var(--green, #22c55e); }
.price { font-size: 26px; font-weight: 700; margin: 6px 0 2px; }
.rows { list-style: none; padding: 0; margin: 10px 0; }
.rows li { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 14px; }
.rows li.done { color: var(--text-dim); }
.x { background: none; border: 0; color: var(--text-dim); cursor: pointer; font-size: 14px; }
.row-form { display: flex; gap: 6px; margin: 10px 0 4px; }
.row-form input, .goal-form > input, .goal-form label input { flex: 1; min-width: 0; padding: 8px 10px; border-radius: 10px; border: 1px solid var(--border); background: var(--bg); color: var(--text); font-size: 15px; }
.goal { margin: 12px 0; }
.goal-top { display: flex; justify-content: space-between; }
.bar { height: 8px; border-radius: 99px; background: var(--bg); border: 1px solid var(--border); overflow: hidden; margin: 6px 0 4px; }
.bar span { display: block; height: 100%; background: var(--orange, #f7931a); }
.plan { color: var(--orange, #f7931a); margin-top: 2px; }
.goal-form { display: flex; flex-direction: column; gap: 6px; margin-top: 12px; }
.goal-form label { display: flex; gap: 8px; align-items: center; }
</style>
