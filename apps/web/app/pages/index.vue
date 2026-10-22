<template>
  <div class="wallet">
    <div v-if="w.net.name === 'testnet'" class="testnet">
      🧪 Test network: these coins have no value.
      <a href="https://mempool.space/testnet4/faucet" target="_blank" rel="noopener">Get free test coins</a>
    </div>

    <div v-if="w.net.name === 'mainnet' && w.state.stored && total > betaLimit" class="beta">
      Satish is new. Until it has had an independent security review, keep only
      spending money here and move savings to a wallet you've used for years.
    </div>

    <!-- ============ locked ============ -->
    <section v-if="w.state.stored && locked" class="card center">
      <div class="big-icon">🔒</div>
      <h2>Satish is locked</h2>
      <p class="sub">Enter your wallet password to open it.</p>
      <label class="field">Wallet password<input v-model="password" type="password" autocomplete="current-password" @keyup.enter="unlock" /></label>
      <p v-if="error" class="err">{{ error }}</p>
      <div class="stack">
        <button class="btn primary" :disabled="busy || !password" @click="unlock"><span v-if="busy" class="spinner" /> Unlock</button>
        <button class="btn ghost" @click="go('forgot'); locked = false">Forgot password?</button>
      </div>
    </section>

    <!-- ============ no wallet yet ============ -->
    <template v-else-if="!w.state.stored">
      <section v-if="view === 'welcome'" class="card center">
        <div class="big-icon">₿</div>
        <h2>Your own Bitcoin wallet</h2>
        <p class="sub">
          Only you hold the keys. Your recovery phrase is created on this phone and is
          never sent to Satish, not even to us.
        </p>
        <div class="stack">
          <button v-if="w.state.cloudHasBackup" class="btn primary" @click="go('cloudrestore')">
            ☁️ Restore from my Telegram backup
          </button>
          <button class="btn" :class="{ primary: !w.state.cloudHasBackup }" @click="startCreate">Create a new wallet</button>
          <button class="btn" @click="go('restore')">I already have a recovery phrase</button>
        </div>
        <p v-if="error" class="err">{{ error }}</p>
      </section>

      <section v-else-if="view === 'cloudrestore'" class="card">
        <h2>Restore from Telegram backup</h2>
        <p class="sub">Enter the wallet password you used when you set up this wallet.</p>
        <label class="field">Wallet password<input v-model="password" type="password" autocomplete="current-password" /></label>
        <p v-if="error" class="err">{{ error }}</p>
        <div class="stack">
          <button class="btn primary" :disabled="busy || !password" @click="cloudRestore">
            <span v-if="busy" class="spinner" /> Restore
          </button>
          <button class="btn ghost" @click="go('restore')">Use my 12 words instead</button>
          <button class="btn ghost" @click="go('welcome')">Cancel</button>
        </div>
      </section>

      <!-- show phrase -->
      <section v-else-if="view === 'show'" class="card">
        <h2>Write down your recovery phrase</h2>
        <p class="sub">
          These 12 words are the only way to get your bitcoin back if you lose this
          phone. Write them on paper, in order, and keep them somewhere safe.
          Never share them or type them into any website or chat.
        </p>
        <div class="words" :class="{ hidden: !revealed }" @click="revealed = true">
          <div v-for="(word, i) in words" :key="i" class="word"><span>{{ i + 1 }}</span>{{ word }}</div>
          <div v-if="!revealed" class="cover">Tap to show. Make sure nobody is watching.</div>
        </div>
        <label class="check"><input v-model="wroteDown" type="checkbox" /> I've written down all 12 words</label>
        <div class="stack">
          <button class="btn primary" :disabled="!revealed || !wroteDown" @click="startVerify">Continue</button>
          <button class="btn ghost" @click="cancelSetup">Cancel</button>
        </div>
      </section>

      <!-- verify phrase -->
      <section v-else-if="view === 'verify'" class="card">
        <h2>Check your backup</h2>
        <p class="sub">Type these words from your paper to make sure it's right.</p>
        <label v-for="(q, i) in quiz" :key="q" class="field">
          Word #{{ q + 1 }}
          <input v-model="answers[i]" autocapitalize="none" autocomplete="off" spellcheck="false" />
        </label>
        <p v-if="error" class="err">{{ error }}</p>
        <div class="stack">
          <button class="btn primary" @click="checkQuiz">Continue</button>
          <button class="btn ghost" @click="go('show')">Show the words again</button>
        </div>
      </section>

      <!-- restore -->
      <section v-else-if="view === 'restore'" class="card">
        <h2>Restore your wallet</h2>
        <p class="sub">Enter your 12 or 24 recovery words in order, separated by spaces.</p>
        <label class="field">
          Recovery phrase
          <textarea v-model="restoreText" rows="4" autocapitalize="none" autocomplete="off" spellcheck="false" />
        </label>
        <p v-if="error" class="err">{{ error }}</p>
        <div class="stack">
          <button class="btn primary" @click="checkRestore">Continue</button>
          <button class="btn ghost" @click="cancelSetup">Cancel</button>
        </div>
      </section>

      <!-- set password -->
      <section v-else-if="view === 'password'" class="card">
        <h2>Set a wallet password</h2>
        <p class="sub">
          You'll need it to send bitcoin from this phone. It isn't your recovery
          phrase: if you forget it, restore with your 12 words.
        </p>
        <label class="field">Password (at least 8 characters)<input v-model="pw1" type="password" autocomplete="new-password" /></label>
        <label class="field">Type it again<input v-model="pw2" type="password" autocomplete="new-password" /></label>
        <label v-if="w.state.cloudAvailable" class="check">
          <input v-model="cloudOpt" type="checkbox" />
          <span>Back up to my Telegram (encrypted with this password, so only you can open it)</span>
        </label>
        <p v-if="error" class="err">{{ error }}</p>
        <div class="stack">
          <button class="btn primary" :disabled="busy" @click="finishSetup">
            <span v-if="busy" class="spinner" /> Create wallet
          </button>
          <button class="btn ghost" :disabled="busy" @click="cancelSetup">Cancel</button>
        </div>
      </section>
    </template>

    <!-- ============ wallet ============ -->
    <template v-else>
      <!-- home -->
      <template v-if="view === 'home'">
        <section class="card center">
          <div class="dim small">
            {{ w.net.label }} balance
            <button class="eye" :aria-label="w.state.hideBalance ? 'Show balance' : 'Hide balance'" @click="w.setHideBalance(!w.state.hideBalance)">
              {{ w.state.hideBalance ? "🙈" : "👁" }}
            </button>
          </div>
          <template v-if="w.state.hideBalance">
            <div class="balance-big">••••••</div>
            <div class="dim small">Hidden. Tap 🙈 to show.</div>
          </template>
          <template v-else>
            <div class="balance-big">{{ fmtBtc(total) }} <span class="unit">{{ unit }}</span></div>
            <div class="dim small">
              {{ total.toLocaleString() }} sats
              <template v-if="naira(total)"> · {{ naira(total) }}</template>
            </div>
            <div v-if="w.pending.value" class="pending small">
              {{ w.pending.value > 0 ? "+" : "" }}{{ w.pending.value.toLocaleString() }} sats waiting to confirm
            </div>
          </template>
          <div class="row">
            <button class="btn primary" @click="go('receive'); watchReceive()">↓ Receive</button>
            <button class="btn primary" :disabled="!w.spendable.value" @click="openSend">↑ Send</button>
            <button class="btn primary" @click="openBuy">＋ Buy</button>
            <button class="btn primary" @click="openRequest">⇄ Request</button>
          </div>
          <button class="btn ghost small" :disabled="w.state.loading" @click="w.refresh()">
            <span v-if="w.state.loading" class="spinner" /> {{ w.state.loading ? "Updating…" : "Refresh" }}
          </button>
          <p v-if="w.state.error" class="err">{{ w.state.error }}</p>
          <p v-if="w.state.lastSync && !w.state.live && !w.state.loading" class="small dim">Last updated {{ ago(w.state.lastSync) }}</p>
        </section>

        <LightningWallet :hide="w.state.hideBalance" :username="w.state.handle?.username ?? null" @pay-onchain="payOnchainTo" />

        <section class="card">
          <h2>Activity</h2>
          <p v-if="!w.state.history.length && !w.state.loading" class="dim small">
            No transactions yet. Tap Receive to get your address.
          </p>
          <button v-for="t in w.state.history.slice(0, historyLimit)" :key="t.txid" class="tx" @click="openTx(t.txid)">
            <div>
              <b>{{ t.amount >= 0 ? "Received" : "Sent" }}</b>
              <span v-if="w.state.notes[t.txid]" class="small dim"> · {{ w.state.notes[t.txid] }}</span>
              <div class="small" :class="t.confirmed ? 'dim' : 'pending'">
                {{ t.confirmed ? fmtTime(t.time) : t.amount < 0 && t.replaceable ? "Waiting to confirm · tap to speed up" : "Waiting to confirm" }}
              </div>
            </div>
            <div :class="t.amount >= 0 ? 'pos' : 'neg'">
              <template v-if="w.state.hideBalance">••••</template>
              <template v-else>{{ t.amount >= 0 ? "+" : "" }}{{ t.amount.toLocaleString() }} sats</template>
            </div>
          </button>
          <button v-if="w.state.history.length > historyLimit" class="btn ghost small" @click="historyLimit += 20">Show more</button>
        </section>

        <section class="card">
          <div class="head">
            <h2>🏷 Your username</h2>
            <button v-if="w.state.handle?.username" class="btn small ghost" @click="openUsername">Change</button>
          </div>
          <template v-if="w.state.handle?.username">
            <div class="handle">@{{ w.state.handle.username }}</div>
            <p class="small dim">Friends on Satish can pay <b>@{{ w.state.handle.username }}</b> instead of copying an address.</p>
            <button class="btn small" @click="copy('@' + w.state.handle.username)">{{ copied ? "Copied ✓" : "Copy username" }}</button>
          </template>
          <template v-else>
            <p class="small dim">Pick a username so friends can pay <b>@you</b>, no long addresses.</p>
            <button class="btn primary small" @click="openUsername">Pick a username</button>
          </template>
        </section>

        <section class="card">
          <div class="head">
            <h2>📒 Address book</h2>
            <button class="btn small" @click="openContact()">+ Add</button>
          </div>
          <p v-if="!w.state.contacts.length" class="dim small">
            Save addresses with a name, like "Mum" or "Shop", so you can pay them without copying long addresses.
          </p>
          <button
            v-for="c in contactsPreview"
            :key="c.id"
            class="contact"
            @click="sendToContact(c)"
          >
            <span class="avatar">{{ c.name.charAt(0).toUpperCase() }}</span>
            <span class="who"><b>{{ c.name }}</b><span class="small dim mono">{{ contactLine(c) }}</span></span>
            <span class="small dim">Send →</span>
          </button>
          <button v-if="w.state.contacts.length" class="btn ghost small" @click="openContacts">
            See all ({{ w.state.contacts.length }})
          </button>
        </section>

        <section class="card">
          <h2>Wallet settings</h2>
          <div v-if="w.state.cloudAvailable" class="backup-row">
            <span>
              ☁️ Telegram backup:
              <b :class="w.state.stored.cloud ? 'ok' : 'pending'">{{ w.state.stored.cloud ? "On" : "Off" }}</b>
              <span v-if="w.state.cloudError" class="small err"> · {{ w.state.cloudError }}</span>
            </span>
            <button v-if="!w.state.stored.cloud" class="btn small" @click="go('cloudon')">Turn on</button>
            <button v-else class="btn small ghost" @click="cloudOff">Turn off</button>
          </div>
          <div class="backup-row">
            <span>🔔 Payment alerts in Telegram: <b :class="alerts?.enabled ? 'ok' : 'pending'">{{ alerts === null ? "…" : alerts.enabled ? "On" : "Off" }}</b></span>
            <button v-if="alerts && !alerts.enabled" class="btn small" @click="go('alerts')">Turn on</button>
            <button v-else-if="alerts" class="btn small ghost" :disabled="busy" @click="setAlerts(false)">Turn off</button>
          </div>
          <div class="backup-row">
            <span>🔒 Lock Satish when I leave it: <b :class="lockOn ? 'ok' : 'pending'">{{ lockOn ? "On" : "Off" }}</b></span>
            <button class="btn small" :class="{ ghost: lockOn }" @click="toggleLock">{{ lockOn ? "Turn off" : "Turn on" }}</button>
          </div>
          <div class="stack">
            <button class="btn" @click="go('reveal')">Show recovery phrase</button>
            <button class="btn" @click="go('changepw')">Change password</button>
            <button class="btn" :disabled="!w.state.history.length" @click="exportHistory">Download history (CSV)</button>
            <button class="btn" @click="go('export')">Use this wallet in another app</button>
            <button class="btn" :disabled="!w.spendable.value" @click="moveEverything">Move everything to another wallet</button>
            <NuxtLink class="btn ghost" to="/recovery">How recovery works (and for your family)</NuxtLink>
            <button class="btn ghost danger" @click="go('remove')">Remove wallet from this phone</button>
          </div>
          <p v-if="notice" class="small ok">{{ notice }}</p>
        </section>
      </template>

      <!-- receive -->
      <section v-else-if="view === 'receive'" class="card center">
        <h2>Receive bitcoin</h2>
        <p class="sub">Share this address or QR code. Only send {{ w.net.name === "testnet" ? "test-network " : "" }}bitcoin to it.</p>
        <template v-if="w.receiveAddress.value">
          <div class="qr" v-html="qrSvg" />
          <div class="addr mono">{{ w.receiveAddress.value }}</div>
          <div class="row">
            <button class="btn primary" @click="copy(w.receiveAddress.value!)">{{ copied ? "Copied ✓" : "Copy address" }}</button>
          </div>
          <p class="small dim">A fresh address is shown after each payment, for privacy. Old addresses still work.</p>
          <p v-if="alerts?.enabled" class="small ok">🔔 You'll get a Telegram message when bitcoin arrives here.</p>
        </template>
        <p v-else-if="w.state.loading"><span class="spinner" /> Getting your address…</p>
        <p v-else class="err">{{ w.state.error || "Couldn't get an address. Go back and refresh." }}</p>
        <button class="btn ghost" @click="go('home')">← Back</button>
      </section>

      <!-- username -->
      <section v-else-if="view === 'username'" class="card">
        <h2>{{ w.state.handle?.username ? "Change your username" : "Pick a username" }}</h2>
        <p class="sub">People on Satish can pay you at this name. Each payment still goes to a fresh address in your wallet.</p>
        <label class="field">
          Username
          <div class="inline at">
            <span>@</span>
            <input v-model="usernameInput" maxlength="20" autocapitalize="none" autocomplete="off" spellcheck="false" placeholder="ada" @input="checkName" />
          </div>
          <span v-if="nameStatus" class="small" :class="nameOk ? 'ok' : 'err'">{{ nameStatus }}</span>
        </label>
        <label v-if="!w.state.stored.identityKey" class="field">
          Wallet password
          <input v-model="password" type="password" autocomplete="current-password" />
        </label>
        <p class="small dim">3-20 characters: lowercase letters, numbers and _. Old names stay reserved for 30 days after a change.</p>
        <p v-if="error" class="err">{{ error }}</p>
        <div class="stack">
          <button class="btn primary" :disabled="busy || !nameOk" @click="claimName"><span v-if="busy" class="spinner" /> Save username</button>
          <button class="btn ghost" @click="go('home')">Cancel</button>
        </div>
      </section>

      <!-- request payment -->
      <section v-else-if="view === 'request'" class="card">
        <h2>Request a payment</h2>
        <template v-if="!w.state.handle?.username">
          <p class="sub">Requests show your username, so pick one first.</p>
          <button class="btn primary" @click="openUsername">Pick a username</button>
        </template>
        <template v-else>
          <p class="sub">Get a link you can share on WhatsApp, Telegram or anywhere. Anyone can pay it from any bitcoin wallet.</p>
          <label class="field">
            Amount in sats (optional)
            <input v-model="reqAmount" inputmode="numeric" placeholder="e.g. 5000" />
            <span v-if="naira(Number(reqAmount) || 0)" class="small dim">{{ naira(Number(reqAmount)) }}</span>
          </label>
          <label class="field">What's it for? (optional)<input v-model="reqNote" maxlength="140" placeholder="e.g. rice, rent, school fees" /></label>
          <p v-if="error" class="err">{{ error }}</p>
          <div class="stack">
            <button class="btn primary" :disabled="busy" @click="createRequest"><span v-if="busy" class="spinner" /> Create link</button>
          </div>
        </template>
        <template v-if="myRequests.length">
          <h3 class="small sub-head">Your recent requests</h3>
          <div v-for="q in myRequests" :key="q.id" class="req-row">
            <span>
              <b>{{ q.amount_sats ? q.amount_sats.toLocaleString() + " sats" : "Any amount" }}</b>
              <span v-if="q.note" class="small dim"> · {{ q.note }}</span>
            </span>
            <span class="req-acts">
              <span class="chip" :class="q.status">{{ human(q.status) }}</span>
              <button v-if="q.status === 'open'" class="btn small" @click="showRequest(q)">Share</button>
            </span>
          </div>
        </template>
        <button class="btn ghost" style="margin-top: 14px" @click="go('home')">← Back</button>
      </section>

      <section v-else-if="view === 'requestshow' && shownRequest" class="card center">
        <h2>Share this link</h2>
        <p class="sub">
          {{ shownRequest.amount_sats ? shownRequest.amount_sats.toLocaleString() + " sats" : "Any amount" }}
          <template v-if="naira(shownRequest.amount_sats || 0)"> ({{ naira(shownRequest.amount_sats || 0) }})</template>
          <template v-if="shownRequest.note"> for "{{ shownRequest.note }}"</template>
          · paid to @{{ shownRequest.username }}
        </p>
        <div class="qr" v-html="requestQr" />
        <div class="addr mono">{{ shownRequest.url }}</div>
        <div class="stack">
          <button class="btn primary" @click="shareWhatsApp(shownRequest)">Share on WhatsApp</button>
          <button class="btn" @click="shareTelegram(shownRequest)">Share on Telegram</button>
          <button class="btn" @click="copy(shownRequest.url)">{{ copied ? "Copied ✓" : "Copy link" }}</button>
        </div>
        <p class="small dim">You'll get a Telegram message when it's paid.</p>
        <button class="btn ghost" @click="openRequest">← Back</button>
      </section>

      <!-- buy -->
      <section v-else-if="view === 'buy'" class="card">
        <h2>Buy bitcoin</h2>

        <template v-if="w.net.name === 'testnet'">
          <p class="sub">
            This wallet is on the test network, where coins are free and have no value.
            Get some from a faucet to try sending and receiving.
          </p>
          <div class="stack">
            <button class="btn primary" @click="openExternal('https://mempool.space/testnet4/faucet')">Get free test coins</button>
            <button class="btn" :disabled="!w.receiveAddress.value" @click="copy(w.receiveAddress.value!)">
              {{ copied ? "Copied ✓" : "Copy my address" }}
            </button>
          </div>
        </template>

        <template v-else>
          <p class="sub">
            Satish doesn't sell bitcoin or hold your money. A licensed partner takes your
            payment and sends the bitcoin straight to <b>your</b> wallet.
          </p>

          <div v-if="onramp?.enabled" class="buybox">
            <label class="field">
              Amount ({{ buyFiat }})
              <input v-model="buyAmount" inputmode="decimal" placeholder="e.g. 20000" />
            </label>
            <p class="small dim">You'll see the partners, prices and fees before paying. They may ask for ID.</p>
            <p v-if="error" class="err">{{ error }}</p>
            <button class="btn primary" :disabled="busy || !w.receiveAddress.value" @click="startBuy">
              <span v-if="busy" class="spinner" /> Continue to payment
            </button>
          </div>

          <h3 class="small sect">{{ onramp?.enabled ? "Or buy on an exchange" : "Buy on an exchange" }}</h3>
          <ol class="small steps">
            <li>Copy your wallet address.</li>
            <li>Buy bitcoin on one of these apps with naira.</li>
            <li>Withdraw (send) it to your address. It shows up here once the network confirms it.</li>
          </ol>
          <button class="btn" :disabled="!w.receiveAddress.value" @click="copy(w.receiveAddress.value!)">
            {{ copied ? "Copied ✓" : "Copy my address" }}
          </button>
          <div class="exchanges">
            <button v-for="x in exchanges" :key="x.name" class="exchange" @click="openExternal(x.url)">
              <b>{{ x.name }}</b>
              <span class="small dim">{{ x.note }}</span>
            </button>
          </div>
          <p class="small faint">Satish isn't connected to these companies. Check their fees and rules before buying.</p>
        </template>

        <button class="btn ghost" style="margin-top: 14px" @click="go('home')">← Back</button>
      </section>

      <!-- address book -->
      <section v-else-if="view === 'contacts'" class="card">
        <div class="head">
          <h2>📒 Address book</h2>
          <button class="btn small primary" @click="openContact()">+ Add</button>
        </div>
        <label class="field">
          <input v-model="contactQuery" placeholder="Search names or addresses" autocapitalize="none" autocomplete="off" />
        </label>
        <p v-if="!filteredContacts.length" class="dim small" style="margin-top: 12px">
          {{ w.state.contacts.length ? "No matches." : "No saved addresses yet." }}
        </p>
        <div v-for="c in filteredContacts" :key="c.id" class="contact static">
          <span class="avatar">{{ c.name.charAt(0).toUpperCase() }}</span>
          <span class="who">
            <b>{{ c.name }}</b>
            <span class="small dim mono">{{ contactLine(c) }}</span>
            <span v-if="c.note" class="small dim">{{ c.note }}</span>
          </span>
          <span class="acts">
            <button class="btn small primary" @click="sendToContact(c)">Send</button>
            <button class="btn small" @click="openContact(c)">Edit</button>
          </span>
        </div>
        <button class="btn ghost" style="margin-top: 14px" @click="go('home')">← Back</button>
      </section>

      <section v-else-if="view === 'contact'" class="card">
        <h2>{{ contactForm.id ? "Edit contact" : "New contact" }}</h2>
        <label class="field">Name<input v-model="contactForm.name" maxlength="40" placeholder="e.g. Mum, Chika's shop" /></label>
        <label class="field">
          @username or Bitcoin address
          <div class="inline">
            <input v-model="contactForm.address" autocapitalize="none" autocomplete="off" spellcheck="false" placeholder="@ada or bc1… / tb1…" />
            <button v-if="canScan" class="btn small" type="button" @click="scanQr('contact')">Scan</button>
          </div>
        </label>
        <label class="field">Note (optional)<input v-model="contactForm.note" maxlength="80" placeholder="e.g. rent, school fees" /></label>
        <p v-if="error" class="err">{{ error }}</p>
        <div class="stack">
          <button class="btn primary" @click="saveContact">Save</button>
          <button v-if="contactForm.id" class="btn ghost danger" @click="deleteContact">Delete contact</button>
          <button class="btn ghost" @click="go(contactReturn)">Cancel</button>
        </div>
      </section>

      <!-- send -->
      <section v-else-if="view === 'send'" class="card">
        <h2>Send bitcoin</h2>
        <div v-if="payingRequest" class="paying">
          Paying <b>@{{ payingRequest.username }}</b>'s request<template v-if="payingRequest.note"> for "{{ payingRequest.note }}"</template>
          <span class="verified">✓ verified</span>
        </div>
        <label class="field">
          To (name or Bitcoin address)
          <div class="inline">
            <input v-model="sendTo" autocapitalize="none" autocomplete="off" spellcheck="false" placeholder="Name, bc1… or tb1…" />
            <button v-if="canScan" class="btn small" type="button" @click="scanQr('send')">Scan</button>
          </div>
          <span v-if="recipient.username" class="small ok">→ @{{ recipient.username }}<template v-if="recipient.contact && recipient.contact.name !== '@' + recipient.username"> ({{ recipient.contact.name }})</template> · Satish user</span>
          <span v-else-if="recipient.contact" class="small ok">→ {{ recipient.contact.name }} · {{ contactLine(recipient.contact) }}</span>
          <label v-if="keyChanged" class="check warn">
            <input v-model="acceptKeyChange" type="checkbox" />
            <span>⚠️ @{{ recipient.username }} has a different wallet than last time. Only continue if they told you they changed wallets.</span>
          </label>
        </label>
        <p v-if="payLinkId" class="small">
          That's a Satish payment link. <button class="btn small" type="button" @click="openPayRequest(payLinkId)">Open it</button>
        </p>
        <div v-if="sendSuggestions.length" class="chips">
          <button v-for="c in sendSuggestions" :key="c.id" type="button" class="chip-btn" @click="sendTo = c.name">
            {{ c.name }}
          </button>
        </div>
        <label class="field">
          Amount (sats)
          <div class="inline">
            <input v-model="sendAmount" inputmode="numeric" :disabled="sendMax" placeholder="e.g. 10000" />
            <button class="btn small" type="button" :class="{ primary: sendMax }" @click="sendMax = !sendMax">Max</button>
          </div>
          <span class="small dim">
            Available: {{ w.spendable.value.toLocaleString() }} sats
            <template v-if="naira(w.spendable.value)"> ({{ naira(w.spendable.value) }})</template>
            <template v-if="!sendMax && naira(Number(sendAmount) || 0)"> · sending {{ naira(Number(sendAmount)) }}</template>
          </span>
        </label>
        <div class="field">
          Network fee
          <div class="fees">
            <button
              v-for="opt in feeOptions"
              :key="opt.key"
              type="button"
              class="btn small"
              :class="{ primary: feeChoice === opt.key }"
              @click="feeChoice = opt.key"
            >
              {{ opt.label }}<span class="small dim"> · {{ opt.rate }} sat/vB</span>
            </button>
          </div>
          <span class="small dim">Faster fees confirm sooner. Most payments confirm within an hour on "Normal". You can speed it up later if it gets stuck.</span>
        </div>
        <label class="field">Note for yourself (optional)<input v-model="sendNote" maxlength="120" placeholder="e.g. rent, rice, school fees" /></label>
        <p v-if="error" class="err">{{ error }}</p>
        <div class="stack">
          <button class="btn primary" :disabled="!feeRates" @click="review">Review</button>
          <button class="btn ghost" @click="go('home')">Cancel</button>
        </div>
      </section>

      <!-- review -->
      <section v-else-if="view === 'review' && planned" class="card">
        <h2>Check before sending</h2>
        <div class="summary">
          <div>
            <span>To</span>
            <b>
              <template v-if="plannedUsername">@{{ plannedUsername }} <span class="verified">✓ verified</span><br /></template>
              <template v-else-if="plannedContact">{{ plannedContact.name }}<br /></template>
              <span class="mono">{{ planned.to }}</span>
            </b>
          </div>
          <div><span>Amount</span><b>{{ planned.amount.toLocaleString() }} sats<small v-if="naira(planned.amount)" class="ngn">{{ naira(planned.amount) }}</small></b></div>
          <div><span>Network fee</span><b>{{ planned.fee.toLocaleString() }} sats<small v-if="naira(planned.fee)" class="ngn">{{ naira(planned.fee) }}</small></b></div>
          <div class="total"><span>Total</span><b>{{ (planned.amount + planned.fee).toLocaleString() }} sats<small v-if="naira(planned.amount + planned.fee)" class="ngn">{{ naira(planned.amount + planned.fee) }}</small></b></div>
        </div>
        <p class="small dim">Bitcoin payments can't be reversed. Check the address carefully.</p>
        <div v-if="warnings.length" class="warnbox">
          <p v-for="m in warnings" :key="m" class="small">⚠️ {{ m }}</p>
          <label class="check"><input v-model="warningsOk" type="checkbox" /> <span>I've checked, send it</span></label>
        </div>
        <label class="field">Wallet password<input v-model="password" type="password" autocomplete="current-password" /></label>
        <p v-if="error" class="err">{{ error }}</p>
        <button class="linkish small" @click="go('forgot')">Forgot your password?</button>
        <div class="stack">
          <button class="btn primary" :disabled="busy || !password || (warnings.length > 0 && !warningsOk)" @click="confirmSend">
            <span v-if="busy" class="spinner" /> Send now
          </button>
          <button class="btn ghost" :disabled="busy" @click="go('send')">← Edit</button>
        </div>
      </section>

      <!-- sent -->
      <section v-else-if="view === 'sent'" class="card center">
        <div class="big-icon">✅</div>
        <h2>Sent</h2>
        <p class="sub">Your payment is on its way. It usually confirms within an hour.</p>
        <a class="btn" :href="w.explorerTx(sentTxid)" target="_blank" rel="noopener">View on mempool.space</a>
        <div v-if="!plannedContact && !plannedUsername && planned" class="save-box">
          <div class="small">Save this address for next time?</div>
          <div class="inline">
            <input v-model="saveName" maxlength="40" placeholder="Name, e.g. Tunde" />
            <button class="btn small" @click="saveSentAddress">Save</button>
          </div>
          <p v-if="error" class="err">{{ error }}</p>
        </div>
        <p v-else-if="savedNote" class="small ok">{{ savedNote }}</p>
        <button class="btn primary" @click="go('home')">Done</button>
      </section>

      <!-- transaction details -->
      <section v-else-if="view === 'tx' && txItem" class="card">
        <h2>{{ txItem.amount >= 0 ? "Received" : "Sent" }}</h2>
        <div class="summary">
          <div><span>Amount</span><b>{{ Math.abs(txItem.amount).toLocaleString() }} sats<small v-if="naira(Math.abs(txItem.amount))" class="ngn">{{ naira(Math.abs(txItem.amount)) }}</small></b></div>
          <div v-if="txItem.amount < 0"><span>Network fee</span><b>{{ txItem.fee.toLocaleString() }} sats</b></div>
          <div><span>Status</span><b :class="txItem.confirmed ? 'ok' : 'pending'">{{ txItem.confirmed ? "Confirmed" : "Waiting to confirm" }}</b></div>
          <div v-if="txItem.time"><span>When</span><b>{{ fmtTime(txItem.time) }}</b></div>
        </div>
        <label class="field">
          Note (only you see this)
          <div class="inline">
            <input v-model="txNote" maxlength="120" placeholder="e.g. rent, rice" />
            <button class="btn small" @click="saveTxNote">{{ noteSaved ? "Saved ✓" : "Save" }}</button>
          </div>
        </label>
        <template v-if="!txItem.confirmed && txItem.amount < 0">
          <div v-if="txItem.replaceable" class="stuck">
            <p class="small">Taking too long? You can pay a higher fee so it confirms sooner, or cancel it while it's still waiting.</p>
            <div class="row">
              <button class="btn primary" @click="startBump('speed')">⚡ Speed up</button>
              <button class="btn" @click="startBump('cancel')">✕ Cancel payment</button>
            </div>
          </div>
          <p v-else class="small dim">This payment can't be changed from here. It will confirm when the network has room.</p>
        </template>
        <p v-else-if="!txItem.confirmed" class="small dim">
          Incoming payments confirm when the network has room, usually within an hour. If it takes days, ask the sender to speed it up.
        </p>
        <p v-if="error" class="err">{{ error }}</p>
        <div class="stack">
          <a class="btn" :href="w.explorerTx(txItem.txid)" target="_blank" rel="noopener">View on mempool.space</a>
          <button class="btn ghost" @click="go('home')">← Back</button>
        </div>
      </section>

      <!-- speed up / cancel -->
      <section v-else-if="view === 'bump'" class="card">
        <h2>{{ bumpKind === "speed" ? "Speed up payment" : "Cancel payment" }}</h2>
        <p class="sub">
          <template v-if="bumpKind === 'speed'">The same payment is sent again with a higher fee, so miners pick it up sooner. The person still gets exactly the same amount.</template>
          <template v-else>The payment is replaced by one that sends your bitcoin back to you. This only works while it's still waiting, and costs a network fee.</template>
        </p>
        <div class="field">
          New fee
          <div class="fees">
            <button v-for="opt in feeOptions.slice(0, 2)" :key="opt.key" type="button" class="btn small" :class="{ primary: bumpFee === opt.key }" @click="bumpFee = opt.key; planBumpNow()">
              {{ opt.label }}<span class="small dim"> · {{ opt.rate }} sat/vB</span>
            </button>
          </div>
        </div>
        <div v-if="bumpPlan" class="summary">
          <div><span>Old fee</span><b>{{ bumpPlan.oldFee.toLocaleString() }} sats · {{ bumpPlan.oldFeeRate }} sat/vB</b></div>
          <div><span>New fee</span><b>{{ bumpPlan.fee.toLocaleString() }} sats · {{ bumpPlan.feeRate }} sat/vB</b></div>
          <div class="total"><span>Extra cost</span><b>{{ bumpPlan.extraFee.toLocaleString() }} sats<small v-if="naira(bumpPlan.extraFee)" class="ngn">{{ naira(bumpPlan.extraFee) }}</small></b></div>
          <div v-if="bumpKind === 'cancel'"><span>Comes back to you</span><b>{{ bumpPlan.outputs[0].value.toLocaleString() }} sats</b></div>
        </div>
        <p v-else-if="!error" class="small dim"><span class="spinner" /> Working it out…</p>
        <label v-if="bumpPlan" class="field">Wallet password<input v-model="password" type="password" autocomplete="current-password" /></label>
        <p v-if="error" class="err">{{ error }}</p>
        <div class="stack">
          <button class="btn primary" :disabled="busy || !bumpPlan || !password" @click="confirmBump">
            <span v-if="busy" class="spinner" /> {{ bumpKind === "speed" ? "Speed it up" : "Cancel it" }}
          </button>
          <button class="btn ghost" :disabled="busy" @click="go('tx')">← Back</button>
        </div>
      </section>

      <!-- payment alerts -->
      <section v-else-if="view === 'alerts'" class="card">
        <h2>🔔 Payment alerts</h2>
        <p class="sub">
          Get a Telegram message when bitcoin arrives, even when Satish is closed, and
          another when it's confirmed.
        </p>
        <p class="small dim">
          To do this, Satish's server watches the receive addresses this phone shows you
          (and the ones it gives out for your @username). It never gets your keys or your
          whole wallet, and can never move your money. Turn alerts off any time and the
          addresses are forgotten.
        </p>
        <p v-if="error" class="err">{{ error }}</p>
        <div class="stack">
          <button class="btn primary" :disabled="busy" @click="setAlerts(true)"><span v-if="busy" class="spinner" /> Turn on alerts</button>
          <button class="btn ghost" @click="go('home')">Not now</button>
        </div>
      </section>

      <!-- export to other wallets -->
      <section v-else-if="view === 'export'" class="card">
        <h2>Use this wallet in another app</h2>
        <p class="sub">
          Satish uses the common standard (BIP84, native SegWit), so your 12 words also
          work in Sparrow, BlueWallet, Nunchuk, Electrum and others. You're never locked in.
        </p>
        <template v-if="!descriptors">
          <p class="small dim">
            To <b>watch</b> your balance in another app without letting it spend, use your
            public wallet key. Enter your password to show it.
          </p>
          <label class="field">Wallet password<input v-model="password" type="password" autocomplete="current-password" /></label>
          <p v-if="error" class="err">{{ error }}</p>
          <div class="stack">
            <button class="btn primary" :disabled="busy || !password" @click="showDescriptors"><span v-if="busy" class="spinner" /> Show public key</button>
            <button class="btn ghost" @click="go('home')">← Back</button>
          </div>
        </template>
        <template v-else>
          <p class="small dim">Public key ({{ descriptors.path }}, fingerprint {{ descriptors.fingerprint }}). It can see your balance but can't spend.</p>
          <div class="addr mono">{{ descriptors.xpub }}</div>
          <button class="btn small" @click="copy(descriptors.xpub)">{{ copied ? "Copied ✓" : "Copy public key" }}</button>
          <p class="small dim" style="margin-top: 12px">Or as a descriptor (Sparrow, Bitcoin Core):</p>
          <div class="addr mono">{{ descriptors.receive }}</div>
          <button class="btn small" @click="copy(descriptors.receive)">Copy descriptor</button>
          <p class="small dim">To spend from another app, restore it there with your 12 words and choose "Native SegWit".</p>
          <button class="btn ghost" style="margin-top: 14px" @click="go('home')">Done</button>
        </template>
      </section>

      <!-- forgot password -->
      <section v-else-if="view === 'forgot'" class="card">
        <h2>Forgot your password?</h2>
        <p class="sub">
          Satish can't reset it: only you can unlock your wallet. But your bitcoin isn't lost
          if you have your 12-word recovery phrase.
        </p>
        <ol class="small steps">
          <li>Find the paper with your 12 words.</li>
          <li>Tap "Remove and restore" below. This only removes the wallet from this phone; your bitcoin stays on the network.</li>
          <li>Choose "I already have a recovery phrase", type the 12 words, and set a new password.</li>
        </ol>
        <p class="small dim">No 12 words? Keep trying passwords you might have used. Without the password or the words, nobody can recover the wallet, not even Satish.</p>
        <label class="check"><input v-model="wroteDown" type="checkbox" /> I have my 12 words with me</label>
        <div class="stack">
          <button class="btn danger" :disabled="!wroteDown" @click="removeAndRestore">Remove and restore</button>
          <button class="btn ghost" @click="go('home')">← Back</button>
        </div>
      </section>

      <!-- reveal phrase -->
      <section v-else-if="view === 'reveal'" class="card">
        <h2>Your recovery phrase</h2>
        <template v-if="!shownWords.length">
          <p class="sub">Enter your wallet password. Make sure nobody can see your screen.</p>
          <label class="field">Wallet password<input v-model="password" type="password" autocomplete="current-password" /></label>
          <p v-if="error" class="err">{{ error }}</p>
          <div class="stack">
            <button class="btn primary" :disabled="busy || !password" @click="reveal">
              <span v-if="busy" class="spinner" /> Show
            </button>
            <button class="btn ghost" @click="go('home')">Cancel</button>
          </div>
        </template>
        <template v-else>
          <div class="words">
            <div v-for="(word, i) in shownWords" :key="i" class="word"><span>{{ i + 1 }}</span>{{ word }}</div>
          </div>
          <button class="btn primary" @click="go('home')">Done</button>
        </template>
      </section>

      <!-- change password -->
      <section v-else-if="view === 'changepw'" class="card">
        <h2>Change wallet password</h2>
        <label class="field">Current password<input v-model="password" type="password" autocomplete="current-password" /></label>
        <label class="field">New password<input v-model="pw1" type="password" autocomplete="new-password" /></label>
        <label class="field">Type it again<input v-model="pw2" type="password" autocomplete="new-password" /></label>
        <p v-if="error" class="err">{{ error }}</p>
        <div class="stack">
          <button class="btn primary" :disabled="busy" @click="changePw"><span v-if="busy" class="spinner" /> Save</button>
          <button class="btn ghost" @click="go('home')">Cancel</button>
        </div>
      </section>

      <!-- turn on backup -->
      <section v-else-if="view === 'cloudon'" class="card">
        <h2>Back up to Telegram</h2>
        <p class="sub">
          Your wallet and address book are saved to your own Telegram account, locked with
          your wallet password. If you change phones, open Satish and restore with the password.
          Keep your 12 words too: they work even without Telegram.
        </p>
        <label class="field">Wallet password<input v-model="password" type="password" autocomplete="current-password" /></label>
        <p v-if="error" class="err">{{ error }}</p>
        <div class="stack">
          <button class="btn primary" :disabled="busy || !password" @click="cloudOn"><span v-if="busy" class="spinner" /> Turn on backup</button>
          <button class="btn ghost" @click="go('home')">Cancel</button>
        </div>
      </section>

      <!-- remove -->
      <section v-else-if="view === 'remove'" class="card">
        <h2>Remove wallet from this phone?</h2>
        <p class="sub">
          Your bitcoin stays safe on the network, but this phone will no longer have
          access. You'll need your 12-word recovery phrase to get it back.
          Without it, your bitcoin is lost forever.
        </p>
        <label class="check"><input v-model="wroteDown" type="checkbox" /> I have my recovery phrase written down</label>
        <label v-if="w.state.stored.cloud" class="check">
          <input v-model="alsoCloud" type="checkbox" /> Also delete my Telegram backup
        </label>
        <div class="stack">
          <button class="btn danger" :disabled="!wroteDown" @click="removeWallet">Remove wallet</button>
          <button class="btn ghost" @click="go('home')">Cancel</button>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { renderSVG } from "uqr";
