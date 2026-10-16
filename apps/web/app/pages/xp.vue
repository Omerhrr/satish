<template>
  <div>
    <h1 class="page-title">⚡ XP Ledger</h1>
    <p class="page-sub">
      Append-only accounting. Balance always equals the sum of entries - every
      credit, reservation, charge and refund is a visible line.
    </p>

    <section class="card">
      <div style="display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap">
        <div class="balance-big">{{ balance ? balance.balance_xp.toLocaleString() + " XP" : "…" }}</div>
        <div class="dim small" v-if="balance">≈ {{ Math.ceil(balance.balance_xp / balance.xp_per_sat).toLocaleString() }} sats equivalent spend capacity · rate 1 sat = {{ balance.xp_per_sat }} XP</div>
      </div>
      <div style="margin-top: 12px; display: flex; gap: 10px; flex-wrap: wrap">
        <button class="btn primary small" :disabled="granting" @click="grant(1000)">
          <span v-if="granting" class="spinner" /> +1,000 XP (dev)
        </button>
        <button class="btn small" @click="refresh">Refresh</button>
      </div>
    </section>

    <section class="card">
      <h2>Ledger entries <span class="dim">({{ ledger?.total ?? 0 }})</span></h2>
      <div class="table-wrap" style="margin-top: 10px">
        <table class="ledger">
          <thead>
            <tr>
              <th>When</th>
              <th>Type</th>
              <th style="text-align: right">Δ XP</th>
              <th style="text-align: right">Balance</th>
              <th>Reference</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!ledger">
              <td colspan="6"><span class="spinner" /> Loading…</td>
            </tr>
            <tr v-else-if="ledger.items.length === 0">
              <td colspan="6" class="dim">No entries yet - seed some XP to see the ledger move.</td>
            </tr>
            <tr v-for="e in ledger?.items ?? []" :key="e.id">
              <td class="mono small">{{ shortTime(e.created_at) }}</td>
              <td><span class="badge" :class="badgeClass(e.entry_type)">{{ e.entry_type }}</span></td>
              <td style="text-align: right" :class="e.amount >= 0 ? 'amount-pos' : 'amount-neg'">
                {{ e.amount >= 0 ? "+" : "" }}{{ e.amount.toLocaleString() }}
              </td>
              <td class="mono" style="text-align: right">{{ e.balance_after.toLocaleString() }}</td>
              <td class="mono small dim">{{ e.reference_type || "-" }}<template v-if="e.reference_id"> · {{ e.reference_id.slice(0, 8) }}</template></td>
              <td class="small dim">{{ e.note ?? "-" }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div class="notice small">
      XP is an internal usage-credit unit. It is not Bitcoin, not a blockchain
      token, and not a claim on funds. Purchases require a verified settled
      payment, credited exactly once.
    </div>
  </div>
</template>

<script setup lang="ts">
import type { BalanceOut, LedgerPageOut } from "@xp/shared-types";

const api = useXpApi();
const balance = ref<BalanceOut | null>(null);
const ledger = ref<LedgerPageOut | null>(null);
const granting = ref(false);

function badgeClass(t: string) {
  if (t === "purchase" || t === "refund" || t === "reservation_release") return "completed";
  if (t === "reservation" || t === "charge") return "awaiting_approval";
  return "not_configured";
}

function shortTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

async function refresh() {
  [balance.value, ledger.value] = await Promise.all([api.balance(), api.ledger(100)]);
}

async function grant(amount: number) {
  granting.value = true;
  try {
    await api.devGrant({ amount_xp: amount, reason: "ledger page grant" });
    await refresh();
  } finally {
    granting.value = false;
  }
}

onMounted(refresh);
</script>
