<template>
  <div>
    <h1 class="page-title">🔗 Connected services</h1>
    <p class="page-sub">
      Link an email service so the agent can draft and - only after you approve the
      exact content - send. Credentials are encrypted at rest and never shown again,
      not even here.
    </p>

    <section class="card">
      <h2>Link SMTP email service</h2>
      <p class="small dim">
        The connection grants the <code>email:draft</code> and <code>email:send</code>
        scopes. Sending additionally requires your explicit approval of each message
        (bound to its content digest and a time window). Revoking deletes the stored
        credential immediately.
      </p>
      <div class="form-grid">
        <label>SMTP host<input v-model="form.host" placeholder="smtp.example.com" /></label>
        <label>Port<input v-model="form.port" inputmode="numeric" placeholder="587" /></label>
        <label>Username (sender)<input v-model="form.username" placeholder="you@example.com" /></label>
        <label>Password<input v-model="form.password" type="password" placeholder="app password" /></label>
        <label class="check"><input v-model="form.starttls" type="checkbox" /> Use STARTTLS</label>
      </div>
      <button class="btn" :disabled="linking || !form.host || !form.username" @click="link">
        <span v-if="linking" class="spinner" /> Link service
      </button>
      <span v-if="note" class="small" style="margin-left: 10px">{{ note }}</span>
      <p v-if="error" class="small" style="color: #f59e0b">{{ error }}</p>
    </section>

    <section class="card">
      <h2>Your connections</h2>
      <p v-if="loadError" class="small" style="color: #f59e0b">{{ loadError }}</p>
      <p v-else-if="!connections.length" class="small dim">
        No services linked yet. Without a connection, email drafts stay preview-only -
        the agent cannot send anything.
      </p>
      <div v-for="c in connections" :key="c.id" class="row-list">
        <div>
          <div class="small">
            <b>{{ c.provider }}</b> · {{ c.status }} · scopes: {{ c.scopes.join(", ") }}
          </div>
          <div class="small dim">
            linked {{ fmt(c.created_at) }}
            <span v-if="c.disclosure"> · {{ c.disclosure }}</span>
          </div>
        </div>
        <button
          v-if="c.status !== 'revoked'"
          class="btn ghost sensitive-action"
          :disabled="revokingId === c.id"
          @click="revoke(c.id)"
        >
          <span v-if="revokingId === c.id" class="spinner" /> Revoke
        </button>
      </div>
    </section>

    <section class="card">
      <h2>Email drafts (preview)</h2>
      <p class="small dim">
        Every draft the agent prepared. Status shows the honest send outcome:
        <code>sent</code>, <code>failed</code> (definite refusal - safe to retry),
        or <code>unknown_outcome</code> (the server may have accepted it; the system
        never retries automatically - a resend requires a new draft and a new approval).
      </p>
      <p v-if="!drafts.length" class="small dim">No drafts yet.</p>
      <div v-for="d in drafts" :key="d.id" class="row-list">
        <div>
          <div class="small">
            <b>{{ d.subject }}</b> → {{ d.to_address }}
            <span class="badge" :data-status="d.status">{{ d.status }}</span>
          </div>
          <div class="small dim">
            {{ fmt(d.created_at) }}
            <span v-if="d.provider_mode"> · via {{ d.provider_mode }}</span>
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
  if (!window.confirm("Revoke this connection? The stored credential is deleted immediately.")) {
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
