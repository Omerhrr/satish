<template>
  <section v-if="ln.available" class="card ln">
    <!-- ======== card ======== -->
    <template v-if="view === 'card'">
      <div class="head">
        <h2>⚡ Lightning</h2>
        <span class="chip">{{ netLabel }}</span>
      </div>
      <p class="small dim">Instant payments with tiny fees, for everyday spending. Same 12 words as your savings wallet.</p>
      <details class="small dim safe">
        <summary>How safe is it?</summary>
        Your keys stay on this phone, like your savings wallet. Lightning here runs on Spark:
        payments are co-signed by a few independent companies (Lightspark, Breez, Flashnet),
        who can't move your money on their own, and you can always take it back to the Bitcoin
        network yourself. It's built for spending money; keep larger savings in your Bitcoin wallet.
      </details>

      <template v-if="!ln.st.open">
        <div v-if="ln.st.cachedBalance !== null" class="bal">
          {{ hide ? "••••" : ln.st.cachedBalance.toLocaleString() + " sats" }}
          <span class="small dim">last known</span>
        </div>
        <template v-if="!w.state.unlocked">
          <label class="field">Wallet password<input v-model="password" type="password" autocomplete="current-password" @keyup.enter="unlock" /></label>
          <p class="small dim">One password opens both your Bitcoin and Lightning wallets.</p>
          <p v-if="ln.st.error || error" class="err">{{ error || ln.st.error }}</p>
          <button class="btn primary" :disabled="busy || !password" @click="unlock">
            <span v-if="busy" class="spinner" /> Unlock Satish
          </button>
        </template>
        <template v-else>
          <p v-if="ln.st.opening" class="small dim"><span class="spinner" /> Opening Lightning… (the first time can take a minute)</p>
          <template v-else>
            <p v-if="ln.st.error" class="err">{{ ln.st.error }}</p>
            <button class="btn primary" @click="ln.open()">{{ ln.st.error ? "Try again" : "Open Lightning" }}</button>
          </template>
        </template>
      </template>

      <template v-else>
        <div class="bal">
          <template v-if="hide">••••</template>
          <template v-else>
            {{ (ln.st.balance ?? 0).toLocaleString() }} sats
            <span v-if="naira(ln.st.balance ?? 0)" class="small dim">· {{ naira(ln.st.balance ?? 0) }}</span>
          </template>
        </div>
        <div v-if="ln.st.address" class="small">Your Lightning address: <b class="mono">{{ ln.st.address }}</b></div>
        <div v-if="username" class="small">Satish users can pay you at <b>@{{ username }}</b> ⚡</div>
        <div class="row">
          <button class="btn primary" @click="startReceive">↓ Receive</button>
          <button class="btn primary" :disabled="!ln.st.balance" @click="startSend()">↑ Send</button>
          <button class="btn" @click="go('move')">⇅ Move</button>
        </div>
        <p v-if="ln.st.flash" class="small ok">{{ ln.st.flash }}</p>
        <p v-if="ln.st.error" class="err">{{ ln.st.error }}</p>

        <div v-for="d in ln.st.deposits" :key="d.txid + d.vout" class="deposit small">
          ⏳ Deposit of {{ d.amount.toLocaleString() }} sats on its way in. {{ d.problem }}
          <button v-if="d.problem && !d.problem.startsWith('Waiting')" class="btn small" :disabled="busy" @click="claim(d.txid, d.vout)">Bring it in now</button>
        </div>

        <h3 class="small sect">Recent</h3>
        <p v-if="!ln.st.payments.length" class="small dim">No Lightning payments yet.</p>
        <div v-for="p in ln.st.payments.slice(0, showAll ? 50 : 5)" :key="p.id" class="tx">
          <div>
            <b>{{ p.direction === "receive" ? "Received" : "Sent" }}</b>
            <span class="small dim"> · {{ kindLabel(p.kind) }}</span>
            <span v-if="p.description" class="small dim"> · {{ p.description }}</span>
            <div class="small" :class="p.status === 'completed' ? 'dim' : p.status === 'failed' ? 'err' : 'pending'">
              {{ p.status === "completed" ? fmt(p.time) : p.status === "failed" ? "Failed" : "In progress" }}
            </div>
          </div>
          <div :class="p.direction === 'receive' ? 'pos' : 'neg'">
            {{ hide ? "••••" : (p.direction === "receive" ? "+" : "-") + (p.amount + (p.direction === "send" ? p.fee : 0)).toLocaleString() + " sats" }}
          </div>
        </div>
        <button v-if="ln.st.payments.length > 5 && !showAll" class="btn ghost small" @click="showAll = true">Show more</button>
        <button v-if="ln.addressSupported && !ln.st.address && username" class="btn small" :disabled="busy" @click="getAddress">
          Get {{ username }}@{{ addressDomain }}
        </button>
      </template>
    </template>

    <!-- ======== receive ======== -->
    <template v-else-if="view === 'receive'">
      <h2>⚡ Receive with Lightning</h2>
      <div class="tabs">
        <button class="btn small" :class="{ primary: recvMode === 'invoice' }" @click="recvMode = 'invoice'; shown = ''">Invoice</button>
        <button class="btn small" :class="{ primary: recvMode === 'spark' }" @click="showSpark">Spark address</button>
        <button v-if="!ln.canMove" class="btn small" :class="{ primary: recvMode === 'deposit' }" @click="showDeposit">Bitcoin deposit</button>
      </div>
      <template v-if="recvMode === 'invoice' && !shown">
        <p class="sub">Create an invoice anyone can pay from any Lightning wallet.</p>
        <label class="field">Amount in sats (optional)<input v-model="amount" inputmode="numeric" placeholder="e.g. 2000" /></label>
        <span v-if="naira(Number(amount) || 0)" class="small dim">{{ naira(Number(amount)) }}</span>
        <label class="field">What's it for? (optional)<input v-model="desc" maxlength="80" placeholder="e.g. lunch" /></label>
        <p v-if="error" class="err">{{ error }}</p>
        <div class="stack">
          <button class="btn primary" :disabled="busy" @click="makeInvoice"><span v-if="busy" class="spinner" /> Create invoice</button>
        </div>
      </template>
      <template v-else-if="shown">
        <p class="sub">{{ shownHint }}</p>
        <div class="qr" v-html="qr" />
        <div class="addr mono">{{ shown }}</div>
        <div class="row">
          <button class="btn primary" @click="copy(shown)">{{ copied ? "Copied ✓" : "Copy" }}</button>
          <button v-if="recvMode === 'deposit' && faucet" class="btn" @click="openExternal(faucet)">Get free test coins</button>
        </div>
        <p v-if="recvMode === 'invoice'" class="small dim">This page updates by itself when it's paid. Invoices expire after an hour.</p>
      </template>
      <p v-else-if="busy" class="small dim"><span class="spinner" /> Getting it ready…</p>
      <p v-if="error && shown === ''" class="err">{{ error }}</p>
      <button class="btn ghost" style="margin-top: 12px" @click="go('card')">← Back</button>
    </template>

    <!-- ======== send ======== -->
    <template v-else-if="view === 'send'">
      <h2>⚡ Send with Lightning</h2>
      <label class="field">
        @username, invoice or Lightning address
        <div class="inline">
          <input v-model="target" autocapitalize="none" autocomplete="off" spellcheck="false" placeholder="@ada, lnbc… or name@wallet.com" @change="check" />
          <button v-if="canScan" class="btn small" type="button" @click="scan">Scan</button>
        </div>
      </label>
      <div v-if="userSuggestions.length" class="chips">
        <button v-for="c in userSuggestions" :key="c.id" type="button" class="chip-btn" @click="pickUser(c.username!)">
          @{{ c.username }}<template v-if="c.name !== '@' + c.username"> · {{ c.name }}</template>
        </button>
      </div>
      <p v-if="parsed" class="small ok">→ {{ parsedLine }}<span v-if="toUser" class="verified"> ✓ verified</span></p>
      <label v-if="toUser?.changed" class="check warn">
        <input v-model="acceptChange" type="checkbox" />
        <span>⚠️ @{{ toUser.username }} has a different wallet than last time. Only continue if they told you they changed wallets.</span>
      </label>
      <label v-if="parsed && needsAmount" class="field">
        Amount in sats
        <input v-model="amount" inputmode="numeric" :placeholder="rangeHint" />
        <span v-if="naira(Number(amount) || 0)" class="small dim">{{ naira(Number(amount)) }}</span>
      </label>
      <p class="small dim">Available: {{ (ln.st.balance ?? 0).toLocaleString() }} sats</p>
      <p v-if="error" class="err">{{ error }}</p>
      <div class="stack">
        <button class="btn primary" :disabled="busy || !target" @click="review"><span v-if="busy" class="spinner" /> Review</button>
        <button class="btn ghost" @click="go('card')">Cancel</button>
      </div>
    </template>

    <template v-else-if="view === 'review' && quote">
      <h2>Check before sending</h2>
      <div class="summary">
        <div><span>To</span><b :class="{ mono: !toUser }">{{ parsedLine }}<span v-if="toUser" class="verified"> ✓ verified</span></b></div>
        <div><span>Amount</span><b>{{ quote.amount.toLocaleString() }} sats<small v-if="naira(quote.amount)" class="ngn">{{ naira(quote.amount) }}</small></b></div>
        <div><span>Fee</span><b>{{ quote.fee.toLocaleString() }} sats</b></div>
        <div class="total"><span>Total</span><b>{{ (quote.amount + quote.fee).toLocaleString() }} sats</b></div>
      </div>
      <p class="small dim">Lightning payments are instant and can't be reversed.</p>
      <p v-if="error" class="err">{{ error }}</p>
      <div class="stack">
        <button class="btn primary" :disabled="busy" @click="confirmSend"><span v-if="busy" class="spinner" /> Send now</button>
        <button class="btn ghost" :disabled="busy" @click="go('send')">← Edit</button>
      </div>
    </template>

    <template v-else-if="view === 'sent'">
      <div class="center">
        <div class="big-icon">⚡</div>
        <h2>{{ sentPending ? "On its way" : "Sent" }}</h2>
        <p class="sub">{{ sentPending ? "Lightning is still finding a route. It usually finishes in seconds; check Recent." : "Delivered instantly." }}</p>
        <button class="btn primary" @click="go('card')">Done</button>
      </div>
    </template>

    <!-- ======== move ======== -->
    <template v-else-if="view === 'move'">
      <h2>⇅ Move money</h2>
      <template v-if="ln.canMove">
        <p class="sub">Keep savings in your Bitcoin wallet and spending money on Lightning.</p>
        <div class="stack">
          <button class="btn primary" :disabled="busy" @click="toLightning"><span v-if="busy" class="spinner" /> Savings → Lightning</button>
          <p class="small dim">Sends from your Bitcoin wallet to your Lightning wallet. It arrives after the network confirms it (usually under an hour), minus a small fee.</p>
          <button class="btn" :disabled="!ln.st.balance" @click="toSavings">Lightning → Savings</button>
          <p class="small dim">Sends your Lightning money back to your Bitcoin wallet, with a network fee shown before you confirm.</p>
        </div>
      </template>
      <template v-else>
        <p class="sub">
          In test mode, your Bitcoin wallet uses testnet4 and Lightning uses a separate test network,
          so money can't move between them. Use <b>Receive → Bitcoin deposit</b> to get free test coins
          for Lightning. On the real network, moving between the two takes one tap.
        </p>
      </template>
      <p v-if="error" class="err">{{ error }}</p>
      <button class="btn ghost" style="margin-top: 12px" @click="go('card')">← Back</button>
    </template>
  </section>
