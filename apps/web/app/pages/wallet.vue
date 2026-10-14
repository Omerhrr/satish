<template>
  <div>
    <h1 class="page-title">₿ Wallet</h1>
    <p class="page-sub">On-chain self-custody — arriving after the phase-3 wallet library decision.</p>

    <section class="hero">
      <h1 style="font-size: 20px">Custody model, stated plainly</h1>
      <p class="tagline">
        Target model: self-custodial with user-controlled keys. This service
        stores wallet <em>metadata</em> only. Seed phrases and private keys never
        touch the API, the agent, the bot, or the database.
      </p>
    </section>

    <section class="card">
      <h2>What will NOT be claimed</h2>
      <ul class="small dim" style="padding-left: 18px; line-height: 2">
        <li>That Telegram (or any chat platform) safely stores your keys.</li>
        <li>That an on-chain recovery phrase alone restores Lightning channel state.</li>
        <li>That the AI agent can "manage" your wallet — it cannot sign anything.</li>
        <li>That custodial convenience equals self-custody.</li>
      </ul>
    </section>

    <section class="card">
      <h2>Planned flows (regtest first)</h2>
      <div class="table-wrap" style="margin-top: 10px">
        <table class="ledger">
          <thead><tr><th>Flow</th><th>Phase</th><th>Status</th></tr></thead>
          <tbody>
            <tr><td>Create / import wallet, secure recovery</td><td>3</td><td><span class="badge not_configured">pending spike</span></td></tr>
            <tr><td>Address derivation &amp; receive</td><td>3</td><td><span class="badge not_configured">pending spike</span></td></tr>
            <tr><td>Send with full pre-sign review</td><td>3</td><td><span class="badge not_configured">pending spike</span></td></tr>
            <tr><td>Lightning invoices &amp; payments</td><td>3+</td><td><span class="badge not_configured">pending PoC</span></td></tr>
            <tr><td>XP purchase with sats</td><td>4</td><td><span class="badge not_configured">planned</span></td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <div class="notice small">
      Wallet and Lightning adapters are replaceable protocols in
      <code class="mono">services/wallet-adapter</code> and
      <code class="mono">services/lightning-adapter</code> so the library choice
      never leaks through the codebase (plan: suggested_repository_layout notes).
    </div>
  </div>
</template>

<script setup lang="ts">
// Wallet flows activate after the threat-model and integration spikes.
</script>
