<template>
  <div>
    <h1 class="page-title">🛡 Security &amp; recovery</h1>
    <p class="page-sub">Security, recovery, and transparent limitations are release requirements - not post-launch additions.</p>

    <section class="card">
      <h2>Standing rules</h2>
      <ul class="small dim" style="padding-left: 18px; line-height: 2">
        <li>The bot will <b>never</b> ask for a seed phrase or private key in chat.</li>
        <li>The AI agent never receives seed material or signing authority.</li>
        <li>Every sensitive action requires explicit, fresh user approval.</li>
        <li>Telegram init data is validated server-side; forged or stale payloads are rejected.</li>
        <li>Generated artifacts are private by default with authorized delivery.</li>
      </ul>
    </section>

    <section class="card">
      <h2>Session</h2>
      <p class="sub">
        Sessions are short-lived ({{ ttlNote }}), stored server-side as a hash only, and
        revocation takes effect immediately - logout kills the session on the server, not
        just in this webview.
      </p>
      <button
        class="btn sensitive-action"
        :disabled="loggingOut"
        @click="logout"
      >
        <span v-if="loggingOut" class="spinner" /> ⚠️ Log out (revoke this session)
      </button>
      <span class="small dim" style="margin-left: 10px">{{ sessionNote }}</span>
    </section>

    <section class="card">
      <h2>Active sessions</h2>
      <p class="small dim">
        Every live bearer session issued for your account. Revoke anything you do not
        recognise - revocation is instant and permanent for that token.
      </p>
      <p v-if="sessionsError" class="small" style="color: #f59e0b">{{ sessionsError }}</p>
      <p v-else-if="!sessions.length" class="small dim">
        {{ noSessionsNote }}
      </p>
      <div v-else class="session-list">
        <div v-for="s in sessions" :key="s.id" class="session-row">
          <div>
            <div class="small">
              <b>{{ s.created_via }}</b> · created {{ fmt(s.created_at) }} · expires
              {{ fmt(s.expires_at) }}
            </div>
            <div class="small dim">
              last used: {{ s.last_used_at ? fmt(s.last_used_at) : "never" }} ·
              <code class="sid">{{ s.id.slice(0, 8) }}</code>
            </div>
          </div>
          <button
            class="btn ghost sensitive-action"
            :disabled="revokingId === s.id"
            @click="revoke(s.id)"
          >
            <span v-if="revokingId === s.id" class="spinner" /> Revoke
          </button>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Recovery guidance (preview)</h2>
      <p class="small dim">
        On-chain recovery requires your seed phrase created at wallet setup
        (phase 3). Lightning additionally requires channel-state backups - a
        seed phrase alone will not restore channels. Recovery steps will be
        shown privately in the Mini App and verified during onboarding.
      </p>
    </section>

    <section class="card">
      <h2>Custody, data &amp; retention (phase 10)</h2>
      <p class="small dim">
        <strong>Custody:</strong> you hold your keys - wallets are
        self-custodial, the server stores public descriptors only, and the
        agent can never sign or ask for seeds. <strong>Your XP ledger is
        append-only</strong> and is never auto-deleted; the same applies to
        payment records, task evidence, and the audit trail.
        <strong>What does expire:</strong> revoked/expired login sessions
        (7 days), read notifications (30 days; unread 90), finished
        automation runs (180 days), sent email drafts (30 days). Deliverables
        (PDFs, research artifacts) are kept until you delete them. Full
        policy: privacy &amp; retention docs; known limitations are published
        in the project's limitations register.
      </p>
    </section>

    <section class="card">
      <h2>Environment</h2>
      <p class="small dim">
        Current build: phase 10 operational readiness · DEV_MODE grants are
        enabled · no production secrets exist in this environment.
      </p>
    </section>
  </div>
</template>

<script setup lang="ts">
import type { SessionInfo } from "@xp/shared-types";

const api = useXpApi();
const sessionNote = ref("");
const sessions = ref<SessionInfo[]>([]);
const sessionsError = ref("");
const loggingOut = ref(false);
const revokingId = ref<string | null>(null);

const ttlNote = "24h";
const noSessionsNote =
  "No user-issued session found in this webview. The app may be running on the DEV_MODE " +
  "fallback user (no stored token) - open the app fresh from Telegram to issue a real session.";

function fmt(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function note(msg: string) {
  sessionNote.value = msg;
  setTimeout(() => (sessionNote.value = ""), 3000);
}

async function loadSessions() {
  sessionsError.value = "";
  try {
    sessions.value = await api.listSessions();
  } catch (err) {
    sessionsError.value = String(err instanceof Error ? err.message : err);
  }
}

async function logout() {
  if (!window.confirm("Log out and revoke this session on the server?")) return;
  loggingOut.value = true;
  try {
    await api.logout();
    for (const store of [window.localStorage, window.sessionStorage]) {
      store.removeItem("xp_session_token");
    }
    note("server-side revocation confirmed");
    await loadSessions();
  } catch (err) {
    note(String(err instanceof Error ? err.message : err));
  } finally {
    loggingOut.value = false;
  }
}

async function revoke(sessionId: string) {
  if (!window.confirm(`Revoke session ${sessionId.slice(0, 8)}? Devices using it are logged out immediately.`)) return;
  revokingId.value = sessionId;
  try {
    await api.revokeSession(sessionId);
    note(`session ${sessionId.slice(0, 8)} revoked`);
    await loadSessions();
  } catch (err) {
    note(String(err instanceof Error ? err.message : err));
  } finally {
    revokingId.value = null;
  }
}

onMounted(loadSessions);
</script>
