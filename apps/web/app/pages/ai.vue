<template>
  <div>
    <section class="hero">
      <h1>🤖 AI assistant</h1>
      <p class="tagline">
        Ask for research, price comparisons and written reports. You pay with
        <b>TK credits</b>, bought with bitcoin from your Satish wallet. You approve a
        budget first, and anything unused comes back.
      </p>
    </section>

    <section v-if="signedOut" class="card">
      <h2>Open Satish from Telegram</h2>
      <p class="sub">
        You're not signed in. Open the Satish bot in Telegram and tap <b>Open</b> to
        sign in with your Telegram account.
      </p>
    </section>

    <template v-else>
      <section class="card">
        <h2>⚡ TK credits</h2>
        <div class="balance-big">
          <span v-if="balance">{{ balance.balance_xp.toLocaleString() }} TK</span>
          <span v-else-if="balanceError" class="small dim">Couldn't load your credits. <a href="#" @click.prevent="load">Try again</a></span>
          <span v-else class="spinner" />
        </div>
        <p v-if="balance" class="sub">
          Only for AI tasks. TK can't be sent to anyone or turned back into sats.
        </p>
        <div class="actions">
          <NuxtLink class="btn primary" to="/tasks">Start a task</NuxtLink>
          <NuxtLink class="btn" to="/billing">Buy TK</NuxtLink>
          <NuxtLink class="btn ghost" to="/tk">History →</NuxtLink>
        </div>
      </section>

      <section class="card">
        <h2>What the assistant can do</h2>
        <div class="features">
          <NuxtLink to="/tasks" class="feature">
            <b>🔎 Research &amp; reports</b>
            <span class="small dim">Ask a question, set a budget, get a PDF report with sources.</span>
          </NuxtLink>
          <NuxtLink to="/automations" class="feature">
            <b>⏱ Automations</b>
            <span class="small dim">Repeat a task on a schedule with a spending cap.</span>
          </NuxtLink>
          <NuxtLink to="/connections" class="feature">
            <b>✉️ Email</b>
            <span class="small dim">Let the assistant draft emails; nothing sends without your OK.</span>
          </NuxtLink>
        </div>
      </section>

      <section class="card">
        <h2>📄 Try a sample report</h2>
        <p class="sub">See what a report looks like. Free, takes a few seconds.</p>
        <div class="actions">
          <button class="btn primary" :disabled="pdfPending" @click="makePdf">
            <span v-if="pdfPending" class="spinner" /> Create sample report
          </button>
          <button v-if="latestPdf && latestPdf.status === 'ready'" class="btn" @click="download(latestPdf)">
            Download PDF
          </button>
        </div>
        <p v-if="pdfError" class="small" style="color: var(--red); margin-top: 10px">{{ pdfError }}</p>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import type { ArtifactOut, BalanceOut } from "@xp/shared-types";

const api = useXpApi();
const balance = ref<BalanceOut | null>(null);
const balanceError = ref(false);
const signedOut = ref(false);
const artifacts = ref<ArtifactOut[]>([]);
const pdfPending = ref(false);
const pdfError = ref("");
const latestPdf = computed(() => artifacts.value[0] ?? null);


function isAuthError(e: unknown) {
  return /not signed in/i.test(String(e instanceof Error ? e.message : e));
}

async function load() {
  balanceError.value = false;
  // Each piece loads on its own so one failure never blanks the page.
  try {
    balance.value = await api.balance();
  } catch (e) {
    if (isAuthError(e)) signedOut.value = true;
    else balanceError.value = true;
  }
  try {
    artifacts.value = await api.listArtifacts();
  } catch {
    /* optional */
  }
}

async function download(a: ArtifactOut) {
  try {
    const token = sessionStorage.getItem("xp_session_token") ?? localStorage.getItem("xp_session_token");
    const res = await fetch(api.artifactDownloadUrl(a), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`download failed (${res.status})`);
    const url = URL.createObjectURL(await res.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "xp-report.pdf";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  } catch (e) {
    pdfError.value = "Couldn't download the report. Please try again.";
  }
}

async function makePdf() {
  pdfPending.value = true;
  pdfError.value = "";
  try {
    const artifact = await api.createDemoPdf({
      title: "Satish Sample Report",
      sections: ["Summary", "Findings", "Sources"],
    });
    for (let i = 0; i < 20 && artifact.status !== "ready"; i++) {
      await new Promise((r) => setTimeout(r, 750));
      const list = await api.listArtifacts();
      Object.assign(artifact, list.find((a) => a.id === artifact.id) ?? artifact);
    }
    artifacts.value = await api.listArtifacts();
    if (artifact.status !== "ready") pdfError.value = "Still working on it. Check back in a moment.";
  } catch (e) {
    pdfError.value = isAuthError(e) ? "Please open Satish from Telegram to sign in." : "Couldn't create the report. Please try again.";
  } finally {
    pdfPending.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.actions { display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
.features { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-top: 10px; }
.feature { display: flex; flex-direction: column; gap: 4px; padding: 12px; border: 1px solid var(--border); border-radius: 10px; text-decoration: none; color: inherit; }
.feature:hover { border-color: var(--orange); }
</style>