import type { PaymentRequestOut } from "@xp/api-client";
import {
  SendError, WrongPassword, checkAddress, verifyPoolAddress, isValidPhrase, newRecoveryPhrase, normalizePhrase,
  parsePaymentRequest, satsToBtc, resolveRecipient, searchContacts, normalizeUsername, usernameProblem,
  type BumpPlan, type Contact, type FeeRates, type SendPlan,
} from "~/lib/wallet-core";

const w = useWallet();
const { naira } = usePrice();
type View = "tx" | "bump" | "alerts" | "export" | "forgot" | "welcome" | "show" | "verify" | "restore" | "password" | "home" | "receive" | "send" | "review" | "sent" | "reveal" | "changepw" | "remove" | "contacts" | "contact" | "buy" | "cloudrestore" | "cloudon" | "username" | "request" | "requestshow";
const view = ref<View>(w.state.stored ? "home" : "welcome");
const error = ref("");
const busy = ref(false);

const total = computed(() => w.confirmed.value + w.pending.value);
const config = useRuntimeConfig();
const betaLimit = computed(() => Number(config.public.walletBetaLimitSats || 1_000_000));
const historyLimit = ref(20);
const notice = ref("");

function ago(t: number) {
  const m = Math.round((Date.now() - t) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h} h ago` : new Date(t).toLocaleDateString();
}

// ---- transaction details, notes, speed up / cancel
const txId = ref("");
const txItem = computed(() => w.state.history.find((t) => t.txid === txId.value) ?? null);
const txNote = ref("");
const noteSaved = ref(false);
const bumpKind = ref<"speed" | "cancel">("speed");
const bumpFee = ref<"fast" | "normal">("fast");
const bumpPlan = ref<BumpPlan | null>(null);

function openTx(txid: string) {
  txId.value = txid;
  txNote.value = w.state.notes[txid] ?? "";
  noteSaved.value = false;
  go("tx");
}

function saveTxNote() {
  w.setNote(txId.value, txNote.value);
  noteSaved.value = true;
  setTimeout(() => (noteSaved.value = false), 1500);
}

async function startBump(kind: "speed" | "cancel") {
  bumpKind.value = kind;
  bumpFee.value = "fast";
  bumpPlan.value = null;
  go("bump");
  try {
    feeRates.value = await w.fees();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Couldn't get network fees.";
    return;
  }
  await planBumpNow();
}

async function planBumpNow() {
  error.value = "";
  bumpPlan.value = null;
  try {
    const rate = feeRates.value ? feeRates.value[bumpFee.value] : 5;
    bumpPlan.value = await w.planReplace(txId.value, bumpKind.value, rate);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Couldn't work out the new fee.";
  }
}

async function confirmBump() {
  if (!bumpPlan.value) return;
  busy.value = true;
  error.value = "";
  try {
    const kind = bumpKind.value;
    sentTxid.value = await w.sendReplace(bumpPlan.value, password.value);
    password.value = "";
    txId.value = sentTxid.value;
    notice.value = kind === "speed" ? "Sped up ✓ It should confirm sooner now." : "Cancelled ✓ Your bitcoin is coming back to you.";
    go("home");
  } catch (e) {
    error.value = e instanceof WrongPassword ? "Wrong password." : e instanceof Error ? e.message : "That didn't work. Nothing was changed.";
  } finally {
    busy.value = false;
  }
}

// ---- payment alerts
const alerts = ref<{ enabled: boolean; watched: number } | null>(null);

async function loadAlerts() {
  try {
    alerts.value = await api.alertsStatus(w.net.name);
    if (alerts.value.enabled) watchReceive();
  } catch {
    alerts.value = null;
  }
}

function alertAddresses(): string[] {
  return w.state.addresses.filter((a) => a.change === 0 && a.index < 1000 && a.txCount === 0).sort((a, b) => a.index - b.index).slice(0, 3).map((a) => a.address);
}

function watchReceive() {
  const list = alertAddresses();
  if (alerts.value?.enabled && list.length) api.alertsWatch({ network: w.net.name, addresses: list }).catch(() => undefined);
}

async function setAlerts(on: boolean) {
  busy.value = true;
  error.value = "";
  try {
    alerts.value = await api.alertsSet({ network: w.net.name, enabled: on, addresses: on ? alertAddresses() : [] });
    notice.value = on ? "Payment alerts are on ✓" : "Payment alerts are off. Watched addresses were forgotten.";
    go("home");
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Couldn't change alerts.";
  } finally {
    busy.value = false;
  }
}

// ---- lock
const LOCK_AFTER_MS = 5 * 60 * 1000;
const lockKey = () => `xp_lock_v1_${(window as any).Telegram?.WebApp?.initDataUnsafe?.user?.id ?? "local"}`;
const lockOn = ref(false);
const locked = ref(false);
let hiddenAt = 0;
try {
  lockOn.value = localStorage.getItem(lockKey()) === "1";
  locked.value = lockOn.value && !!w.state.stored;
} catch {
  /* storage blocked: no lock */
}

function toggleLock() {
  lockOn.value = !lockOn.value;
  try {
    localStorage.setItem(lockKey(), lockOn.value ? "1" : "0");
  } catch {
    /* ignore */
  }
  notice.value = lockOn.value ? "Satish will ask for your password each time you open it, and after 5 minutes away." : "Lock is off.";
}

async function unlock() {
  busy.value = true;
  error.value = "";
  try {
    await w.revealPhrase(password.value);
    password.value = "";
    locked.value = false;
  } catch {
    error.value = "Wrong password.";
  } finally {
    busy.value = false;
  }
}

function onVisibility() {
  if (document.hidden) hiddenAt = Date.now();
  else if (lockOn.value && hiddenAt && Date.now() - hiddenAt > LOCK_AFTER_MS && w.state.stored) {
    locked.value = true;
    void ln.close(); // keys leave memory while locked
    view.value = "home";
  }
}

// ---- exports
const descriptors = ref<{ receive: string; change: string; xpub: string; path: string; fingerprint: string } | null>(null);

async function showDescriptors() {
  busy.value = true;
  error.value = "";
  try {
    descriptors.value = await w.exportDescriptors(password.value);
    password.value = "";
  } catch {
    error.value = "Wrong password.";
  } finally {
    busy.value = false;
  }
}

async function exportHistory() {
  const csv = w.exportCsv();
  const name = `satish-history-${new Date().toISOString().slice(0, 10)}.csv`;
  try {
    const file = new File([csv], name, { type: "text/csv" });
    if ((navigator as any).canShare?.({ files: [file] })) {
      await (navigator as any).share({ files: [file], title: "Satish history" });
      return;
    }
    const url = URL.createObjectURL(file);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    notice.value = "History downloaded.";
  } catch {
    await copy(csv);
    notice.value = "Couldn't download here, so the history was copied. Paste it into a spreadsheet.";
  }
}

const ln = useLightning();

async function payOnchainTo(address: string) {
  await openSend();
  sendTo.value = address;
  sendNote.value = "Moved to Lightning";
}

async function moveEverything() {
  await openSend();
  sendMax.value = true;
  sendNote.value = "Moved to my other wallet";
}

async function removeAndRestore() {
  await ln.forget();
  await w.remove({ alsoCloud: false });
  locked.value = false;
  go("restore");
}

// setup
const phrase = ref("");
const words = computed(() => phrase.value.split(" "));
const revealed = ref(false);
const wroteDown = ref(false);
const quiz = ref<number[]>([]);
const answers = ref<string[]>([]);
const restoreText = ref("");
const pw1 = ref("");
const pw2 = ref("");
const cloudOpt = ref(true);
const alsoCloud = ref(false);

// send
const sendTo = ref("");
const sendAmount = ref("");
const sendMax = ref(false);
const feeRates = ref<FeeRates | null>(null);
const feeChoice = ref<"fast" | "normal" | "slow">("normal");
const planned = ref<SendPlan | null>(null);
const password = ref("");
const sentTxid = ref("");
const plannedContact = ref<Contact | null>(null);
const plannedUsername = ref("");
const plannedIdentity = ref("");
const keyChanged = ref(false);
const acceptKeyChange = ref(false);
const sendNote = ref("");
const warningsOk = ref(false);
const payLinkId = computed(() => sendTo.value.trim().match(/\/pay\/([A-Za-z0-9_-]{6,24})(?:[?#].*)?$/)?.[1] ?? "");
const warnings = computed(() => {
  const p = planned.value;
  if (!p) return [] as string[];
  const out: string[] = [];
  const known = !!plannedContact.value || !!plannedUsername.value;
  if (!known) out.push("You haven't paid this address before. Check the first and last few characters with the person.");
  const bal = w.spendable.value;
  if (bal > 0 && p.amount + p.fee >= bal * 0.5 && p.amount >= 100_000) out.push(`This is a big payment: ${Math.round(((p.amount + p.fee) / bal) * 100)}% of your balance.`);
  if (p.fee > p.amount * 0.2) out.push(`The network fee is more than 20% of the amount you're sending.`);
  return out;
});

