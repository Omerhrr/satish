<template>
  <div>
    <header>
      <h1 class="page-title">{{ t("cr.title") }}</h1>
      <p class="page-sub">
        TK pays for Satish AI. It's taken automatically as you use it. You buy it with
        bitcoin or Lightning; it can't be sent to anyone or turned back into sats.
      </p>
    </header>

    <section class="card">
      <div class="head-row">
        <h2>{{ t("cr.yours") }}</h2>
        <NuxtLink class="small" to="/tk">TK history</NuxtLink>
      </div>
      <div class="balance-big">{{ balance ? balance.balance_xp.toLocaleString() + " TK" : "…" }}</div>
      <p v-if="rate" class="dim small">1 sat buys {{ rate.xp_per_sat }} TK{{ rate.can_change ? " (this rate can change)" : "" }}.</p>
    </section>

    <section class="card">
      <h2>{{ t("cr.buy") }}</h2>
      <label class="field">
        {{ t("cr.howMuch") }}
        <input v-model.number="tkWanted" type="number" inputmode="numeric" :min="minTk" step="100" />
      </label>
      <div class="quick">
        <button v-for="q in quick" :key="q" type="button" class="chipbtn" :class="{ on: tkWanted === q }" @click="tkWanted = q">{{ q.toLocaleString() }}</button>
      </div>
      <p class="dim small">
        <template v-if="tkValid">
          Costs <b>{{ satsFor.toLocaleString() }} sats</b><template v-if="naira(satsFor)"> ({{ naira(satsFor) }})</template>
          <template v-if="tkCredited !== tkWanted"> · you'll get {{ tkCredited.toLocaleString() }} TK</template>
        </template>
        <template v-else>The minimum is {{ minTk.toLocaleString() }} TK ({{ Math.ceil(minTk / perSat).toLocaleString() }} sats).</template>
      </p>

      <div v-if="methods.length" class="seg" role="radiogroup" aria-label="Pay with">
        <button v-for="m in methods" :key="m" type="button" role="radio" :aria-checked="method === m" :class="{ on: method === m }" @click="method = m">
          {{ m === "lightning" ? "⚡ Lightning" : "₿ Bitcoin" }}
        </button>
      </div>
      <p class="dim small">{{ method === "lightning" ? "Instant, tiny fees." : "On-chain: takes a few minutes, network fee applies." }}</p>
      <button class="btn primary" :disabled="!tkValid || buying || !methods.length" @click="buy">
        <span v-if="buying" class="spinner" /> {{ t("cr.continue") }}
      </button>
      <p v-if="!methods.length && rate" class="small err">Payments aren't set up yet.</p>
      <p v-if="error" class="notice small">{{ error }}</p>
      <p v-if="receiptNote" class="small" style="color: var(--green)">{{ receiptNote }}</p>
    </section>

    <section v-if="paying" ref="payCard" class="card pay">
      <h2>Pay {{ paying.amount_sats.toLocaleString() }} sats <span v-if="naira(paying.amount_sats)" class="dim small">{{ naira(paying.amount_sats) }}</span></h2>
      <template v-if="paying.status === 'settled'">
        <p class="paid">✅ Paid. +{{ paying.xp_amount.toLocaleString() }} TK added to your balance.</p>
        <button class="btn" @click="paying = null">Done</button>
      </template>
      <template v-else-if="paying.status === 'expired' && paying.payment_method === 'lightning'">
        <p class="small err">This invoice expired. Start a new purchase.</p>
        <button class="btn" @click="paying = null">Close</button>
      </template>
      <template v-else>
        <p class="sub">
          You'll get <b>{{ paying.xp_amount.toLocaleString() }} TK</b> as soon as the payment arrives.
          <template v-if="paying.network === 'testnet'"> (Test network: use test coins.)</template>
        </p>
        <p v-if="paying.payee_username" class="small payee">
          Paying to <b>@{{ paying.payee_username }}</b>
          <button class="linkbtn" @click="copy('@' + paying.payee_username, 'user')">{{ copiedWhat === "user" ? "Copied ✓" : "Copy" }}</button>
        </p>

        <div class="qr" v-html="qrSvg" />
        <div class="addr mono">{{ payTarget }}</div>
        <button class="btn small" @click="copy(payTarget, 'target')">
          {{ copiedWhat === "target" ? "Copied ✓" : paying.payment_method === "lightning" ? "Copy invoice" : "Copy address" }}
        </button>
        <p class="small dim">
          <template v-if="paying.payment_method === 'lightning'">Scan or paste this invoice in any Lightning wallet. It's for this purchase only, so we can match your payment.</template>
          <template v-else>Send exactly {{ paying.amount_sats.toLocaleString() }} sats or more to this address.</template>
        </p>

        <!-- Pay with the in-app wallet -->
        <div class="from-wallet">
          <b>Pay with my Satish wallet</b>
          <template v-if="!w.state.stored">
            <span class="small dim">You don't have a Satish wallet yet.</span>
            <NuxtLink class="btn small" to="/">Set up my wallet</NuxtLink>
          </template>
          <template v-else-if="paying.payment_method === 'lightning'">
            <template v-if="!ln.st.open">
              <label class="field">Wallet password<input v-model="password" type="password" autocomplete="current-password" /></label>
              <button class="btn primary" :disabled="sending || !password" @click="openLightning">
                <span v-if="sending" class="spinner" /> Unlock wallet
              </button>
            </template>
            <template v-else>
              <span class="small dim">Lightning balance: {{ (ln.st.balance ?? 0).toLocaleString() }} sats</span>
              <span v-if="lnQuote" class="small dim">Fee {{ lnQuote.fee.toLocaleString() }} sats · total {{ (lnQuote.amount + lnQuote.fee).toLocaleString() }} sats</span>
              <button class="btn primary" :disabled="sending || !lnQuote || lnShort" @click="payLightning">
                <span v-if="sending" class="spinner" /> Pay now
              </button>
              <span v-if="lnShort" class="small err">Not enough in your Lightning wallet. Top it up, or pay with another wallet.</span>
            </template>
          </template>
          <template v-else-if="walletReady">
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
          </template>
          <span v-else class="small dim">{{ walletNote }}</span>
        </div>

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
          <tr><th>Sats</th><th>TK</th><th>Status</th><th>Receipt</th></tr>
        </thead>
        <tbody>
          <tr v-for="p in purchases" :key="p.id">
            <td>{{ p.amount_sats.toLocaleString() }}</td>
            <td>+{{ p.xp_amount.toLocaleString() }}</td>
            <td>
              <span class="chip" :class="p.status">{{ human(p.status) }}</span>
              <button
                v-if="p.status === 'pending' || (p.status === 'expired' && p.payment_method === 'onchain')"
                class="btn small primary"
                @click="openPay(p)"
              >Pay</button>
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
    </section>
  </div>
