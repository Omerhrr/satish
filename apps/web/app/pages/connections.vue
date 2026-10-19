<template>
  <div>
    <h1 class="page-title">🔗 Connect your email</h1>
    <p class="page-sub">
      Let the assistant write emails for you. Nothing is sent until you approve
      it. Your password is stored encrypted and never shown again.
    </p>

    <section class="card">
      <h2>Connect your email</h2>
      <p class="small dim">
        The assistant can write drafts, but every email needs your approval
        before it's sent. Disconnect at any time and your password is deleted
        immediately.
      </p>
      <div class="form-grid">
        <label>Mail server<input v-model="form.host" placeholder="smtp.example.com" /></label>
        <label>Port<input v-model="form.port" inputmode="numeric" placeholder="587" /></label>
        <label>Your email address<input v-model="form.username" placeholder="you@example.com" /></label>
        <label>Password<input v-model="form.password" type="password" placeholder="app password" /></label>
        <label class="check"><input v-model="form.starttls" type="checkbox" /> Secure connection (recommended)</label>
      </div>
      <button class="btn" :disabled="linking || !form.host || !form.username" @click="link">
        <span v-if="linking" class="spinner" /> Connect
      </button>
      <span v-if="note" class="small" style="margin-left: 10px">{{ note }}</span>
      <p v-if="error" class="small" style="color: #f59e0b">{{ error }}</p>
    </section>

    <section class="card">
      <h2>Your connections</h2>
      <p v-if="loadError" class="small" style="color: #f59e0b">{{ loadError }}</p>
      <p v-else-if="!connections.length" class="small dim">
        No email connected yet. The assistant can still write drafts, but it
        can't send anything.
      </p>
      <div v-for="c in connections" :key="c.id" class="row-list">
        <div>
          <div class="small">
            <b>Email</b> · {{ human(c.status) }}
          </div>
          <div class="small dim">
            linked {{ fmt(c.created_at) }}
            
          </div>
        </div>
        <button
          v-if="c.status !== 'revoked'"
          class="btn ghost sensitive-action"
          :disabled="revokingId === c.id"
          @click="revoke(c.id)"
        >
          <span v-if="revokingId === c.id" class="spinner" /> Disconnect
        </button>
      </div>
    </section>

    <section class="card">
      <h2>Email drafts</h2>
      <p class="small dim">
        Emails the assistant wrote for you. "Failed" means it wasn't sent, so you
        can try again. "Not sure if sent" means it may have gone out; we never
        resend on our own, so check your sent folder first.
      </p>
      <p v-if="!drafts.length" class="small dim">No drafts yet.</p>
      <div v-for="d in drafts" :key="d.id" class="row-list">
        <div>
          <div class="small">
            <b>{{ d.subject }}</b> → {{ d.to_address }}
            <span class="badge" :data-status="d.status">{{ human(d.status) }}</span>
          </div>
          <div class="small dim">
            {{ fmt(d.created_at) }}
            
            <span v-if="d.error"> · {{ d.error }}</span>
          </div>
          <pre class="draft-body">{{ d.body }}</pre>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import type { ConnectionOut, EmailDraftOut } from "@xp/shared-types";

const api = useXpApi();

const connections = ref<ConnectionOut[]>([]);
const drafts = ref<EmailDraftOut[]>([]);
const loadError = ref("");
const error = ref("");
const note = ref("");
const linking = ref(false);
const revokingId = ref<string | null>(null);

const form = reactive({
  host: "",
  port: "587",
  username: "",
  password: "",
  starttls: true,
});

function fmt(iso: string | null): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function flash(msg: string) {
  note.value = msg;
  setTimeout(() => (note.value = ""), 3500);
}

async function load() {
  loadError.value = "";
  try {
    connections.value = await api.listConnections();
    drafts.value = await api.listDrafts();
  } catch (err) {
    loadError.value = String(err instanceof Error ? err.message : err);
  }
}

async function link() {
  error.value = "";
  linking.value = true;
  try {
    const conn = await api.linkConnection({
      provider: "smtp",
      credential: {
        host: form.host,
        port: Number(form.port) || 587,
        username: form.username,
        password: form.password,
        starttls: form.starttls,
      },
    });
    flash(conn.disclosure || "Service linked.");
    form.password = "";
    await load();
  } catch (err) {
    error.value = String(err instanceof Error ? err.message : err);
  } finally {
    linking.value = false;
  }
}

async function revoke(id: string) {
  if (!window.confirm("Disconnect this email? Your saved password is deleted straight away.")) {
    return;
  }
  revokingId.value = id;
  try {
    const out = await api.revokeConnection(id);
    flash(out.disclosure || "Connection revoked.");
    await load();
  } catch (err) {
    error.value = String(err instanceof Error ? err.message : err);
  } finally {
    revokingId.value = null;
  }
}

onMounted(load);
</script>

<style scoped>
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin: 12px 0;
}
.form-grid label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--dim, #8899aa);
}
.form-grid input {
  padding: 8px 10px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 8px;
  background: transparent;
  color: inherit;
}
.form-grid label.check {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}
.row-list {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
}
.badge {
  margin-left: 8px;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  border: 1px solid rgba(148, 163, 184, 0.4);
}
.draft-body {
  margin: 6px 0 0;
  padding: 8px 10px;
  font-size: 12px;
  white-space: pre-wrap;
  border-radius: 8px;
  background: rgba(148, 163, 184, 0.08);
  max-height: 120px;
  overflow: auto;
}
</style>