// username
const usernameInput = ref("");
const nameStatus = ref("");
const nameOk = ref(false);
let nameTimer: ReturnType<typeof setTimeout> | null = null;

function openUsername() {
  usernameInput.value = w.state.handle?.username ?? "";
  nameStatus.value = "";
  nameOk.value = false;
  go("username");
}

function checkName() {
  const name = normalizeUsername(usernameInput.value);
  usernameInput.value = name;
  nameOk.value = false;
  if (nameTimer) clearTimeout(nameTimer);
  const local = usernameProblem(name);
  if (local) {
    nameStatus.value = name ? local : "";
    return;
  }
  if (name === w.state.handle?.username) {
    nameStatus.value = "That's your current username.";
    return;
  }
  nameStatus.value = "Checking…";
  nameTimer = setTimeout(async () => {
    try {
      const res = await api.handleCheck(name, w.net.name);
      if (normalizeUsername(usernameInput.value) !== name) return;
      nameOk.value = res.available;
      nameStatus.value = res.available ? `@${name} is available ✓` : res.reason || "Not available.";
    } catch (e) {
      nameStatus.value = e instanceof Error ? e.message : "Couldn't check that name.";
    }
  }, 350);
}

async function claimName() {
  busy.value = true;
  error.value = "";
  try {
    await w.claimUsername(usernameInput.value, password.value || undefined);
    password.value = "";
    go("home");
  } catch (e) {
    error.value = e instanceof WrongPassword ? "Wrong password." : e instanceof Error ? e.message : "Couldn't save the username.";
  } finally {
    busy.value = false;
  }
}

