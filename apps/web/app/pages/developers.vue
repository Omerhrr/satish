<template>
  <div>
    <h1 class="page-title">Satish for developers</h1>
    <p class="page-sub">
      Accept bitcoin on your website, app or bot. Payments go straight to your own Satish wallet
      (your @username); Satish never holds your money.
    </p>

    <p v-if="!username" class="notice small">
      Pick a Satish username first (Wallet &gt; Home &gt; Pick a username). Payments to your API are paid to it.
    </p>

    <!-- 1. Keys -->
    <section class="card">
      <h2>1. API keys</h2>
      <p class="small dim">Use a key from your server only. It can create and read payment requests; it can't move money or see your balance.</p>
      <ul class="rows">
        <li v-for="k in keys" :key="k.id">
          <div>
            <b>{{ k.name }}</b> <span class="chip">{{ k.network === "mainnet" ? "live" : "test" }}</span>
            <div class="small dim mono">{{ k.prefix }}… · {{ k.last_used_at ? `used ${new Date(k.last_used_at).toLocaleString()}` : "never used" }}</div>
          </div>
          <button class="btn small ghost" @click="revokeKey(k.id)">Revoke</button>
        </li>
      </ul>
      <form class="row" @submit.prevent="createKey">
        <input v-model="keyName" maxlength="60" placeholder="Key name, e.g. My shop" aria-label="Key name" />
        <select v-model="keyNet" aria-label="Network">
          <option value="testnet">Test (test coins)</option>
          <option value="mainnet">Live (real bitcoin)</option>
        </select>
        <button class="btn small primary" :disabled="!keyName.trim()">Create key</button>
      </form>
      <div v-if="newSecret" class="secret">
        <b>Copy your key now. You won't see it again.</b>
        <div class="mono addr">{{ newSecret }}</div>
        <button class="btn small" @click="copy(newSecret, 'key')">{{ copied === "key" ? "Copied ✓" : "Copy key" }}</button>
      </div>
    </section>

    <!-- 2. Create a payment request -->
    <section class="card">
      <h2>2. Create a payment request</h2>
      <p class="small dim">From your server, with your key. Amounts in sats, or any currency (converted at today's rate).</p>
      <pre class="code">{{ curlCreate }}</pre>
      <button class="btn small" @click="copy(curlCreate, 'curl')">{{ copied === "curl" ? "Copied ✓" : "Copy" }}</button>
      <p class="small dim">The answer has <code>pay_url</code> (a page anyone can pay from any wallet, Lightning or Bitcoin), <code>telegram_url</code> (opens Satish in Telegram), <code>lightning_invoice</code>, <code>bitcoin_uri</code> (a QR code that works in both kinds of wallet) and <code>status</code>.</p>
      <p class="small dim"><b>Lightning:</b> payers pay an invoice from Satish's Lightning wallet; Satish confirms it at once (your webhook fires) and forwards the sats to your Satish Lightning wallet within seconds. Open Lightning once in your wallet so it can be found. Send <code>"methods": ["onchain"]</code> for Bitcoin only.</p>

      <h3 class="small">Try it now</h3>
      <form class="row" @submit.prevent="tryCreate">
        <input v-model="tryAmount" inputmode="decimal" placeholder="Amount" aria-label="Amount" />
        <select v-model="tryCur" aria-label="Currency">
          <option value="SAT">sats</option>
          <option value="NGN">NGN</option>
          <option value="USD">USD</option>
        </select>
        <input v-model="tryNote" maxlength="140" placeholder="Note, e.g. Order 42" aria-label="Note" />
        <button class="btn small primary" :disabled="!username || !tryAmount">Create</button>
      </form>
      <p v-if="tryError" class="small err">{{ tryError }}</p>
      <div v-if="tried" class="secret">
        <b>{{ tried.amount_sats?.toLocaleString() }} sats · {{ tried.status }} · {{ (tried.methods || ["onchain"]).join(" + ") }}</b>
        <span v-if="tried.warning" class="small err">{{ tried.warning }}</span>
        <a class="small" :href="tried.pay_url" target="_blank" rel="noopener">{{ tried.pay_url }}</a>
      </div>
    </section>

    <!-- 3. Button -->
    <section class="card">
      <h2>3. Add a "Pay with Satish" button</h2>
      <p class="small dim">Put the <code>pay_url</code> from step 2 on your page. No script needed.</p>
      <div class="preview"><a class="satish-btn" :href="tried?.pay_url || '#'" target="_blank" rel="noopener">₿ Pay with Satish</a></div>
      <pre class="code">{{ buttonHtml }}</pre>
      <button class="btn small" @click="copy(buttonHtml, 'btn')">{{ copied === "btn" ? "Copied ✓" : "Copy" }}</button>
    </section>

    <!-- 4. Webhooks -->
    <section class="card">
      <h2>4. Get told when you're paid (webhooks)</h2>
      <p class="small dim">Satish sends <code>request.paid</code> to your https address, signed with your webhook secret. Failed deliveries are retried for about 7 hours.</p>
      <div v-for="h in hooks" :key="h.id" class="hook">
        <div class="mono small">{{ h.url }}</div>
        <div class="small dim">Secret: <span class="mono">{{ shown[h.id] ? h.secret : "whsec_••••••••" }}</span>
          <button class="linkbtn" @click="shown[h.id] = !shown[h.id]">{{ shown[h.id] ? "Hide" : "Show" }}</button>
          <button class="linkbtn" @click="copy(h.secret, h.id)">{{ copied === h.id ? "Copied ✓" : "Copy" }}</button>
        </div>
        <div class="acts">
          <button class="btn small" @click="testHook(h.id)">Send a test</button>
          <button class="btn small" @click="loadDeliveries(h.id)">Deliveries</button>
          <button class="btn small ghost" @click="deleteHook(h.id)">Remove</button>
        </div>
        <p v-if="testResult[h.id]" class="small" :class="testResult[h.id]!.ok ? 'ok' : 'err'">{{ testResult[h.id]!.text }}</p>
        <ul v-if="deliveries[h.id]" class="rows small">
          <li v-for="d in deliveries[h.id]" :key="d.id">
            <span>{{ d.event }} · {{ new Date(d.created_at).toLocaleString() }}</span>
            <span :class="d.status === 'delivered' ? 'ok' : d.status === 'failed' ? 'err' : 'dim'">{{ d.status }}{{ d.last_status_code ? ` (${d.last_status_code})` : "" }}</span>
          </li>
          <li v-if="!deliveries[h.id]!.length" class="dim">Nothing sent yet.</li>
        </ul>
      </div>
      <form class="row" @submit.prevent="createHook">
        <input v-model="hookUrl" placeholder="https://your-site.com/satish-webhook" aria-label="Webhook URL" />
        <button class="btn small primary" :disabled="!hookUrl.startsWith('https://')">Add webhook</button>
      </form>
      <p v-if="hookError" class="small err">{{ hookError }}</p>
      <h3 class="small">Check the signature (Node.js)</h3>
      <pre class="code">{{ verifyJs }}</pre>
      <button class="btn small" @click="copy(verifyJs, 'js')">{{ copied === "js" ? "Copied ✓" : "Copy" }}</button>
    </section>

    <section class="card">
      <h2>Reference</h2>
      <table class="ref">
        <tr><th>Call</th><th>What it does</th></tr>
        <tr><td class="mono">POST /api/v1/dev/payment-requests</td><td><code>amount_sats</code> or <code>amount</code> + <code>currency</code>, <code>note</code>, <code>metadata</code> (yours, returned in webhooks), <code>redirect_url</code> (a "Back to the shop" button after paying)</td></tr>
        <tr><td class="mono">GET /api/v1/dev/payment-requests/{id}</td><td>Current status: <code>open</code>, <code>paid</code> or <code>cancelled</code>; <code>paid_sats</code>; <code>paid_via</code> (<code>lightning</code> or <code>onchain</code>); for Lightning, <code>forward_status</code> (<code>pending</code>, <code>sent</code>)</td></tr>
        <tr><td class="mono">GET /api/v1/dev/payment-requests</td><td>Your latest requests (<code>?status=paid</code>)</td></tr>
        <tr><td class="mono">POST …/{id}/cancel</td><td>Stop accepting a request</td></tr>
      </table>
      <p class="small dim">Test keys (<code>sk_test_</code>) work on the test network with free test coins; live keys (<code>sk_live_</code>) use real bitcoin. Payments count once the network sees them.</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import type { DevHook, DevKey } from "@xp/api-client";

const api = useXpApi();
const w = useWallet();
const config = useRuntimeConfig();
const base = computed(() => {
  const b = String(config.public.apiBase || "");
  return b.startsWith("http") ? b.replace(/\/$/, "") : location.origin;
});
const username = computed(() => w.state.handle?.username ?? "");

const keys = ref<DevKey[]>([]);
const keyName = ref("");
const keyNet = ref(config.public.bitcoinNetwork === "mainnet" ? "mainnet" : "testnet");
const newSecret = ref("");
const hooks = ref<DevHook[]>([]);
const hookUrl = ref("");
const hookError = ref("");
const shown = reactive<Record<string, boolean>>({});
const testResult = reactive<Record<string, { ok: boolean; text: string }>>({});
const deliveries = reactive<Record<string, any[]>>({});
const copied = ref("");
const tryAmount = ref("5000");
const tryCur = ref("SAT");
const tryNote = ref("Order 42");
const tried = ref<Record<string, any> | null>(null);
const tryError = ref("");

async function load() {
  try {
    [keys.value, hooks.value] = await Promise.all([api.devKeys(), api.devHooks()]);
  } catch {
    /* signed out */
  }
}
async function createKey() {
  const k = await api.devCreateKey(keyName.value.trim(), keyNet.value);
  newSecret.value = k.secret || "";
  keyName.value = "";
  await load();
}
async function revokeKey(id: string) {
  if (!window.confirm("Revoke this key? Anything using it stops working.")) return;
  await api.devRevokeKey(id);
  await load();
}
async function createHook() {
  hookError.value = "";
  try {
    await api.devCreateHook(hookUrl.value.trim());
    hookUrl.value = "";
    await load();
  } catch (e) {
    hookError.value = e instanceof Error ? e.message : "Couldn't add it.";
  }
}
async function deleteHook(id: string) {
  await api.devDeleteHook(id);
  await load();
}
async function testHook(id: string) {
  testResult[id] = { ok: false, text: "Sending…" };
  try {
    const r = await api.devTestHook(id);
    testResult[id] = r.delivered
      ? { ok: true, text: `Delivered (HTTP ${r.status_code}).` }
      : { ok: false, text: `Not delivered: ${r.error || "no answer"}. We'll retry.` };
  } catch (e) {
    testResult[id] = { ok: false, text: e instanceof Error ? e.message : "Failed." };
  }
}
async function loadDeliveries(id: string) {
  deliveries[id] = await api.devDeliveries(id);
}
async function tryCreate() {
  tryError.value = "";
  const n = Number(tryAmount.value.replace(/[,\s]/g, ""));
  try {
    tried.value = await api.devCreatePaymentRequest(
      tryCur.value === "SAT" ? { amount_sats: n, note: tryNote.value } : { amount: n, currency: tryCur.value, note: tryNote.value },
    );
  } catch (e) {
    tryError.value = e instanceof Error ? e.message : "Couldn't create it.";
  }
}
async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    /* ignore */
  }
  copied.value = what;
  setTimeout(() => (copied.value = ""), 2000);
}

