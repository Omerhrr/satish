<template>
  <div>
    <header>
      <h1 class="page-title">Buy XP</h1>
      <p class="page-sub">
        XP are credits you spend on tasks. You pay for them in bitcoin.
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
        Pick a pack, then pay from your XP wallet in one tap (or any other
        bitcoin wallet). Your XP arrives as soon as the payment is confirmed.
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
          <span v-if="naira(p.amount_sats)" class="dim small">{{ naira(p.amount_sats) }}</span>
        </button>
      </div>
      <p v-if="error" class="notice small">{{ error }}</p>
    </section>

    <section v-if="paying" ref="payCard" class="card pay">
      <h2>Pay {{ paying.amount_sats.toLocaleString() }} sats <span v-if="naira(paying.amount_sats)" class="dim small">{{ naira(paying.amount_sats) }}</span></h2>
      <template v-if="paying.status === 'settled'">
        <p class="paid">✅ Paid. +{{ paying.xp_amount.toLocaleString() }} XP added to your balance.</p>
        <button class="btn" @click="paying = null">Done</button>
      </template>
      <template v-else>
        <p class="sub">
          You'll get <b>{{ paying.xp_amount.toLocaleString() }} XP</b> as soon as the payment arrives.
          <template v-if="paying.network === 'testnet'"> (Test network: use test coins.)</template>
        </p>

        <div v-if="walletReady" class="from-wallet">
          <b>Pay from my XP wallet</b>
          <span class="small dim">Balance: {{ w.spendable.value.toLocaleString() }} sats</span>
          <template v-if="feeRates && quote">
            <span class="small dim">Network fee about {{ quote.fee.toLocaleString() }} sats · total {{ (quote.amount + quote.fee).toLocaleString() }} sats</span>
            <label class="field">Wallet password<input v-model="password" type="password" autocomplete="current-password" /></label>
            <button class="btn primary" :disabled="sending || !password" @click="payFromWallet">
              <span v-if="sending" class="spinner" /> Pay now
            </button>
          </template>
          <span v-else-if="quoteError" class="small err">{{ quoteError }}</span>
          <span v-else class="small dim"><span class="spinner" /> Getting network fee…</span>
        </div>
        <p v-else-if="walletNote" class="small dim">{{ walletNote }}</p>

        <details class="other">
          <summary class="small">Pay from another wallet</summary>
          <div class="qr" v-html="qrSvg" />
          <div class="addr mono">{{ paying.address }}</div>
          <button class="btn small" @click="copy(paying.address!)">{{ copied ? "Copied ✓" : "Copy address" }}</button>
          <p class="small dim">Send exactly {{ paying.amount_sats.toLocaleString() }} sats or more to this address.</p>
        </details>

        <p class="small status">
          <span class="spinner" />
          <template v-if="(paying.seen_sats ?? 0) >= paying.amount_sats">Payment seen. Waiting for the network to confirm it…</template>
          <template v-else-if="paying.seen_sats">Received {{ paying.seen_sats.toLocaleString() }} of {{ paying.amount_sats.toLocaleString() }} sats…</template>
          <template v-else>Waiting for your payment…</template>
        </p>
        <p v-if="payError" class="small err">{{ payError }}</p>
        <button class="btn ghost small" @click="paying = null">Close (you can pay later)</button>
      </template>
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
                v-if="p.status !== 'settled' && p.payment_method === 'onchain'"
                class="btn small primary"
                @click="openPay(p)"
              >Pay</button>
              <button
                v-else-if="p.status === 'pending'"
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
      <p v-if="purchases.some((p) => p.payment_method !== 'onchain')" class="dim small">
        Older Lightning purchases here are demo payments; "Confirm payment" completes them.
      </p>
    </section>
  </div>
</template>

<script setup lang="ts">
import type { BalanceOut, PackOut, PurchaseOut, RateOut } from "@xp/shared-types";
import { renderSVG } from "uqr";
import type { FeeRates, SendPlan } from "~/lib/wallet-core";

const api = useXpApi();
const w = useWallet();
const { naira } = usePrice();

// on-chain payment panel
const paying = ref<PurchaseOut | null>(null);
const payCard = ref<HTMLElement | null>(null);
const feeRates = ref<FeeRates | null>(null);
const password = ref("");
const sending = ref(false);
const payError = ref("");
const copied = ref(false);
let poller: ReturnType<typeof setInterval> | null = null;