// payment requests
const reqAmount = ref("");
const reqNote = ref("");
const myRequests = ref<PaymentRequestOut[]>([]);
const shownRequest = ref<PaymentRequestOut | null>(null);
const requestQr = computed(() =>
  shownRequest.value ? renderSVG(shownRequest.value.url, { border: 2, whiteColor: "#ffffff", blackColor: "#0b0e11" }) : "",
);

async function openRequest() {
  reqAmount.value = "";
  reqNote.value = "";
  go("request");
  try {
    myRequests.value = (await api.listRequests()).filter((q) => q.network === w.net.name).slice(0, 8);
  } catch {
    myRequests.value = [];
  }
}

async function createRequest() {
  error.value = "";
  const amount = reqAmount.value ? Number(reqAmount.value.replace(/[,\s]/g, "")) : undefined;
  if (amount !== undefined && (!Number.isInteger(amount) || amount < 546)) {
    error.value = "Enter a whole number of sats, at least 546 (or leave it empty).";
    return;
  }
  busy.value = true;
  try {
    const q = await api.createRequest({ network: w.net.name, amount_sats: amount, note: reqNote.value || undefined });
    w.refresh();
    showRequest(q);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Couldn't create the request.";
  } finally {
    busy.value = false;
  }
}

function showRequest(q: PaymentRequestOut) {
  shownRequest.value = q;
  go("requestshow");
}