</template>

<script setup lang="ts">
import { renderSVG } from "uqr";
import type { PrepareSendPaymentResponse } from "@breeztech/breez-sdk-spark";
import { LightningError, type FeeQuote, type SendTarget } from "~/lib/lightning";
import { WrongPassword } from "~/lib/wallet-core";

const props = defineProps<{ hide: boolean; username: string | null }>();
const emit = defineEmits<{ (e: "pay-onchain", address: string): void }>();

const ln = useLightning();
const w = useWallet();
const { naira } = usePrice();

type View = "card" | "receive" | "send" | "review" | "sent" | "move";
const view = ref<View>("card");
const password = ref("");
const busy = ref(false);
const error = ref("");
const copied = ref(false);
const showAll = ref(false);
const amount = ref("");
const desc = ref("");
const recvMode = ref<"invoice" | "spark" | "deposit">("invoice");
const shown = ref("");
const shownHint = ref("");
const target = ref("");
const parsed = ref<SendTarget | null>(null);
const prep = ref<PrepareSendPaymentResponse | null>(null);
const quote = ref<FeeQuote | null>(null);
const sentPending = ref(false);
let idem = "";

const netLabel = computed(() => (ln.network === "mainnet" ? "Bitcoin" : "Test network"));
const addressDomain = "breez.tips";
const faucet = computed(() => (ln.network === "regtest" ? "https://app.lightspark.com/regtest-faucet" : ""));
const canScan = computed(() => !!(window as any).Telegram?.WebApp?.showScanQrPopup);
const qr = computed(() => (shown.value ? renderSVG(shown.value.toUpperCase().startsWith("LN") ? shown.value.toUpperCase() : shown.value, { border: 2, whiteColor: "#ffffff", blackColor: "#0b0e11" }) : ""));
const hide = computed(() => props.hide);

