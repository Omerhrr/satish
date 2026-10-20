<template>
  <div class="wallet">
    <div v-if="w.net.name === 'testnet'" class="testnet">
      🧪 Test network: these coins have no value.
      <a href="https://mempool.space/testnet4/faucet" target="_blank" rel="noopener">Get free test coins</a>
    </div>

    <!-- ============ no wallet yet ============ -->
    <template v-if="!w.state.stored">
      <section v-if="view === 'welcome'" class="card center">
        <div class="big-icon">₿</div>
        <h2>Your own Bitcoin wallet</h2>
        <p class="sub">
          Only you hold the keys. Your recovery phrase is created on this phone and is
          never sent to XP, not even to us.
        </p>
        <div class="stack">
          <button v-if="w.state.cloudHasBackup" class="btn primary" @click="go('cloudrestore')">
            ☁️ Restore from my Telegram backup
          </button>
          <button class="btn" :class="{ primary: !w.state.cloudHasBackup }" @click="startCreate">Create a new wallet</button>
          <button class="btn" @click="go('restore')">I already have a recovery phrase</button>
        </div>
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
          <div class="dim small">{{ w.net.label }} balance</div>
          <div class="balance-big">{{ fmtBtc(w.confirmed.value + w.pending.value) }} <span class="unit">{{ unit }}</span></div>
          <div class="dim small">
            {{ (w.confirmed.value + w.pending.value).toLocaleString() }} sats
            <template v-if="naira(w.confirmed.value + w.pending.value)"> · {{ naira(w.confirmed.value + w.pending.value) }}</template>
          </div>
          <div v-if="w.pending.value" class="pending small">
            {{ w.pending.value > 0 ? "+" : "" }}{{ w.pending.value.toLocaleString() }} sats waiting to confirm
          </div>
          <div class="row">
            <button class="btn primary" @click="go('receive')">↓ Receive</button>
            <button class="btn primary" :disabled="!w.spendable.value" @click="openSend">↑ Send</button>
            <button class="btn primary" @click="openBuy">＋ Buy</button>
          </div>
          <button class="btn ghost small" :disabled="w.state.loading" @click="w.refresh()">
            <span v-if="w.state.loading" class="spinner" /> {{ w.state.loading ? "Updating…" : "Refresh" }}
          </button>
          <p v-if="w.state.error" class="err">{{ w.state.error }}</p>
        </section>

        <section class="card">
          <h2>Activity</h2>
          <p v-if="!w.state.history.length && !w.state.loading" class="dim small">
            No transactions yet. Tap Receive to get your address.
          </p>
          <a
            v-for="t in w.state.history"
            :key="t.txid"
            class="tx"
            :href="w.explorerTx(t.txid)"
            target="_blank"
            rel="noopener"
          >
            <div>
              <b>{{ t.amount >= 0 ? "Received" : "Sent" }}</b>
              <div class="small dim">{{ t.confirmed ? fmtTime(t.time) : "Waiting to confirm" }}</div>
            </div>
            <div :class="t.amount >= 0 ? 'pos' : 'neg'">
              {{ t.amount >= 0 ? "+" : "" }}{{ t.amount.toLocaleString() }} sats
            </div>
          </a>
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
            <span class="who"><b>{{ c.name }}</b><span class="small dim mono">{{ shortAddr(c.address) }}</span></span>
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
          <div class="stack">
            <button class="btn" @click="go('reveal')">Show recovery phrase</button>
            <button class="btn" @click="go('changepw')">Change password</button>
            <button class="btn ghost danger" @click="go('remove')">Remove wallet from this phone</button>
          </div>
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
        </template>
        <p v-else-if="w.state.loading"><span class="spinner" /> Getting your address…</p>
        <p v-else class="err">{{ w.state.error || "Couldn't get an address. Go back and refresh." }}</p>
        <button class="btn ghost" @click="go('home')">← Back</button>
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
            XP doesn't sell bitcoin or hold your money. A licensed partner takes your
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
          <p class="small faint">XP isn't connected to these companies. Check their fees and rules before buying.</p>
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
            <span class="small dim mono">{{ shortAddr(c.address) }}</span>
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
          Bitcoin address
          <div class="inline">
            <input v-model="contactForm.address" autocapitalize="none" autocomplete="off" spellcheck="false" placeholder="bc1… / tb1…" />
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
        <label class="field">
          To (name or Bitcoin address)
          <div class="inline">
            <input v-model="sendTo" autocapitalize="none" autocomplete="off" spellcheck="false" placeholder="Name, bc1… or tb1…" />
            <button v-if="canScan" class="btn small" type="button" @click="scanQr('send')">Scan</button>
          </div>
          <span v-if="recipient.contact" class="small ok">→ {{ recipient.contact.name }} · {{ shortAddr(recipient.contact.address) }}</span>
        </label>
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
          <span class="small dim">Faster fees confirm sooner. Most payments confirm within an hour on "Normal".</span>
        </div>
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
              <template v-if="plannedContact">{{ plannedContact.name }}<br /></template>
              <span class="mono">{{ planned.to }}</span>
            </b>
          </div>
          <div><span>Amount</span><b>{{ planned.amount.toLocaleString() }} sats<small v-if="naira(planned.amount)" class="ngn">{{ naira(planned.amount) }}</small></b></div>
          <div><span>Network fee</span><b>{{ planned.fee.toLocaleString() }} sats<small v-if="naira(planned.fee)" class="ngn">{{ naira(planned.fee) }}</small></b></div>
          <div class="total"><span>Total</span><b>{{ (planned.amount + planned.fee).toLocaleString() }} sats<small v-if="naira(planned.amount + planned.fee)" class="ngn">{{ naira(planned.amount + planned.fee) }}</small></b></div>
        </div>
        <p class="small dim">Bitcoin payments can't be reversed. Check the address carefully.</p>
        <label class="field">Wallet password<input v-model="password" type="password" autocomplete="current-password" /></label>
        <p v-if="error" class="err">{{ error }}</p>
        <div class="stack">
          <button class="btn primary" :disabled="busy || !password" @click="confirmSend">
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
        <div v-if="!plannedContact && planned" class="save-box">
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
          your wallet password. If you change phones, open XP and restore with the password.
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
import {
  SendError, WrongPassword, checkAddress, isValidPhrase, newRecoveryPhrase, normalizePhrase,
  parsePaymentRequest, satsToBtc, resolveRecipient, searchContacts,
  type Contact, type FeeRates, type SendPlan,
} from "~/lib/wallet-core";