function shareText(q: PaymentRequestOut) {
  const amt = q.amount_sats ? `${q.amount_sats.toLocaleString()} sats` : "a payment";
  return `@${q.username} is requesting ${amt}${q.note ? ` for ${q.note}` : ""}. Pay with bitcoin:`;
}

function shareWhatsApp(q: PaymentRequestOut) {
  openExternal(`https://wa.me/?text=${encodeURIComponent(shareText(q) + " " + q.url)}`);
}

function shareTelegram(q: PaymentRequestOut) {
  const url = `https://t.me/share/url?url=${encodeURIComponent(q.url)}&text=${encodeURIComponent(shareText(q))}`;
  const tg = (window as any).Telegram?.WebApp;
  if (tg?.openTelegramLink) tg.openTelegramLink(url);
  else openExternal(url);
}

function contactLine(c: Contact) {
  if (c.username) return c.name.toLowerCase() === "@" + c.username ? "Satish user" : `@${c.username}`;
  return shortAddr(c.address);
}
const saveName = ref("");
const savedNote = ref("");

const payingRequest = ref<PaymentRequestOut | null>(null);

// buy
const api = useXpApi();
const onramp = ref<{ enabled: boolean; default_fiat: string } | null>(null);
const buyAmount = ref("");
const buyFiat = computed(() => onramp.value?.default_fiat ?? "NGN");
const exchanges = [
  { name: "Yellow Card", url: "https://yellowcard.io", note: "Pay by bank transfer in naira" },
  { name: "Quidax", url: "https://www.quidax.com", note: "Nigerian exchange, naira deposits" },
  { name: "Busha", url: "https://www.busha.co", note: "Nigerian exchange, naira deposits" },
  { name: "Bitnob", url: "https://bitnob.com", note: "Bitcoin app built in Africa" },
];