function go(v: View) {
  error.value = "";
  view.value = v;
  window.scrollTo?.({ top: 0 });
}

function fmt(t: number) {
  return t ? new Date(t * 1000).toLocaleString() : "";
}

function kindLabel(k: string) {
  return ({ lightning: "Lightning", spark: "Spark", deposit: "from Bitcoin", withdraw: "to Bitcoin" } as Record<string, string>)[k] ?? "";
}

function msg(e: unknown, fallback: string) {
  return e instanceof LightningError || e instanceof Error ? e.message : fallback;
}

async function unlock() {
  busy.value = true;
  error.value = "";
  try {
    await ln.unlockAll(password.value);
    password.value = "";
  } catch (e) {
    error.value = e instanceof WrongPassword ? "Wrong password." : msg(e, "Couldn't unlock.");
  } finally {
    busy.value = false;
  }
}

// Claimed a username after opening Lightning: let people pay it on Lightning too.
watch(
  () => w.state.handle?.username,
  (name) => {
    if (name && ln.st.open) void ln.publish();
  },
);

// Unlocked somewhere else (lock screen, a Bitcoin payment): open Lightning too.
onMounted(() => {
  if (w.state.unlocked && !ln.st.open) void ln.open();
});
watch(
  () => w.state.unlocked,
  (on) => {
    if (on && !ln.st.open) void ln.open();
  },
);