const w = useWallet();
const { naira } = usePrice();
type View = "welcome" | "show" | "verify" | "restore" | "password" | "home" | "receive" | "send" | "review" | "sent" | "reveal" | "changepw" | "remove" | "contacts" | "contact" | "buy" | "cloudrestore" | "cloudon";
const view = ref<View>(w.state.stored ? "home" : "welcome");
const error = ref("");
const busy = ref(false);

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
const saveName = ref("");
const savedNote = ref("");

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
  sendTo.value = c.name;
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
  if (v !== "remove" && v !== "show") wroteDown.value = false;
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
  plannedContact.value = null;
  sendTo.value = "";
  sendAmount.value = "";
  sendMax.value = false;
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

function review() {
  error.value = "";
  const req = resolveRecipient(w.state.contacts, sendTo.value);
  if (req.amountSats && !sendAmount.value) sendAmount.value = String(req.amountSats);
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
    saveName.value = "";
    savedNote.value = "";
    password.value = "";
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
    sentTxid.value = await w.send(planned.value, password.value);
    password.value = "";
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
  await w.remove({ alsoCloud: alsoCloud.value });
  alsoCloud.value = false;
  go("welcome");
}

async function cloudRestore() {
  busy.value = true;
  error.value = "";
  try {
    await w.restoreFromCloud(password.value);
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

onMounted(() => {
  if (!w.state.stored) w.checkCloud();
  if (w.state.stored && !w.state.lastSync) w.refresh();
});
onBeforeUnmount(() => {
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
@media (max-width: 380px) { .words { grid-template-columns: repeat(2, 1fr); } }
</style>