function openExternal(url: string) {
  const tg = (window as any).Telegram?.WebApp;
  if (tg?.openLink) tg.openLink(url);
  else window.open(url, "_blank", "noopener");
}

async function openBuy() {
  error.value = "";
  go("buy");
  if (!w.receiveAddress.value && !w.state.loading) w.refresh();
  if (w.net.name === "mainnet" && !onramp.value) {
    try {
      onramp.value = await api.onrampStatus();
    } catch {
      onramp.value = { enabled: false, default_fiat: "NGN" };
    }
  }
}

async function startBuy() {
  error.value = "";
  const amount = Number(buyAmount.value.replace(/[,\s]/g, ""));
  if (buyAmount.value && (!Number.isFinite(amount) || amount <= 0)) {
    error.value = "Enter a valid amount.";
    return;
  }
  busy.value = true;
  try {
    const link = await api.onrampLink({ address: w.receiveAddress.value!, fiat: buyFiat.value, amount: amount || undefined });
    openExternal(link.url);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Couldn't start the purchase. Try again.";
  } finally {
    busy.value = false;
  }
}

// address book
const contactQuery = ref("");
const contactForm = reactive({ id: "" as string | undefined, name: "", address: "", note: "" });
const contactReturn = ref<View>("contacts");
const contactsPreview = computed(() => searchContacts(w.state.contacts, "").slice(0, 3));
const filteredContacts = computed(() => searchContacts(w.state.contacts, contactQuery.value));
const recipient = computed(() => resolveRecipient(w.state.contacts, sendTo.value));
const sendSuggestions = computed(() => {
  const q = sendTo.value.trim();
  if (recipient.value.contact) return [];
  if (q.length > 25) return [];
  return searchContacts(w.state.contacts, q).slice(0, 6);
});