function startReceive() {
  amount.value = "";
  desc.value = "";
  shown.value = "";
  recvMode.value = "invoice";
  go("receive");
}

async function makeInvoice() {
  error.value = "";
  const a = amount.value ? Number(amount.value.replace(/[,\s]/g, "")) : undefined;
  busy.value = true;
  try {
    const r = await ln.invoice(a, desc.value);
    shown.value = r.request;
    shownHint.value = a ? `Invoice for ${a.toLocaleString()} sats${desc.value ? ` · ${desc.value}` : ""}` : "Invoice for any amount";
  } catch (e) {
    error.value = msg(e, "Couldn't create an invoice.");
  } finally {
    busy.value = false;
  }
}

async function showSpark() {
  recvMode.value = "spark";
  shown.value = "";
  busy.value = true;
  try {
    shown.value = await ln.sparkAddress();
    shownHint.value = "Your Spark address. Other Spark wallets send to it instantly and for free. It never changes.";
  } catch (e) {
    error.value = msg(e, "Couldn't get your Spark address.");
  } finally {
    busy.value = false;
  }
}

async function showDeposit() {
  recvMode.value = "deposit";
  shown.value = "";
  busy.value = true;
  try {
    shown.value = await ln.depositAddress();
    shownHint.value = "Bitcoin sent here is added to your Lightning balance after it confirms.";
  } catch (e) {
    error.value = msg(e, "Couldn't get a deposit address.");
  } finally {
    busy.value = false;
  }
}

const toUser = ref<{ username: string; address: string; identityPubkey: string; changed: boolean } | null>(null);
const acceptChange = ref(false);

// Saved Satish contacts as you type ("@ad" or a contact's name).
const userSuggestions = computed(() => {
  const q = target.value.trim().replace(/^@/, "").toLowerCase();
  if (toUser.value || q.length > 20 || /^(ln|sp)/.test(q) || q.includes("@")) return [];
  return w.state.contacts
    .filter((c) => c.username && (!q || c.username.includes(q) || c.name.toLowerCase().includes(q)))
    .slice(0, 6);
});

function pickUser(username: string) {
  target.value = "@" + username;
  void check();
}

