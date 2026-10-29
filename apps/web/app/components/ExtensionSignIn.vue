<template>
  <div class="signin">
    <img class="logo" src="/logo.png" alt="Satish" width="56" height="56" />
    <h1>Satish in your browser</h1>
    <p class="sub">Sign in with your Telegram account. Same TK, same tasks, same @username.</p>

    <section class="card">
      <template v-if="state === 'loading'">
        <p class="dim"><span class="spinner" /> Getting a code…</p>
      </template>
      <template v-else-if="state === 'code'">
        <p class="step">1. Copy this code</p>
        <button class="code" type="button" @click="copyCode">{{ code }}</button>
        <p class="small dim">{{ copied ? "Copied ✓" : "Tap to copy" }}</p>
        <p class="step">2. Send it to the Satish bot</p>
        <button class="btn primary" type="button" @click="openBot">Open the bot in Telegram</button>
        <p class="small dim">Send: <code>/link {{ code }}</code></p>
        <p class="waiting"><span class="spinner" /> Waiting for Telegram… (code works for {{ minutesLeft }} min)</p>
      </template>
      <template v-else-if="state === 'expired'">
        <p>The code expired.</p>
        <button class="btn primary" type="button" @click="start">Get a new code</button>
      </template>
      <template v-else-if="state === 'error'">
        <p class="err">{{ error }}</p>
        <button class="btn primary" type="button" @click="start">Try again</button>
      </template>
    </section>

    <p class="small dim foot">
      Your wallet stays on each device. After signing in you can restore it here with your
      12 words, or create a new one.
    </p>
  </div>
</template>

<script setup lang="ts">
const emit = defineEmits<{ signedIn: [] }>();
const api = useXpApi();
const { openExternal } = usePlatform();
const config = useRuntimeConfig();

const state = ref<"loading" | "code" | "expired" | "error">("loading");
const code = ref("");
const error = ref("");
const copied = ref(false);
const bot = ref<string>((config.public.botUsername as string) || "");
const expiresAt = ref(0);
const now = ref(Date.now());
let poll: ReturnType<typeof setInterval> | null = null;
let tick: ReturnType<typeof setInterval> | null = null;
let token = "";

const minutesLeft = computed(() => Math.max(1, Math.ceil((expiresAt.value - now.value) / 60_000)));

function stop() {
  if (poll) clearInterval(poll);
  if (tick) clearInterval(tick);
  poll = tick = null;
}

async function start() {
  stop();
  state.value = "loading";
  try {
    const r = await api.linkStart();
    code.value = r.code;
    token = r.poll_token;
    if (r.bot_username) bot.value = r.bot_username;
    now.value = Date.now();
    expiresAt.value = now.value + r.expires_in * 1000;
    state.value = "code";
    poll = setInterval(check, 2500);
    tick = setInterval(() => (now.value = Date.now()), 15_000);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Couldn't reach Satish.";
    state.value = "error";
  }
}

async function check() {
  try {
    const s = await api.linkPoll(token);
    if (!s) return;
    stop();
    try {
      localStorage.setItem("xp_session_token", s.session_token);
    } catch {
      /* ignore */
    }
    emit("signedIn");
  } catch (e) {
    stop();
    const msg = e instanceof Error ? e.message : "";
    if (/expired/i.test(msg)) state.value = "expired";
    else {
      error.value = msg || "Something went wrong.";
      state.value = "error";
    }
  }
}

async function copyCode() {
  try {
    await navigator.clipboard.writeText(`/link ${code.value}`);
    copied.value = true;
    setTimeout(() => (copied.value = false), 2000);
  } catch {
    /* ignore */
  }
}

function openBot() {
  void copyCode();
  const name = bot.value.replace(/^@/, "");
  openExternal(name ? `https://t.me/${name}?text=${encodeURIComponent("/link " + code.value)}` : "https://t.me");
}

onMounted(start);
onBeforeUnmount(stop);
</script>

<style scoped>
.signin { max-width: 420px; margin: 0 auto; padding: 28px 16px; text-align: center; }
.logo { width: 56px; height: 56px; margin: 0 auto 12px; border-radius: 14px; display: block; }
h1 { font-size: 22px; margin: 0 0 6px; }
.sub { color: var(--text-dim, #94a3b8); margin: 0 0 18px; }
.card { text-align: left; }
.step { font-weight: 600; margin: 10px 0 6px; }
.code { width: 100%; font: 700 28px/1.2 ui-monospace, monospace; letter-spacing: 4px; padding: 14px; border-radius: 12px; border: 1px dashed var(--orange, #f7931a); background: transparent; color: inherit; cursor: pointer; }
.waiting { display: flex; gap: 8px; align-items: center; color: var(--orange, #f7931a); font-size: 14px; margin-top: 14px; }
.err { color: var(--red, #ef4444); }
.foot { margin-top: 16px; }
code { font-size: 13px; }
</style>