</template>

<script setup lang="ts">
import type { BalanceOut, PurchaseOut, RateOut } from "@xp/shared-types";
import { renderSVG } from "uqr";
import type { FeeRates, SendPlan } from "~/lib/wallet-core";

const api = useXpApi();
const { t } = useI18n();
const w = useWallet();
const ln = useLightning();
const { naira } = usePrice();

// on-chain payment panel
const paying = ref<PurchaseOut | null>(null);
const payCard = ref<HTMLElement | null>(null);
const feeRates = ref<FeeRates | null>(null);
const password = ref("");
const sending = ref(false);
const payError = ref("");
const copiedWhat = ref("");
let poller: ReturnType<typeof setInterval> | null = null;

const walletReady = computed(
  () => !!w.state.stored && paying.value?.network === w.net.name && w.spendable.value > 0,
);
const walletNote = computed(() => {
  if (!paying.value) return "";
  if (!w.state.stored) return "Tip: create your Satish wallet to pay in one tap.";
  if (paying.value.network !== w.net.name) return "Your Satish wallet is on a different network, so pay from another wallet.";
  if (!w.spendable.value) return "Your Satish wallet is empty. Top it up or pay from another wallet.";
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
const payTarget = computed(() => {
  const p = paying.value;
  if (!p) return "";
  return p.payment_method === "lightning" ? p.bolt11 || "" : p.address || "";
});
const qrSvg = computed(() => {
  const p = paying.value;
  if (!p?.bolt11) return "";
  // Lightning QR codes scan best as upper-case "LIGHTNING:" URIs.
  const data = p.payment_method === "lightning" ? `LIGHTNING:${p.bolt11.toUpperCase()}` : p.bolt11;
  return renderSVG(data, { border: 2, whiteColor: "#ffffff", blackColor: "#0b0e11" });
});

// Lightning: pay from the in-app wallet
const lnPrep = shallowRef<unknown>(null);
const lnQuote = ref<{ amount: number; fee: number } | null>(null);
const lnShort = computed(() => !!lnQuote.value && lnQuote.value.amount + lnQuote.value.fee > (ln.st.balance ?? 0));
async function prepareLightning() {
  lnQuote.value = null;
  lnPrep.value = null;
  if (!paying.value?.bolt11 || !ln.st.open) return;
  try {
    const r = await ln.prepare(paying.value.bolt11);
    lnPrep.value = r.prep;
    lnQuote.value = r.quote;
  } catch (e) {
    payError.value = e instanceof Error ? e.message : "Couldn't read the invoice.";
  }
}
async function openLightning() {
  sending.value = true;
  payError.value = "";
  try {
    await ln.unlockAll(password.value);
    password.value = "";
    await prepareLightning();
  } catch (e) {
    payError.value = e instanceof Error ? e.message : "Wrong password.";
  } finally {
    sending.value = false;
  }
}
async function payLightning() {
  if (!lnPrep.value) return;
  sending.value = true;
  payError.value = "";
  try {
    await ln.send(lnPrep.value as never, crypto.randomUUID());
    setTimeout(poll, 1200);
  } catch (e) {
    payError.value = e instanceof Error ? e.message : "The payment failed. Nothing was sent.";
  } finally {
    sending.value = false;
  }
}

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
  poller = setInterval(poll, p.payment_method === "lightning" ? 3000 : 5000);
  if (p.payment_method === "lightning") {
    nextTick(() => payCard.value?.scrollIntoView({ behavior: "smooth" }));
    if (!ln.st.open && w.state.unlocked) {
      try {
        await ln.open();
      } catch {
        /* user can unlock with the password */
      }
    }
    await prepareLightning();
    return;
  }
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

async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    /* ignore */
  }
  copiedWhat.value = what;
  setTimeout(() => (copiedWhat.value = ""), 2000);
}