function startSend(prefill = "") {
  target.value = prefill;
  amount.value = "";
  parsed.value = null;
  toUser.value = null;
  acceptChange.value = false;
  quote.value = null;
  go("send");
  if (prefill) void check();
}

const needsAmount = computed(() => {
  const p = parsed.value;
  if (!p) return false;
  return p.kind === "invoice" ? !p.amount : p.kind === "bitcoin" ? !p.amount : true;
});

const rangeHint = computed(() => {
  const p = parsed.value;
  return p && (p.kind === "lightningAddress" || p.kind === "lnurl") ? `${p.min.toLocaleString()} - ${p.max.toLocaleString()}` : "e.g. 1000";
});

const parsedLine = computed(() => {
  const p = parsed.value;
  if (!p) return "";
  if (p.kind === "invoice") return `Lightning invoice${p.amount ? ` for ${p.amount.toLocaleString()} sats` : ""}${p.description ? ` · ${p.description}` : ""}`;
  if (p.kind === "lightningAddress") return p.address;
  if (p.kind === "lnurl") return `Lightning payment to ${p.domain}`;
  if (toUser.value) return `@${toUser.value.username}`;
  if (p.kind === "spark") return `Spark address ${p.address.slice(0, 10)}…${p.address.slice(-6)}`;
  return `Bitcoin address ${p.address.slice(0, 10)}…${p.address.slice(-6)}`;
});

/** "@ada", or a saved contact's name that has a username. */
function usernameIn(text: string): string | null {
  const t = text.trim();
  if (/^@[a-z0-9_]{3,20}$/i.test(t)) return t.slice(1).toLowerCase();
  const c = w.state.contacts.find((x) => x.username && x.name.toLowerCase() === t.toLowerCase());
  return c?.username ?? null;
}

async function check() {
  error.value = "";
  parsed.value = null;
  toUser.value = null;
  if (!target.value.trim()) return;
  const name = usernameIn(target.value);
  try {
    if (name) {
      const u = await w.resolveUsernameLightning(name, ln.network);
      toUser.value = u;
      acceptChange.value = false;
      parsed.value = { kind: "spark", address: u.address };
      return;
    }
    parsed.value = await ln.parse(target.value);
  } catch (e) {
    error.value = msg(e, "That doesn't look like something Lightning can pay.");
  }
}

function scan() {
  const tg = (window as any).Telegram?.WebApp;
  tg?.showScanQrPopup?.({ text: "Scan a Lightning invoice or address" }, (text: string) => {
    target.value = text;
    void check();
    return true;
  });
}

async function review() {
  error.value = "";
  if (!parsed.value) await check();
  const p = parsed.value;
  if (!p) return;
  if (toUser.value?.changed && !acceptChange.value) {
    error.value = "Check with them before paying: their wallet key changed.";
    return;
  }
  let a: number | undefined;
  if (needsAmount.value) {
    a = Number(amount.value.replace(/[,\s]/g, ""));
    if (!Number.isInteger(a) || a <= 0) {
      error.value = "Enter the amount in whole sats.";
      return;
    }
    if ((p.kind === "lightningAddress" || p.kind === "lnurl") && (a < p.min || a > p.max)) {
      error.value = `They accept between ${p.min.toLocaleString()} and ${p.max.toLocaleString()} sats.`;
      return;
    }
  }
  busy.value = true;
  try {
    const r = await ln.prepare(toUser.value ? toUser.value.address : target.value, a);
    if (r.quote.amount + r.quote.fee > (ln.st.balance ?? 0)) {
      error.value = "You don't have enough in Lightning for this amount plus the fee.";
      return;
    }
    prep.value = r.prep;
    quote.value = r.quote;
    idem = crypto.randomUUID();
    go("review");
  } catch (e) {
    error.value = msg(e, "Couldn't prepare this payment.");
  } finally {
    busy.value = false;
  }
}

async function confirmSend() {
  if (!prep.value) return;
  busy.value = true;
  error.value = "";
  try {
    const p = await ln.send(prep.value, idem);
    sentPending.value = p.status === "pending";
    if (toUser.value) w.rememberUsername(toUser.value.username, toUser.value.identityPubkey);
    go("sent");
  } catch (e) {
    error.value = msg(e, "The payment failed. Nothing was sent.");
  } finally {
    busy.value = false;
  }
}