const walletReady = computed(
  () => !!w.state.stored && paying.value?.network === w.net.name && w.spendable.value > 0,
);
const walletNote = computed(() => {
  if (!paying.value) return "";
  if (!w.state.stored) return "Tip: create a wallet under Wallet to pay in one tap.";
  if (paying.value.network !== w.net.name) return "Your XP wallet is on a different network, so pay from another wallet.";
  if (!w.spendable.value) return "Your XP wallet is empty. Top it up or pay from another wallet.";
  return "";
});
const quote = computed<SendPlan | null>(() => {
  if (!paying.value?.address || !feeRates.value || !walletReady.value) return null;
  try {
    return w.plan(paying.value.address, paying.value.amount_sats, feeRates.value.normal, false);
  } catch {
    return null;
  }
});
const quoteError = computed(() =>
  walletReady.value && feeRates.value && !quote.value ? "Not enough in your wallet for this amount plus the network fee." : "",
);
const qrSvg = computed(() =>
  paying.value?.bolt11 ? renderSVG(paying.value.bolt11, { border: 2, whiteColor: "#ffffff", blackColor: "#0b0e11" }) : "",
);

function stopPolling() {
  if (poller) clearInterval(poller);
  poller = null;
}

async function poll() {
  if (!paying.value) return stopPolling();
  try {
    const fresh = await api.getPurchase(paying.value.id);
    paying.value = fresh;
    if (fresh.status === "settled") {
      stopPolling();
      await refresh();
    }
  } catch {
    /* keep trying */
  }
}

async function openPay(p: PurchaseOut) {
  paying.value = p;
  password.value = "";
  payError.value = "";
  stopPolling();
  poller = setInterval(poll, 5000);
  nextTick(() => payCard.value?.scrollIntoView({ behavior: "smooth" }));
  if (w.state.stored && !w.state.lastSync) w.refresh();
  try {
    feeRates.value = await w.fees();
  } catch {
    feeRates.value = null;
  }
}

async function payFromWallet() {
  if (!quote.value) return;
  sending.value = true;
  payError.value = "";
  try {
    await w.send(quote.value, password.value);
    password.value = "";
    setTimeout(poll, 1500);
  } catch (e) {
    payError.value = e instanceof Error ? e.message : "Payment failed. Nothing was sent.";
  } finally {
    sending.value = false;
  }
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    /* ignore */
  }
  copied.value = true;
  setTimeout(() => (copied.value = false), 2000);
}

onBeforeUnmount(stopPolling);

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
    const created = await api.createPurchase({ pack_id: pack.pack_id, description: `XP pack ${pack.label}` });
    await refresh();
    if (created.payment_method === "onchain") await openPay(created);
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
    const art = (await api.createReceiptArtifact(p.id)) as { artifact_id?: string };
    await new Promise((r) => setTimeout(r, 1200));
    const token = sessionStorage.getItem("xp_session_token") ?? localStorage.getItem("xp_session_token");
    const res = await fetch(api.artifactDownloadUrl({ id: art.artifact_id } as any), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error("The receipt isn't ready yet. Try again in a moment.");
    const url = URL.createObjectURL(await res.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "xp-receipt.pdf";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
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
.pay { border-color: var(--orange); }
.paid { color: var(--green); font-weight: 600; }
.from-wallet { display: flex; flex-direction: column; gap: 8px; background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 12px; margin: 10px 0; }
.field { display: flex; flex-direction: column; gap: 6px; font-size: 14px; color: var(--text-dim); }
.field input { background: var(--bg-elev); color: var(--text); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; font-size: 16px; }
.other { margin: 10px 0; }
.other summary { cursor: pointer; color: var(--text-dim); }
.qr { width: 200px; height: 200px; margin: 10px 0; border-radius: 10px; overflow: hidden; background: #fff; }
.qr :deep(svg) { width: 100%; height: 100%; }
.addr { word-break: break-all; font-size: 13px; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 8px; margin-bottom: 8px; }
.status { display: flex; gap: 8px; align-items: center; color: var(--orange); margin: 10px 0; }
.err { color: var(--red); }
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