function shortAddr(a: string) {
  return a.length > 20 ? `${a.slice(0, 10)}…${a.slice(-8)}` : a;
}

function openContacts() {
  contactQuery.value = "";
  go("contacts");
}

function openContact(c?: Contact) {
  contactReturn.value = view.value === "contacts" ? "contacts" : "home";
  contactForm.id = c?.id;
  contactForm.name = c?.name ?? "";
  contactForm.address = c?.address ?? "";
  contactForm.note = c?.note ?? "";
  go("contact");
}

function saveContact() {
  error.value = w.saveContact({ id: contactForm.id, name: contactForm.name, address: contactForm.address, note: contactForm.note });
  if (!error.value) go(contactReturn.value);
}

function deleteContact() {
  if (!contactForm.id) return;
  if (!window.confirm(`Delete "${contactForm.name}" from your address book?`)) return;
  w.deleteContact(contactForm.id);
  go(contactReturn.value);
}

async function sendToContact(c: Contact) {
  await openSend();
  sendTo.value = c.username ? "@" + c.username : c.name;
}

function saveSentAddress() {
  if (!planned.value) return;
  error.value = w.saveContact({ name: saveName.value, address: planned.value.to });
  if (!error.value) {
    savedNote.value = `Saved as "${saveName.value.trim()}".`;
    plannedContact.value = w.state.contacts.find((c) => c.address === planned.value!.to) ?? null;
  }
}

// misc
const copied = ref(false);
const shownWords = ref<string[]>([]);
const unit = computed(() => (w.net.name === "testnet" ? "tBTC" : "BTC"));
const canScan = computed(() => !!(window as any).Telegram?.WebApp?.showScanQrPopup);

const qrSvg = computed(() =>
  w.receiveAddress.value
    ? renderSVG("bitcoin:" + w.receiveAddress.value.toUpperCase(), { border: 2, whiteColor: "#ffffff", blackColor: "#0b0e11" })
    : "",
);

const feeOptions = computed(() => {
  const f = feeRates.value;
  return [
    { key: "fast" as const, label: "Fast", rate: f?.fast ?? "…" },
    { key: "normal" as const, label: "Normal", rate: f?.normal ?? "…" },
    { key: "slow" as const, label: "Slow", rate: f?.slow ?? "…" },
  ];
});

function go(v: View) {
  error.value = "";
  password.value = "";
  if (v !== "reveal") shownWords.value = [];
  if (v !== "remove" && v !== "show" && v !== "forgot") wroteDown.value = false;
  if (v !== "export") descriptors.value = null;
  if (v !== "home") notice.value = "";
  view.value = v;
  window.scrollTo?.({ top: 0 });
}

function fmtBtc(sats: number) {
  return satsToBtc(sats);
}
function fmtTime(t?: number) {
  return t ? new Date(t * 1000).toLocaleString() : "";
}

function startCreate() {
  phrase.value = newRecoveryPhrase(12);
  revealed.value = false;
  wroteDown.value = false;
  go("show");
}

function startVerify() {
  const picks = new Set<number>();
  while (picks.size < 3) picks.add(Math.floor(Math.random() * 12));
  quiz.value = [...picks].sort((a, b) => a - b);
  answers.value = ["", "", ""];
  go("verify");
}

function checkQuiz() {
  const ok = quiz.value.every((q, i) => answers.value[i]?.trim().toLowerCase() === words.value[q]);
  if (!ok) {
    error.value = "One or more words don't match. Check your paper and try again.";
    return;
  }
  pw1.value = pw2.value = "";
  go("password");
}

function checkRestore() {
  const clean = normalizePhrase(restoreText.value);
  const n = clean.split(" ").length;
  if (n !== 12 && n !== 24) {
    error.value = `That's ${n} words. A recovery phrase has 12 or 24.`;
    return;
  }
  if (!isValidPhrase(clean)) {
    error.value = "That phrase isn't valid. Check the spelling and the order of the words.";
    return;
  }
  phrase.value = clean;
  restoreText.value = "";
  pw1.value = pw2.value = "";
  go("password");
}

function passwordProblem(a: string, b: string): string {
  if (a.length < 8) return "Use at least 8 characters.";
  if (a !== b) return "The passwords don't match.";
  return "";
}

async function finishSetup() {
  error.value = passwordProblem(pw1.value, pw2.value);
  if (error.value) return;
  busy.value = true;
  try {
    await w.save(phrase.value, pw1.value, { cloud: cloudOpt.value && w.state.cloudAvailable });
    void w.loadHandle();
    phrase.value = "";
    pw1.value = pw2.value = "";
    go("home");
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Couldn't create the wallet.";
  } finally {
    busy.value = false;
  }
}

function cancelSetup() {
  phrase.value = "";
  restoreText.value = "";
  go("welcome");
}

async function openSend() {
  payingRequest.value = null;
  plannedContact.value = null;
  plannedUsername.value = "";
  keyChanged.value = false;
  acceptKeyChange.value = false;
  sendTo.value = "";
  sendAmount.value = "";
  sendMax.value = false;
  sendNote.value = "";
  planned.value = null;
  go("send");
  try {
    feeRates.value = await w.fees();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Couldn't get network fees.";
  }
}

function scanQr(target: "send" | "contact") {
  const tg = (window as any).Telegram?.WebApp;
  tg?.showScanQrPopup?.({ text: "Scan a Bitcoin address" }, (text: string) => {
    const req = parsePaymentRequest(text);
    if (target === "contact") {
      contactForm.address = req.address;
      if (req.label && !contactForm.name) contactForm.name = req.label;
    } else {
      sendTo.value = req.address;
      if (req.amountSats) sendAmount.value = String(req.amountSats);
    }
    return true;
  });
}

async function review() {
  error.value = "";
  if (w.state.loading || !w.state.live) {
    error.value = "Your wallet is still updating. Try again in a moment.";
    if (!w.state.loading) void w.refresh();
    return;
  }
  const req = resolveRecipient(w.state.contacts, sendTo.value);
  if (req.amountSats && !sendAmount.value) sendAmount.value = String(req.amountSats);
  plannedUsername.value = "";
  plannedIdentity.value = "";
  if (req.username) {
    try {
      const got = await w.resolveUsername(req.username);
      keyChanged.value = got.changed;
      if (got.changed && !acceptKeyChange.value) {
        error.value = "Check with them before paying: their wallet key changed.";
        return;
      }
      req.address = got.address;
      plannedUsername.value = got.username;
      plannedIdentity.value = got.identityPubkey;
    } catch (e) {
      error.value = e instanceof Error ? e.message.replace(/^.*?: /, "") : "Couldn't find that username.";
      return;
    }
  }
  const addr = checkAddress(req.address, w.net);
  if (!addr.ok && !req.contact && sendTo.value.trim() && sendTo.value.trim().length < 26) {
    error.value = `No contact called "${sendTo.value.trim()}". Check the name or paste an address.`;
    return;
  }
  if (!addr.ok) {
    error.value = addr.reason;
    return;
  }
  const amount = sendMax.value ? 0 : Number(sendAmount.value.replace(/[,\s]/g, ""));
  if (!sendMax.value && (!Number.isInteger(amount) || amount <= 0)) {
    error.value = "Enter the amount in sats (whole numbers).";
    return;
  }
  try {
    const rate = feeRates.value ? feeRates.value[feeChoice.value] : 2;
    planned.value = w.plan(addr.address, amount, rate, sendMax.value);
    plannedContact.value = req.contact ?? null;
    if (payingRequest.value && addr.address === payingRequest.value.address) {
      plannedUsername.value = payingRequest.value.username;
      plannedIdentity.value = payingRequest.value.identity_pubkey;
    }
    saveName.value = "";
    savedNote.value = "";
    password.value = "";
    warningsOk.value = false;
    view.value = "review";
  } catch (e) {
    error.value = e instanceof SendError ? e.message : "Couldn't prepare this payment.";
  }
}

async function confirmSend() {
  if (!planned.value) return;
  busy.value = true;
  error.value = "";
  try {
    sentTxid.value = await w.send(planned.value, password.value, sendNote.value || (payingRequest.value?.note ?? ""));
    password.value = "";
    if (plannedUsername.value) {
      w.rememberUsername(plannedUsername.value, plannedIdentity.value);
      plannedContact.value = w.state.contacts.find((c) => c.username === plannedUsername.value) ?? null;
    }
    view.value = "sent";
  } catch (e) {
    error.value = e instanceof WrongPassword ? "Wrong password." : e instanceof Error ? e.message : "Sending failed. Nothing was sent.";
  } finally {
    busy.value = false;
  }
}

async function reveal() {
  busy.value = true;
  error.value = "";
  try {
    shownWords.value = (await w.revealPhrase(password.value)).split(" ");
    password.value = "";
  } catch {
    error.value = "Wrong password.";
  } finally {
    busy.value = false;
  }
}