const curlCreate = computed(
  () => `curl -X POST ${base.value}/api/v1/dev/payment-requests \\
  -H "Authorization: Bearer ${newSecret.value || "sk_test_..."}" \\
  -H "Content-Type: application/json" \\
  -d '{"amount": 5000, "currency": "NGN", "note": "Order 42",
       "metadata": {"order_id": "42"},
       "redirect_url": "https://your-shop.com/thanks"}'`,
);
const buttonHtml = computed(
  () => `<a href="${tried.value?.pay_url || "PAY_URL_FROM_STEP_2"}"
   style="display:inline-block;padding:12px 20px;border-radius:999px;
          background:#f7931a;color:#0b0e11;font:600 16px system-ui;text-decoration:none">
  ₿ Pay with Satish
</a>`,
);
const verifyJs = `import crypto from "node:crypto";

// In your webhook route, with the RAW request body (a string or Buffer):
function isFromSatish(rawBody, signatureHeader, secret) {
  const parts = Object.fromEntries(signatureHeader.split(",").map((p) => p.split("=")));
  if (Math.abs(Date.now() / 1000 - Number(parts.t)) > 300) return false; // older than 5 min
  const expected = crypto.createHmac("sha256", secret).update(\`\${parts.t}.\${rawBody}\`).digest("hex");
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(parts.v1 || ""));
}

// const ok = isFromSatish(req.rawBody, req.headers["satish-signature"], process.env.SATISH_WEBHOOK_SECRET);
// Then use JSON.parse(rawBody).data: { id, status: "paid", amount_sats, paid_sats, metadata }.
// The same Satish-Delivery header can arrive twice: handle each id once.`;

