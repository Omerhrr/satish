<template>
  <div class="guide">
    <h1 class="page-title">How recovery works</h1>
    <p class="page-sub">
      Satish is a self-custodial wallet: you hold the keys, so nobody (not even Satish)
      can freeze, take or recover your bitcoin for you. That's the point, and it means
      a little planning goes a long way.
    </p>

    <section class="card">
      <h2>📝 Your 12 words are the wallet</h2>
      <ul>
        <li>Anyone with your 12 words can take your bitcoin. Anyone without them can't.</li>
        <li>Write them on paper, in order. Keep the paper somewhere dry and private. A second copy in another place is better.</li>
        <li>Never photograph them, type them into a website or chat, or give them to "support". Satish will never ask.</li>
      </ul>
    </section>

    <section class="card">
      <h2>📱 Lost or new phone</h2>
      <ol>
        <li>Open Satish in Telegram on the new phone.</li>
        <li>If you turned on Telegram backup, tap <b>Restore from my Telegram backup</b> and enter your wallet password.</li>
        <li>Otherwise tap <b>I already have a recovery phrase</b> and type your 12 words.</li>
        <li>Your balance, including payments to your @username, comes back.</li>
      </ol>
    </section>

    <section class="card">
      <h2>🔑 Forgot your password</h2>
      <p>
        The password only locks the wallet on your phone. If you forget it, remove the wallet
        from the phone and restore it with your 12 words, then choose a new password.
      </p>
    </section>

    <section class="card">
      <h2>🔁 Leaving Satish</h2>
      <p>
        Your 12 words work in other wallets that support "BIP84 / Native SegWit", such as
        Sparrow, BlueWallet, Nunchuk and Electrum. You can also send everything to another
        wallet from <b>Wallet settings → Move everything</b>.
      </p>
    </section>

    <section class="card">
      <h2>👪 For your family</h2>
      <p>
        If something happens to you, your family can only reach your bitcoin with your 12 words.
        Plan it while you can:
      </p>
      <ul>
        <li>Store a copy of the 12 words where a trusted person can get it if needed, for example sealed with your will, or with a lawyer.</li>
        <li>Leave a note (separate from the words) saying: "I have bitcoin in a wallet called Satish. Restore it with my 12 words in any BIP84 wallet."</li>
        <li>Tell one trusted person that the note exists, not what the words are.</li>
        <li>Check the plan once a year.</li>
      </ul>
      <p class="small dim">For larger amounts, consider a multi-signature setup or a professional inheritance service.</p>
    </section>

    <NuxtLink class="btn" to="/">← Back to wallet</NuxtLink>
  </div>
</template>

<style scoped>
.guide { display: flex; flex-direction: column; gap: 12px; }
ul, ol { padding-left: 18px; line-height: 1.7; margin: 6px 0; color: var(--text-dim); }
p { color: var(--text-dim); line-height: 1.6; }
h2 { margin: 0 0 6px; }
</style>
