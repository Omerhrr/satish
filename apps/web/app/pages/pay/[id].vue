<template>
  <div class="paypage">
    <header class="brand"><span class="badge">S</span> Satish</header>

    <section v-if="loading" class="card center"><span class="spinner" /> Loading…</section>

    <section v-else-if="!req" class="card center">
      <h2>Request not found</h2>
      <p class="sub">{{ error || "This payment link doesn't exist or was removed." }}</p>
    </section>

    <section v-else class="card center">
      <div v-if="req.network === 'testnet'" class="testnet">🧪 Test network: pay with test coins only.</div>
      <div class="who">@{{ req.username }}</div>
      <div class="dim">is requesting</div>
      <div class="amount">
        {{ req.amount_sats ? req.amount_sats.toLocaleString() + " sats" : "a payment" }}
      </div>
      <div v-if="req.amount_sats && naira(req.amount_sats)" class="dim">{{ naira(req.amount_sats) }}</div>
      <div v-if="req.note" class="note">for "{{ req.note }}"</div>

      <template v-if="req.status === 'paid'">
        <div class="paid">✅ Paid. Thank you!</div>
      </template>
      <template v-else-if="req.status === 'cancelled'">
        <div class="dim">This request was cancelled.</div>
      </template>
      <template v-else>
        <div v-if="!verified" class="warn">⚠️ This request failed its security check. Don't pay it.</div>
        <template v-else>
          <button v-if="inTelegram" class="btn primary" @click="payInApp">Pay with my Satish wallet</button>
          <a v-else-if="botLink" class="btn primary" :href="botLink">Pay with Satish on Telegram</a>

          <div class="qr" v-html="qrSvg" />
          <div class="addr mono">{{ req.address }}</div>
          <div class="row">
            <button class="btn" @click="copy(req.address)">{{ copied ? "Copied ✓" : "Copy address" }}</button>
            <a class="btn" :href="bip21">Open in my wallet app</a>
          </div>
          <p class="small dim">
            Scan or copy into any bitcoin wallet.
            <template v-if="req.amount_sats">Send exactly {{ req.amount_sats.toLocaleString() }} sats.</template>
            <span class="ok">✓ Address verified for @{{ req.username }}</span>
          </p>
          <p class="small status">
            <span class="spinner" />
            <template v-if="req.paid_sats">Payment seen ({{ req.paid_sats.toLocaleString() }} sats). Waiting for confirmation…</template>
            <template v-else>Waiting for payment…</template>
          </p>
        </template>
      </template>
    </section>

    <p class="foot small dim">Satish · a self-custodial bitcoin wallet in Telegram. Satish never holds anyone's money.</p>
  </div>
</template>

<script setup lang="ts">
import { renderSVG } from "uqr";
import type { PaymentRequestOut } from "@xp/api-client";
import { NETWORKS, verifyPoolAddress } from "~/lib/wallet-core";

definePageMeta({ layout: false });

const route = useRoute();
const api = useXpApi();
const config = useRuntimeConfig();
const { naira } = usePrice();
const req = ref<PaymentRequestOut | null>(null);
const loading = ref(true);
const error = ref("");
const copied = ref(false);
let timer: ReturnType<typeof setInterval> | null = null;

const id = computed(() => String(route.params.id || ""));
const inTelegram = computed(() => !!(window as any).Telegram?.WebApp?.initData);
const botLink = computed(() => {
  const bot = String(config.public.botUsername || "").replace(/^@/, "");
  return bot ? `https://t.me/${bot}?start=pay_${id.value}` : "";
});
const verified = computed(() => {
  const q = req.value;
  if (!q) return false;
  const net = q.network === "mainnet" ? NETWORKS.mainnet : NETWORKS.testnet;
  return verifyPoolAddress(q.identity_pubkey, net, q.address, q.signature);
});
const bip21 = computed(() => {
  const q = req.value;
  if (!q) return "";
  const params = new URLSearchParams();
  if (q.amount_sats) params.set("amount", (q.amount_sats / 1e8).toFixed(8).replace(/0+$/, "").replace(/\.$/, ""));
  params.set("label", "@" + q.username);
  if (q.note) params.set("message", q.note);
  return `bitcoin:${q.address}?${params.toString()}`;
});
const qrSvg = computed(() => (bip21.value ? renderSVG(bip21.value, { border: 2, whiteColor: "#ffffff", blackColor: "#0b0e11" }) : ""));

async function load() {
  try {
    req.value = await api.getRequest(id.value);
    if (req.value.status !== "open" && timer) clearInterval(timer);
  } catch (e) {
    if (!req.value) error.value = e instanceof Error ? e.message : "";
  } finally {
    loading.value = false;
  }
}

function payInApp() {
  navigateTo(`/?pay=${encodeURIComponent(id.value)}`);
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

onMounted(() => {
  load();
  timer = setInterval(load, 10_000);
});
onBeforeUnmount(() => timer && clearInterval(timer));
</script>

<style scoped>
.paypage { max-width: 460px; margin: 0 auto; padding: 16px; min-height: 100vh; }
.brand { display: flex; align-items: center; gap: 8px; font-weight: 700; margin-bottom: 14px; }
.badge { background: var(--orange); color: #0b0e11; border-radius: 8px; width: 28px; height: 28px; display: grid; place-items: center; }
.center { text-align: center; display: flex; flex-direction: column; align-items: center; gap: 8px; }
.who { font-size: 22px; font-weight: 700; color: var(--orange); }
.amount { font-size: 30px; font-weight: 800; }
.note { font-style: italic; color: var(--text-dim); }
.paid { color: var(--green); font-weight: 700; font-size: 18px; margin-top: 8px; }
.warn { color: var(--red); font-weight: 600; }
.ok { color: var(--green); display: block; margin-top: 4px; }
.qr { width: 220px; height: 220px; border-radius: 12px; overflow: hidden; background: #fff; margin-top: 8px; }
.qr :deep(svg) { width: 100%; height: 100%; }
.addr { word-break: break-all; font-size: 13px; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 8px; width: 100%; }
.row { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }
.status { display: flex; gap: 8px; align-items: center; color: var(--orange); }
.testnet { background: var(--orange-soft); color: var(--orange); border-radius: 10px; padding: 6px 10px; font-size: 13px; }
.foot { text-align: center; margin-top: 18px; }
.btn.primary { width: 100%; }
</style>