onMounted(() => {
  void load();
  if (w.state.stored && !w.state.handle) void w.loadHandle();
});
</script>

<style scoped>
.rows { list-style: none; padding: 0; margin: 8px 0; }
.rows li { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--border); }
.row { display: flex; gap: 6px; flex-wrap: wrap; margin: 10px 0; }
.row input { flex: 1; min-width: 120px; padding: 8px 10px; border-radius: 10px; border: 1px solid var(--border); background: var(--bg); color: var(--text); }
.row select { padding: 8px; border-radius: 10px; border: 1px solid var(--border); background: var(--bg-elev); color: var(--text); }
.secret { display: flex; flex-direction: column; gap: 6px; padding: 10px; border: 1px dashed var(--orange); border-radius: 10px; margin-top: 8px; }
.addr { word-break: break-all; font-size: 13px; }
.mono { font-family: ui-monospace, monospace; }
.code { background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 10px; font-size: 12px; overflow-x: auto; white-space: pre; }
.chip { font-size: 11px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--border); }
.hook { padding: 10px 0; border-bottom: 1px solid var(--border); }
.acts { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
.linkbtn { background: none; border: 0; color: var(--orange); font-size: 12px; cursor: pointer; }
.ok { color: var(--green); }
.err { color: var(--red); }
.preview { margin: 10px 0; }
.satish-btn { display: inline-block; padding: 12px 20px; border-radius: 999px; background: #f7931a; color: #0b0e11; font: 600 16px system-ui; text-decoration: none; }
.ref { width: 100%; border-collapse: collapse; font-size: 13px; }
.ref th, .ref td { text-align: left; padding: 6px; border-bottom: 1px solid var(--border); vertical-align: top; }
code { font-size: 12px; }
</style>
