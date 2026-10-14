<template>
  <div>
    <h1 class="page-title">🛡 Security &amp; recovery</h1>
    <p class="page-sub">Security, recovery, and transparent limitations are release requirements — not post-launch additions.</p>

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
      <p class="sub">Bearer session with server-side expiry; revocation hardening lands in phase 2.</p>
      <button class="btn" @click="logout">Log out (clear local token)</button>
      <span class="small dim" style="margin-left: 10px">{{ sessionNote }}</span>
    </section>

    <section class="card">
      <h2>Recovery guidance (preview)</h2>
      <p class="small dim">
        On-chain recovery requires your seed phrase created at wallet setup
        (phase 3). Lightning additionally requires channel-state backups — a
        seed phrase alone will not restore channels. Recovery steps will be
        shown privately in the Mini App and verified during onboarding.
      </p>
    </section>

    <section class="card">
      <h2>Environment</h2>
      <p class="small dim">
        Current build: phase 1 scaffold · DEV_MODE grants are enabled · no
        production secrets exist in this environment.
      </p>
    </section>
  </div>
</template>

<script setup lang="ts">
const sessionNote = ref("");

function logout() {
  try {
    localStorage.removeItem("xp_session_token");
    sessionStorage.removeItem("xp_session_token");
    sessionNote.value = "local token cleared";
  } catch {
    sessionNote.value = "storage unavailable";
  }
  setTimeout(() => (sessionNote.value = ""), 2500);
}
</script>