async function claim(txid: string, vout: number) {
  busy.value = true;
  try {
    await ln.claimDeposit(txid, vout);
  } catch (e) {
    ln.st.error = msg(e, "Couldn't bring the deposit in yet. Try again later.");
  } finally {
    busy.value = false;
  }
}

async function getAddress() {
  if (!props.username) return;
  busy.value = true;
  try {
    await ln.registerAddress(props.username);
    ln.flash(`Your Lightning address is ${ln.st.address}`);
  } catch (e) {
    ln.st.error = msg(e, "Couldn't set up a Lightning address.");
  } finally {
    busy.value = false;
  }
}

async function toLightning() {
  busy.value = true;
  error.value = "";
  try {
    const address = await ln.depositAddress();
    emit("pay-onchain", address);
  } catch (e) {
    error.value = msg(e, "Couldn't get a deposit address.");
  } finally {
    busy.value = false;
  }
}

function toSavings() {
  const to = w.receiveAddress.value;
  if (!to) {
    error.value = "Refresh your Bitcoin wallet first.";
    return;
  }
  startSend(to);
}

function openExternal(url: string) {
  const tg = (window as any).Telegram?.WebApp;
  if (tg?.openLink) tg.openLink(url);
  else window.open(url, "_blank", "noopener");
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

// When an invoice we showed gets paid, go back to the card with the news.
let latestWhenShown: string | undefined;
watch(shown, () => (latestWhenShown = ln.st.payments[0]?.id));
watch(
  () => ln.st.payments[0]?.id,
  (id) => {
    if (id && id !== latestWhenShown && view.value === "receive" && shown.value && ln.st.payments[0].direction === "receive") go("card");
  },
);

defineExpose({ startSend });
</script>

<style scoped>
.ln .head { display: flex; justify-content: space-between; align-items: center; }
.chip { font-size: 12px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border); color: var(--text-dim); }
.bal { font-size: 24px; font-weight: 700; margin: 8px 0; }
.row { display: flex; gap: 8px; margin: 8px 0; flex-wrap: wrap; }
.row .btn { flex: 1; min-width: 0; }
.stack { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; }
.field { display: flex; flex-direction: column; gap: 6px; margin-top: 12px; font-size: 14px; color: var(--text-dim); }
.field input { width: 100%; background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; font-size: 16px; font-family: inherit; }
.inline { display: flex; gap: 8px; }
.inline input { flex: 1; min-width: 0; }
.tabs { display: flex; gap: 6px; flex-wrap: wrap; margin: 6px 0 4px; }
.qr { width: 220px; height: 220px; border-radius: 12px; overflow: hidden; background: #fff; margin: 10px auto; }
.qr :deep(svg) { width: 100%; height: 100%; }
.addr { word-break: break-all; font-size: 12px; background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 10px; }
.tx { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--border); }
.tx:last-of-type { border-bottom: 0; }
.pos { color: var(--green); font-weight: 600; }
.neg { font-weight: 600; }
.pending { color: var(--orange); }
.ok { color: var(--green); }
.err { color: var(--red); font-size: 14px; margin-top: 8px; }
.sect { margin: 14px 0 4px; color: var(--text-dim); }
.summary { display: flex; flex-direction: column; gap: 10px; margin: 12px 0; }
.summary div { display: flex; justify-content: space-between; gap: 12px; }
.summary span { color: var(--text-dim); }
.summary b { text-align: right; word-break: break-all; }
.summary .total { border-top: 1px solid var(--border); padding-top: 10px; }
.ngn { display: block; font-weight: 400; font-size: 12px; color: var(--text-dim); }
.safe { margin: 4px 0 6px; line-height: 1.5; }
.safe summary { cursor: pointer; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.chip-btn { border: 1px solid var(--border); background: var(--bg); color: var(--text); border-radius: 999px; padding: 5px 12px; font: inherit; font-size: 13px; cursor: pointer; }
.verified { color: var(--green); font-size: 12px; font-weight: 600; }
.check { display: flex; gap: 8px; align-items: center; margin-top: 10px; font-size: 14px; }
.warn span { color: var(--orange); }
.deposit { background: var(--orange-soft); border-radius: 10px; padding: 8px 12px; margin: 6px 0; }
.center { text-align: center; display: flex; flex-direction: column; align-items: center; gap: 10px; }
.big-icon { font-size: 44px; }
</style>
