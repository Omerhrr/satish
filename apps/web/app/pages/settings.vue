<template>
  <div>
    <h1 class="page-title">🛡 Security &amp; recovery</h1>
    <p class="page-sub">How Satish keeps your account and money safe.</p>

    <section class="card">
      <h2>Our promises</h2>
      <ul class="small dim" style="padding-left: 18px; line-height: 2">
        <li>The bot will <b>never</b> ask for your recovery phrase or private keys.</li>
        <li>The AI assistant can never see your recovery phrase or move your bitcoin.</li>
        <li>Anything important, like sending an email, waits for your OK.</li>
        <li>Your Telegram sign-in is checked on our server every time.</li>
        <li>Your reports are private; only you can download them.</li>
      </ul>
    </section>

    <section class="card">
      <h2>Sign out</h2>
      <p class="sub">
        Sign-ins last {{ ttlNote }}. Logging out ends this sign-in everywhere,
        straight away.
      </p>
      <button
        class="btn sensitive-action"
        :disabled="loggingOut"
        @click="logout"
      >
        <span v-if="loggingOut" class="spinner" /> Log out
      </button>
      <span class="small dim" style="margin-left: 10px">{{ sessionNote }}</span>
    </section>

    <section class="card">
      <h2>Where you're signed in</h2>
      <p class="small dim">
        Sign out of anything you don't recognise. It takes effect immediately.
      </p>
      <p v-if="sessionsError" class="small" style="color: #f59e0b">{{ sessionsError }}</p>
      <p v-else-if="!sessions.length" class="small dim">
        {{ noSessionsNote }}
      </p>
      <div v-else class="session-list">
        <div v-for="s in sessions" :key="s.id" class="session-row">
          <div>
            <div class="small">
              <b>{{ human(s.created_via) }}</b> · signed in {{ fmt(s.created_at) }} · expires
              {{ fmt(s.expires_at) }}
            </div>
            <div class="small dim">
              last used: {{ s.last_used_at ? fmt(s.last_used_at) : "never" }}
            </div>
          </div>
          <button
            class="btn ghost sensitive-action"
            :disabled="revokingId === s.id"
            @click="revoke(s.id)"
          >
            <span v-if="revokingId === s.id" class="spinner" /> Sign out
          </button>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Recovering your wallet</h2>
      <p class="small dim">
        Your 12-word recovery phrase is the only way to restore your bitcoin.
        It lives only on your phone, protected by your wallet password; Satish never
        sees it and can't recover it for you. You can view it again under
        Wallet → Show recovery phrase. Keep a paper copy somewhere safe.
      </p>
    </section>

    <section class="card">
      <h2>What we keep, and for how long</h2>
      <p class="small dim">
        Payment and TK records are kept permanently so your balance can
        always be checked. Old sign-ins are removed after 7 days, read
        notifications after 30 days (unread after 90), finished automation
        runs after 180 days, and sent email drafts after 30 days. Your reports
        stay until you delete them.
      </p>
    </section>

    <section class="card">
      <h2>Your data</h2>
      <p class="small dim">
        Download a copy of everything Satish stores about you. Passwords and
        sign-in secrets are never included.
      </p>
      <button class="btn" :disabled="exporting" @click="exportData">
        <span v-if="exporting" class="spinner" /> Download my data
      </button>
      <span class="small dim" style="margin-left: 10px">{{ exportNote }}</span>
    </section>

    <section class="card">
      <h2>Close account</h2>
      <p class="small dim">
        This permanently deletes your account and content. You'll need to
        finish any running tasks, open payments and spend or clear your TK
        first. Your bitcoin is not affected: your recovery phrase still
        controls it. This can't be undone.
      </p>
      <button class="btn sensitive-action" :disabled="closing" @click="closeAccount">
        <span v-if="closing" class="spinner" /> ⚠️ Close my account permanently
      </button>
      <p v-if="closureNote" class="small" style="margin-top: 8px">{{ closureNote }}</p>
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
const exporting = ref(false);
const exportNote = ref("");
const closing = ref(false);
const closureNote = ref("");

const ttlNote = "24h";
const noSessionsNote =
  "You're not signed in here. Open Satish from the Telegram bot to sign in.";

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
  if (!window.confirm("Log out of Satish?")) return;
  loggingOut.value = true;
  try {
    await api.logout();
    for (const store of [window.localStorage, window.sessionStorage]) {
      store.removeItem("xp_session_token");
    }
    note("Logged out");
    await loadSessions();
  } catch (err) {
    note(String(err instanceof Error ? err.message : err));
  } finally {
    loggingOut.value = false;
  }
}

async function revoke(sessionId: string) {
  if (!window.confirm("Sign this device out? It will be logged out straight away.")) return;
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

async function exportData() {
  exporting.value = true;
  exportNote.value = "";
  try {
    const res = await api.exportAccount();
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `xp-account-export-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    exportNote.value = "Download started";
  } catch (err) {
    exportNote.value = String(err instanceof Error ? err.message : err);
  } finally {
    exporting.value = false;
  }
}

async function closeAccount() {
  if (
    !window.confirm(
      "Close your account permanently? Your content is erased, your Telegram link is removed, and this cannot be undone."
    )
  )
    return;
  const typed = window.prompt('This is permanent. Type CLOSE to confirm.');
  if (typed !== "CLOSE") {
    closureNote.value = "That didn't match, so nothing was changed.";
    return;
  }
  closing.value = true;
  closureNote.value = "";
  try {
    const result = await api.closeAccount("CLOSE");
    closureNote.value = "Your account is closed. Your bitcoin is still yours, controlled by your recovery phrase.";
    for (const store of [window.localStorage, window.sessionStorage]) {
      store.removeItem("xp_session_token");
    }
  } catch (err) {
    closureNote.value = String(err instanceof Error ? err.message : err);
  } finally {
    closing.value = false;
  }
}

onMounted(loadSessions);
</script>