onBeforeUnmount(stopPolling);

const rate = ref<RateOut | null>(null);
const balance = ref<BalanceOut | null>(null);
const purchases = ref<PurchaseOut[]>([]);
const buying = ref(false);
const tkWanted = ref(500);
const method = ref<"lightning" | "onchain">("lightning");
const perSat = computed(() => rate.value?.xp_per_sat || 5);
const minTk = computed(() => rate.value?.min_tk || 500);
const methods = computed(() => (rate.value?.methods || []) as ("lightning" | "onchain")[]);
const quick = computed(() => [minTk.value, 1000, 2500, 5000, 10000].filter((v, i, a) => a.indexOf(v) === i && v >= minTk.value));
const tkValid = computed(() => Number.isFinite(tkWanted.value) && tkWanted.value >= minTk.value && tkWanted.value <= (rate.value?.max_tk || 5e7));
const satsFor = computed(() => Math.ceil((tkWanted.value || 0) / perSat.value));
const tkCredited = computed(() => satsFor.value * perSat.value);
watch(methods, (m) => {
  if (m.length && !m.includes(method.value)) method.value = m[0]!;
});
const settling = ref<string | null>(null);
const receipting = ref<string | null>(null);
const error = ref<string | null>(null);

async function refresh() {
  try {
    const [r, b, purchasesList] = await Promise.all([api.rate(), api.balance(), api.listPurchases()]);
    rate.value = r;
    balance.value = b;
    purchases.value = purchasesList;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "failed to load billing data";
  }
}

async function buy() {
  buying.value = true;
  error.value = null;
  try {
    const created = await api.createPurchase({ tk_amount: tkWanted.value, method: method.value, description: "TK purchase" });
    await refresh();
    await openPay(created);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "purchase failed";
  } finally {
    buying.value = false;
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

const receiptNote = ref<string | null>(null);
async function receipt(p: PurchaseOut) {
  receipting.value = p.id;
  error.value = null;
  receiptNote.value = null;
  try {
    if ((window as any).Telegram?.WebApp?.initData) {
      // Telegram's in-app browser can't save files: the bot sends the PDF to the chat instead.
      await api.sendReceiptToTelegram(p.id);
      receiptNote.value = "🧾 Receipt sent to your Telegram chat with Satish.";
      return;
    }
    const token = sessionStorage.getItem("xp_session_token") ?? localStorage.getItem("xp_session_token");
    const res = await fetch(api.receiptUrl(p.id), { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!res.ok) {
      let msg = "Couldn't make the receipt. Try again in a moment.";
      try { msg = (await res.json()).detail || msg; } catch { /* not json */ }
      throw new Error(msg);
    }
    const url = URL.createObjectURL(await res.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `satish-receipt-${p.id.slice(0, 8)}.pdf`;
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
.head-row { display: flex; justify-content: space-between; align-items: baseline; }
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
.quick, .seg { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; }
.chipbtn, .seg button { padding: 7px 14px; border-radius: 999px; border: 1px solid var(--border); background: transparent; color: inherit; font-size: 14px; }
.chipbtn.on, .seg button.on { background: var(--orange); border-color: transparent; color: var(--on-accent); font-weight: 600; }
.payee { display: flex; gap: 8px; align-items: center; }
.linkbtn { background: none; border: 0; color: var(--orange); font-size: 13px; padding: 0; }
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
