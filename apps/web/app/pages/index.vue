<template>
  <div>
    <section class="hero">
      <h1>XP Developer Console</h1>
      <p class="tagline">
        Phase 1 scaffold status — monorepo, API, worker, ledger, agent adapter and
        Mini App wired end to end. Bitcoin + Lightning land after the phase-3
        integration spikes.
      </p>
    </section>

    <!-- service health -->
    <div class="grid-2">
      <div class="stat">
        <span class="label"><span class="dot" :class="dotClass(health?.database.status)" /> Database</span>
        <div class="value">{{ health?.database.status ?? "…" }}</div>
        <div class="faint small">{{ health?.database.detail ?? "checking" }}</div>
      </div>
      <div class="stat">
        <span class="label"><span class="dot" :class="dotClass(health?.queue.status)" /> Queue</span>
        <div class="value">{{ health?.queue.status ?? "…" }}</div>
        <div class="faint small">{{ health?.queue.detail ?? "checking" }}</div>
      </div>
      <div class="stat">
        <span class="label"><span class="dot" :class="dotClass(health?.agent_runtime.status)" /> Agent runtime</span>
        <div class="value">{{ health?.agent_runtime.status ?? "…" }}</div>
        <div class="faint small">DSH revision: {{ health?.dsh_revision ?? "…" }}</div>
      </div>
      <div class="stat">
        <span class="label">API</span>
        <div class="value">v{{ health?.version ?? "…" }}</div>
        <div class="faint small">env: {{ health?.env ?? "…" }} · overall {{ health?.status ?? "…" }}</div>
      </div>
    </div>

    <div style="height: 14px" />

    <!-- XP quick card -->
    <section class="card">
      <h2>⚡ XP credits</h2>
      <p class="sub">Internal usage credits — not Bitcoin, not a token. Rate: {{ balance?.sats_per_xp ?? "…" }} sats/XP.</p>
      <div class="balance-big">{{ balance ? balance.balance_xp.toLocaleString() + " XP" : "…" }}</div>
      <div style="display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap">
        <button class="btn primary" :disabled="granting" @click="grant(1000)">
          <span v-if="granting" class="spinner" /> Seed +1,000 XP
        </button>
        <button class="btn" :disabled="granting" @click="grant(10000)">Seed +10,000 XP</button>
        <NuxtLink class="btn ghost" to="/xp">Open ledger →</NuxtLink>
      </div>
      <div class="notice small">
        Dev grants are enabled because the API runs in DEV_MODE. In staging and
        production, XP is credited only from verified settled payments.
      </div>
    </section>

    <!-- WeasyPrint demo -->
    <section class="card">
      <h2>📄 Artifact pipeline demo</h2>
      <p class="sub">
        POST /artifacts/demo-pdf → worker job → WeasyPrint render → private storage →
        authorized download.
      </p>
      <div style="display: flex; gap: 10px; flex-wrap: wrap; align-items: center">
        <button class="btn primary" :disabled="pdfPending" @click="makePdf">
          <span v-if="pdfPending" class="spinner" /> Generate demo report
        </button>
        <a
          v-if="latestPdf && latestPdf.status === 'ready'"
          class="btn"
          :href="api.artifactDownloadUrl(latestPdf)"
          target="_blank"
        >
          Download PDF ({{ formatBytes(latestPdf.size_bytes) }})
        </a>
        <span v-if="latestPdf" class="badge" :class="latestPdf.status">{{ latestPdf.status }}</span>
      </div>
      <p v-if="pdfError" class="small" style="color: var(--red); margin-top: 10px">{{ pdfError }}</p>
    </section>

    <!-- capabilities honesty card -->
    <section class="card">
      <h2>🧭 Capability surface</h2>
      <p class="sub">What is real today — the product never overclaims.</p>
      <div class="table-wrap">
        <table class="ledger">
          <thead>
            <tr><th>Capability</th><th>Status</th></tr>
          </thead>
          <tbody>
            <tr><td>Wallets (on-chain self-custody)</td><td>{{ caps?.wallets ?? "…" }}</td></tr>
            <tr><td>Lightning</td><td>{{ caps?.lightning ?? "…" }}</td></tr>
            <tr><td>Agent runtime (DSH)</td><td>{{ caps?.agent_runtime ?? "…" }}</td></tr>
          </tbody>
        </table>
      </div>
      <ul class="small dim" style="margin-top: 12px; padding-left: 18px">
        <li v-for="(n, i) in caps?.notes ?? []" :key="i" style="margin-bottom: 4px">{{ n }}</li>
      </ul>
    </section>
  </div>
</template>

<script setup lang="ts">
import type { ArtifactOut, BalanceOut, CapabilitiesOut, HealthOut } from "@xp/shared-types";

const api = useXpApi();
const health = ref<HealthOut | null>(null);
const caps = ref<CapabilitiesOut | null>(null);
const balance = ref<BalanceOut | null>(null);
const artifacts = ref<ArtifactOut[]>([]);
const granting = ref(false);
const pdfPending = ref(false);
const pdfError = ref("");

const latestPdf = computed(() => artifacts.value[0] ?? null);

function dotClass(status?: string) {
  return status === "ok" ? "ok" : status === "error" ? "error" : "not_configured";
}

function formatBytes(n: number) {
  return n > 1024 * 1024 ? (n / 1024 / 1024).toFixed(1) + " MB" : Math.round(n / 1024) + " KB";
}

async function refreshAll() {
  try {
    [health.value, caps.value, balance.value, artifacts.value] = await Promise.all([
      api.health(),
      api.capabilities(),
      api.balance(),
      api.listArtifacts(),
    ]);
  } catch (e) {
    console.error("console refresh failed", e);
  }
}

async function grant(amount: number) {
  granting.value = true;
  try {
    balance.value = await api.devGrant({ amount_xp: amount, reason: "console seed grant" });
  } catch (e) {
    alert(String(e));
  } finally {
    granting.value = false;
  }
}

async function makePdf() {
  pdfPending.value = true;
  pdfError.value = "";
  try {
    const artifact = await api.createDemoPdf({
      title: "XP Scaffold Demo Report",
      sections: ["Executive Summary", "Market Findings", "Sources"],
    });
    // inline dev execution completes synchronously; poll briefly anyway
    for (let i = 0; i < 6 && artifact.status !== "ready"; i++) {
      await new Promise((r) => setTimeout(r, 500));
      const list = await api.listArtifacts();
      Object.assign(artifact, list.find((a) => a.id === artifact.id) ?? artifact);
    }
    artifacts.value = await api.listArtifacts();
  } catch (e) {
    pdfError.value = String(e);
  } finally {
    pdfPending.value = false;
  }
}

onMounted(refreshAll);
</script>
