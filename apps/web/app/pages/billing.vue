<template>
  <div>
    <header>
      <h1 class="page-title">Buy XP</h1>
      <p class="page-sub">
        XP are credits you spend on tasks. Pay in sats over Lightning.
        1 sat = {{ rate?.xp_per_sat ?? "…" }} XP
        <span v-if="rate" class="env-chip">{{ rate.can_change ? "rate may change" : "fixed" }}</span>
      </p>
    </header>

    <section class="card">
      <h2>Balance</h2>
      <div class="balance-big">{{ balance ? balance.balance_xp.toLocaleString() + " XP" : "…" }}</div>
      <p class="dim small" v-if="balance">
        ≈ {{ Math.ceil(balance.balance_xp / balance.xp_per_sat).toLocaleString() }} sats equivalent
      </p>
    </section>

    <section class="card">
      <h2>Buy XP</h2>
      <p class="dim small">
        Pick a pack to get a Lightning invoice. Your XP arrives as soon as the
        payment is confirmed.
      </p>
      <div class="packs">
        <button
          v-for="p in packs"
          :key="p.pack_id"
          class="btn pack sensitive-action"
          :disabled="buying !== null"
          @click="buy(p)"
        >
          <span v-if="buying === p.pack_id" class="spinner" />
          <strong>{{ p.amount_sats.toLocaleString() }} sats</strong>
          <span class="dim">→ {{ p.xp_amount.toLocaleString() }} XP</span>
        </button>
      </div>
      <p v-if="error" class="notice small">{{ error }}</p>
    </section>

    <section class="card">
      <h2>Purchases &amp; receipts</h2>
      <p v-if="!purchases.length" class="dim small">No purchases yet.</p>
      <div v-else class="table-wrap"><table class="ledger">
        <thead>
          <tr><th>Sats</th><th>XP</th><th>Status</th><th>Receipt</th></tr>
        </thead>
        <tbody>
          <tr v-for="p in purchases" :key="p.id">
            <td>{{ p.amount_sats.toLocaleString() }}</td>
            <td>+{{ p.xp_amount.toLocaleString() }}</td>
            <td>
              <span class="chip" :class="p.status">{{ human(p.status) }}</span>
              <button
                v-if="p.status === 'pending'"
                class="btn small sensitive-action"
                :disabled="settling !== null"
                @click="settle(p)"
              >
                <span v-if="settling === p.id" class="spinner" /> Confirm payment
              </button>
            </td>
            <td>
              <button
                v-if="p.status === 'settled'"
                class="btn small"
                :disabled="receipting !== null"
                @click="receipt(p)"
              >
                <span v-if="receipting === p.id" class="spinner" /> PDF
              </button>
              <span v-else class="dim small">-</span>
            </td>
          </tr>
        </tbody>
      </table></div>
      <p class="dim small">
        Demo mode: payments are simulated, so no real bitcoin moves. Tap
        "Confirm payment" to complete a purchase.
      </p>
    </section>
  </div>
</template>

<script setup lang="ts">
import type { BalanceOut, PackOut, PurchaseOut, RateOut } from "@xp/shared-types";

const api = useXpApi();

const rate = ref<RateOut | null>(null);
const balance = ref<BalanceOut | null>(null);
const packs = ref<PackOut[]>([]);
const purchases = ref<PurchaseOut[]>([]);
const buying = ref<string | null>(null);
const settling = ref<string | null>(null);
const receipting = ref<string | null>(null);
const error = ref<string | null>(null);

async function refresh() {
  try {
    const [r, b, p, purchasesList] = await Promise.all([
      api.rate(),
      api.balance(),
      api.packs(),
      api.listPurchases(),
    ]);
    rate.value = r;
    balance.value = b;
    packs.value = p;
    purchases.value = purchasesList;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "failed to load billing data";
  }
}

async function buy(pack: PackOut) {
  buying.value = pack.pack_id;
  error.value = null;
  try {
    await api.createPurchase({ pack_id: pack.pack_id, description: `XP pack ${pack.label}` });
    await refresh();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "purchase failed";
  } finally {
    buying.value = null;
  }
}

async function settle(p: PurchaseOut) {
  if (!p.payment_hash) return;
  settling.value = p.id;
  error.value = null;
  try {
    await api.settleDevInvoice(p.payment_hash);
    await refresh();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "settlement failed";
  } finally {
    settling.value = null;
  }
}

async function receipt(p: PurchaseOut) {
  receipting.value = p.id;
  error.value = null;
  try {
    const art = await api.createReceiptArtifact(p.id);
    window.open(api.receiptPdfUrl(p.id), "_blank", "noopener");
    void art;
    await refresh();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "receipt failed";
  } finally {
    receipting.value = null;
  }
}

onMounted(refresh);
</script>

<style scoped>
.packs {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.pack {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 150px;
}
.chip.pending {
  color: #b45309;
  background: #fef3c7;
}
.chip.settled {
  color: #166534;
  background: #dcfce7;
}
.chip.expired {
  color: #7f1d1d;
  background: #fee2e2;
}
</style>