async function changePw() {
  error.value = passwordProblem(pw1.value, pw2.value);
  if (error.value) return;
  busy.value = true;
  try {
    await w.changePassword(password.value, pw1.value);
    pw1.value = pw2.value = "";
    go("home");
  } catch {
    error.value = "Wrong current password.";
  } finally {
    busy.value = false;
  }
}

async function removeWallet() {
  await ln.forget();
  await w.remove({ alsoCloud: alsoCloud.value });
  alsoCloud.value = false;
  go("welcome");
}

async function cloudRestore() {
  busy.value = true;
  error.value = "";
  try {
    await w.restoreFromCloud(password.value);
    await w.loadHandle();
    void w.refresh();
    password.value = "";
    go("home");
  } catch (e) {
    error.value = e instanceof WrongPassword ? "Wrong password." : e instanceof Error ? e.message : "Couldn't restore.";
  } finally {
    busy.value = false;
  }
}

async function cloudOn() {
  busy.value = true;
  error.value = "";
  try {
    await w.enableCloud(password.value);
    password.value = "";
    go("home");
  } catch (e) {
    error.value = e instanceof WrongPassword ? "Wrong password." : e instanceof Error ? e.message : "Backup failed.";
  } finally {
    busy.value = false;
  }
}

async function cloudOff() {
  if (!window.confirm("Turn off Telegram backup? Your backup will be deleted from Telegram. Keep your 12 words safe.")) return;
  await w.disableCloud();
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  copied.value = true;
  setTimeout(() => (copied.value = false), 2000);
}

onMounted(async () => {
  if (!w.state.stored) w.checkCloud();
  if (w.state.stored) {
    await w.loadHandle();
    if (!w.state.live) await w.refresh();
    void loadAlerts();
  }
  document.addEventListener("visibilitychange", onVisibility);
  const qs = new URLSearchParams(location.search);
  const pay = qs.get("pay");
  if (pay && w.state.stored) await openPayRequest(pay);
  else if (pay) error.value = "Create or restore your wallet first, then open the payment link again.";
  if (qs.get("request") && w.state.stored) {
    await openRequest();
    reqAmount.value = qs.get("amount") ?? "";
    reqNote.value = qs.get("note") ?? "";
  }
});

/** Opened from a payment link: fill Send with the request after checking it. */
async function openPayRequest(id: string) {
  try {
    const q = await api.getRequest(id);
    if (q.network !== w.net.name) throw new Error("That request is for a different bitcoin network.");
    if (q.status !== "open") throw new Error(q.status === "paid" ? "That request is already paid." : "That request was cancelled.");
    if (!verifyPoolAddress(q.identity_pubkey, w.net, q.address, q.signature)) throw new Error("That request failed its security check.");
    if (!w.state.live) await w.refresh(); // know the balance before offering to pay
    await openSend();
    sendTo.value = q.address;
    if (q.amount_sats) sendAmount.value = String(q.amount_sats);
    payingRequest.value = q;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Couldn't open that request.";
  }
}
onBeforeUnmount(() => {
  document.removeEventListener("visibilitychange", onVisibility);
  phrase.value = "";
  shownWords.value = [];
  password.value = "";
});
</script>

<style scoped>
.testnet { background: var(--orange-soft); color: var(--orange); border-radius: 10px; padding: 8px 12px; margin-bottom: 12px; font-size: 13px; }
.testnet a { color: inherit; text-decoration: underline; }
.center { text-align: center; display: flex; flex-direction: column; align-items: center; gap: 10px; }
.big-icon { font-size: 44px; line-height: 1; }
.stack { display: flex; flex-direction: column; gap: 10px; margin-top: 14px; width: 100%; }
.row { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; margin: 6px 0; }
.unit { font-size: 0.5em; color: var(--text-dim); }
.pending { color: var(--orange); }
.err { color: var(--red); font-size: 14px; margin-top: 8px; }
.field { display: flex; flex-direction: column; gap: 6px; margin-top: 12px; font-size: 14px; color: var(--text-dim); }
.field input, .field textarea { width: 100%; background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; font-size: 16px; font-family: inherit; }
.field input:focus, .field textarea:focus { outline: none; border-color: var(--orange); }
.inline { display: flex; gap: 8px; }
.inline input { flex: 1; min-width: 0; }
.check { display: flex; gap: 8px; align-items: center; margin-top: 12px; font-size: 14px; }
.words { position: relative; display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 14px 0; }
.words.hidden .word { filter: blur(6px); }
.word { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 8px; font-family: var(--mono); font-size: 14px; }
.word span { color: var(--text-faint); margin-right: 6px; font-size: 12px; }
.cover { position: absolute; inset: 0; display: grid; place-items: center; text-align: center; padding: 16px; background: rgba(11, 14, 17, 0.55); border-radius: 8px; cursor: pointer; font-weight: 600; }
.qr { width: 220px; height: 220px; border-radius: 12px; overflow: hidden; background: #fff; }
.qr :deep(svg) { width: 100%; height: 100%; }
.addr { word-break: break-all; font-size: 14px; background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 10px; width: 100%; }
.fees { display: flex; gap: 8px; flex-wrap: wrap; }
.summary { display: flex; flex-direction: column; gap: 10px; margin: 12px 0; }
.summary div { display: flex; justify-content: space-between; gap: 12px; }
.summary span { color: var(--text-dim); }
.summary b { text-align: right; word-break: break-all; }
.ngn { display: block; font-weight: 400; font-size: 12px; color: var(--text-dim); }
.summary .total { border-top: 1px solid var(--border); padding-top: 10px; }
.tx { display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--border); color: inherit; text-decoration: none; }
.tx:last-child { border-bottom: 0; }
.pos { color: var(--green); font-weight: 600; }
.neg { color: var(--text); font-weight: 600; }
.danger { color: var(--red); border-color: var(--red-soft); }
.sect { margin: 18px 0 6px; color: var(--text-dim); }
.steps { padding-left: 18px; margin: 6px 0 10px; color: var(--text-dim); line-height: 1.7; }
.buybox { background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 12px; margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }
.exchanges { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 12px 0; }
.exchange { display: flex; flex-direction: column; gap: 4px; text-align: left; padding: 10px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg); color: inherit; font: inherit; cursor: pointer; }
.exchange:hover { border-color: var(--orange); }
.faint { color: var(--text-faint); }
.row .btn { min-width: 0; flex: 1; }
.paying { background: var(--orange-soft); border-radius: 10px; padding: 8px 12px; font-size: 14px; margin: 6px 0; }
.handle { font-size: 22px; font-weight: 700; color: var(--orange); margin: 4px 0; }
.at span { display: grid; place-items: center; padding: 0 4px; color: var(--text-dim); font-size: 18px; }
.warn span { color: var(--orange); }
.verified { color: var(--green); font-size: 12px; font-weight: 600; }
.sub-head { margin: 18px 0 6px; color: var(--text-dim); }
.req-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--border); }
.req-acts { display: flex; gap: 6px; align-items: center; }
.chip { font-size: 12px; padding: 2px 8px; border-radius: 999px; background: var(--bg); border: 1px solid var(--border); }
.chip.paid { color: var(--green); border-color: var(--green); }
.chip.open { color: var(--orange); border-color: var(--orange); }
.backup-row { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin: 6px 0 4px; font-size: 14px; }
.head { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.contact { display: flex; align-items: center; gap: 12px; width: 100%; padding: 10px 0; border: 0; border-bottom: 1px solid var(--border); background: none; color: inherit; text-align: left; font: inherit; cursor: pointer; }
.contact.static { cursor: default; }
.contact:last-of-type { border-bottom: 0; }
.avatar { width: 36px; height: 36px; flex: none; border-radius: 50%; display: grid; place-items: center; background: var(--orange-soft); color: var(--orange); font-weight: 700; }
.who { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.who b, .who span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.acts { display: flex; gap: 6px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.chip-btn { border: 1px solid var(--border); background: var(--bg); color: var(--text); border-radius: 999px; padding: 5px 12px; font: inherit; font-size: 13px; cursor: pointer; }
.chip-btn:hover { border-color: var(--orange); }
.ok { color: var(--green); }
.save-box { width: 100%; text-align: left; background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.save-box input { flex: 1; min-width: 0; background: var(--bg-elev); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; font: inherit; }
.beta { background: var(--orange-soft); color: var(--orange); border-radius: 10px; padding: 8px 12px; margin-bottom: 12px; font-size: 13px; }
.eye { background: none; border: 0; cursor: pointer; font-size: 14px; padding: 0 4px; }
.tx { width: 100%; background: none; border-left: 0; border-right: 0; border-top: 0; font: inherit; text-align: left; cursor: pointer; }
.stuck { background: var(--orange-soft); border-radius: 10px; padding: 10px 12px; margin-top: 12px; }
.warnbox { background: var(--orange-soft); border-radius: 10px; padding: 8px 12px; margin: 8px 0; }
.warnbox p { margin: 4px 0; color: var(--orange); }
.linkish { background: none; border: 0; color: var(--text-dim); text-decoration: underline; cursor: pointer; padding: 6px 0 0; font: inherit; font-size: 13px; }
@media (max-width: 380px) { .words { grid-template-columns: repeat(2, 1fr); } }
</style>
