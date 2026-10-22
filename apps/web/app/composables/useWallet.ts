/**
 * Wallet state for the screens. Everything stays on this device:
 * - the encrypted recovery phrase (needs the password to open),
 * - the public account key, so the balance shows without a password.
 * Nothing here is ever sent to the Satish server. An optional backup goes to the
 * user's own Telegram Cloud Storage, encrypted (see lib/cloud-backup.ts).
 */
import {
  backupContacts, backupNotes, backupWallet, deleteBackup, hasBackup, newBackupKey, restoreBackup, telegramStore,
} from "~/lib/cloud-backup";
import {
  Esplora, NETWORKS, accountXpub, buildHistory, decryptPhrase, encryptPhrase, nextUnused,
  normalizePhrase, planSend, scanAddresses, signPlan, signTx, planBump, walletDescriptors, historyCsv, checkContact,
  identityFromPhrase, signPoolAddresses, verifyPoolAddress, normalizeUsername, POOL_START,
  type AddressInfo, type BumpPlan, type Contact, type EncryptedSecret, type FeeRates, type HistoryItem, type NetworkName, type SendPlan, type Utxo,
} from "~/lib/wallet-core";

interface StoredWallet {
  v: 1;
  network: NetworkName;
  xpub: string;
  secret: EncryptedSecret;
  backedUp: boolean;
  createdAt: number;
  backupKey?: string; // encrypts the address-book backup
  cloud?: boolean; // Telegram backup switched on
  identityKey?: string; // can only vouch for addresses (@username), never spend
  identityPub?: string;
}

interface HandleInfo {
  username: string | null;
  available: number;
  maxIndex: number;
  issuedMax: number;
}

const POOL_BATCH = 30;
const POOL_LOW = 10;

const state = reactive({
  ready: false,
  stored: null as StoredWallet | null,
  addresses: [] as AddressInfo[],
  utxos: [] as Utxo[],
  history: [] as HistoryItem[],
  loading: false,
  error: "",
  lastSync: 0,
  contacts: [] as Contact[],
  cloudAvailable: false,
  cloudHasBackup: false,
  cloudError: "",
  handle: null as HandleInfo | null,
  notes: {} as Record<string, string>,
  live: false, // true once this session has fresh data from the network (cached data is display-only)
  hideBalance: false,
  unlocked: false, // wallet session open: one password for Bitcoin and Lightning
});

// The decrypted phrase for an unlocked session lives only in memory, never in storage.
let sessionPhrase: string | null = null;
let refreshing: Promise<void> | null = null;

interface Snapshot {
  xpub: string;
  addresses: AddressInfo[];
  utxos: Utxo[];
  history: HistoryItem[];
  lastSync: number;
}

function userId(): string {
  return String((window as any).Telegram?.WebApp?.initDataUnsafe?.user?.id ?? "local");
}

function storageKey(net: NetworkName): string {
  return `xp_wallet_v1_${net}_${userId()}`;
}

function contactsKey(net: NetworkName): string {
  return `xp_contacts_v1_${net}_${userId()}`;
}

function readContacts(net: NetworkName): Contact[] {
  try {
    const raw = localStorage.getItem(contactsKey(net));
    return raw ? (JSON.parse(raw) as Contact[]) : [];
  } catch {
    return [];
  }
}

function writeContacts(list: Contact[], net: NetworkName) {
  try {
    localStorage.setItem(contactsKey(net), JSON.stringify(list));
  } catch {
    throw new Error("This device couldn't save your address book.");
  }
}

function notesKey(net: NetworkName): string {
  return `xp_notes_v1_${net}_${userId()}`;
}

function snapKey(net: NetworkName): string {
  return `xp_snapshot_v1_${net}_${userId()}`;
}

function prefsKey(): string {
  return `xp_prefs_v1_${userId()}`;
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage full or blocked: these are conveniences only */
  }
}

function readStore(net: NetworkName): StoredWallet | null {
  try {
    const raw = localStorage.getItem(storageKey(net));
    return raw ? (JSON.parse(raw) as StoredWallet) : null;
  } catch {
    return null;
  }
}

function writeStore(w: StoredWallet | null, net: NetworkName) {
  try {
    if (w) localStorage.setItem(storageKey(net), JSON.stringify(w));
    else localStorage.removeItem(storageKey(net));
  } catch {
    throw new Error("This device couldn't save your wallet. Check that storage isn't full or blocked.");
  }
}

export function useWallet() {
  const config = useRuntimeConfig();
  const xpApi = useXpApi();
  const netName = (config.public.bitcoinNetwork === "mainnet" ? "mainnet" : "testnet") as NetworkName;
  const net = NETWORKS[netName];
  const api = new Esplora((config.public.esploraUrl as string) || net.esplora);

  if (!state.ready) {
    state.stored = readStore(netName);
    state.contacts = readContacts(netName);
    state.notes = readJson(notesKey(netName), {} as Record<string, string>);
    state.hideBalance = !!readJson(prefsKey(), { hideBalance: false }).hideBalance;
    // Show the last known balance straight away (and when offline); sending waits for fresh data.
    const snap = readJson<Snapshot | null>(snapKey(netName), null);
    if (snap && state.stored && snap.xpub === state.stored.xpub) {
      state.addresses = snap.addresses;
      state.utxos = snap.utxos;
      state.history = snap.history;
      state.lastSync = snap.lastSync;
    }
    state.cloudAvailable = !!telegramStore();
    state.ready = true;
  }

  const confirmed = computed(() => state.addresses.reduce((s, a) => s + a.confirmed, 0));
  const pending = computed(() => state.addresses.reduce((s, a) => s + a.unconfirmed, 0));
  const spendable = computed(() => state.utxos.reduce((s, u) => s + u.value, 0));
  const receiveAddress = computed(() => nextUnused(state.addresses, 0)?.address ?? null);

  function identityFields(phrase: string) {
    const id = identityFromPhrase(phrase, net);
    return { identityKey: id.privHex, identityPub: id.pubHex };
  }

  function persist(stored: StoredWallet) {
    writeStore(stored, netName);
    state.stored = stored;
  }

  async function uploadContacts() {
    const kv = telegramStore();
    const w = state.stored;
    if (!kv || !w?.cloud || !w.backupKey) return;
    try {
      await backupContacts(kv, netName, w.backupKey, state.contacts);
      state.cloudError = "";
    } catch (e) {
      state.cloudError = e instanceof Error ? e.message : "Telegram backup failed.";
    }
  }

  async function uploadNotes() {
    const kv = telegramStore();
    const w = state.stored;
    if (!kv || !w?.cloud || !w.backupKey) return;
    try {
      await backupNotes(kv, netName, w.backupKey, state.notes);
    } catch (e) {
      state.cloudError = e instanceof Error ? e.message : "Telegram backup failed.";
    }
  }

  /** Back up the wallet (and contacts) to Telegram. Never blocks the wallet itself. */
  async function uploadWallet(password: string): Promise<boolean> {
    const kv = telegramStore();
    const w = state.stored;
    if (!kv || !w) return false;
    try {
      const backupKey = w.backupKey ?? newBackupKey();
      await backupWallet(kv, netName, { xpub: w.xpub, secret: w.secret, backupKey, createdAt: w.createdAt }, password);
      persist({ ...w, backupKey, cloud: true });
      await uploadContacts();
      await uploadNotes();
      state.cloudError = "";
      return true;
    } catch (e) {
      state.cloudError = e instanceof Error ? e.message : "Telegram backup failed.";
      return false;
    }
  }

  async function checkCloud() {
    const kv = telegramStore();
    if (!kv) return;
    try {
      state.cloudHasBackup = await hasBackup(kv, netName);
    } catch {
      state.cloudHasBackup = false;
    }
  }

  async function restoreFromCloud(password: string) {
    const kv = telegramStore();
    if (!kv) throw new Error("Telegram backup isn't available here. Open Satish inside Telegram.");
    const r = await restoreBackup(kv, netName, password);
    persist({
      v: 1, network: netName, xpub: r.xpub, secret: r.secret, backedUp: true, createdAt: r.createdAt,
      backupKey: r.backupKey, cloud: true, ...identityFields(r.phrase),
    });
    if (r.contacts.length) {
      writeContacts(r.contacts, netName);
      state.contacts = r.contacts;
    }
    if (Object.keys(r.notes).length) {
      state.notes = { ...r.notes, ...state.notes };
      writeJson(notesKey(netName), state.notes);
    }
    state.addresses = [];
    state.utxos = [];
    state.history = [];
    await refresh();
  }

  async function enableCloud(password: string) {
    await revealPhrase(password); // checks the password first
    if (!(await uploadWallet(password))) throw new Error(state.cloudError || "Telegram backup failed.");
  }

  async function disableCloud() {
    const kv = telegramStore();
    if (kv) await deleteBackup(kv, netName);
    if (state.stored) persist({ ...state.stored, cloud: false });
    state.cloudHasBackup = false;
  }

  async function save(phrase: string, password: string, opts: { cloud?: boolean } = {}) {
    const clean = normalizePhrase(phrase);
    const stored: StoredWallet = {
      v: 1,
      network: netName,
      xpub: accountXpub(clean, net),
      secret: await encryptPhrase(clean, password),
      backedUp: true,
      createdAt: Date.now(),
      backupKey: newBackupKey(),
      cloud: false,
      ...identityFields(clean),
    };
    persist(stored);
    if (opts.cloud !== false) await uploadWallet(password);
    state.addresses = [];
    state.utxos = [];
    state.history = [];
    await refresh();
  }

  function refresh(): Promise<void> {
    if (refreshing) return refreshing;
    refreshing = doRefresh().finally(() => (refreshing = null));
    return refreshing;
  }

  async function doRefresh() {
    if (!state.stored) return;
    const firstSync = !state.lastSync;
    state.loading = true;
    state.error = "";
    try {
      // Payers may have been handed new @username addresses since we last looked.
      // Asked even before we know a username, so a freshly restored wallet
      // scans every pool address that was ever handed out.
      try {
        setHandle(await xpApi.handleMe(netName));
      } catch {
        /* not signed in / offline: the pool is still gap-scanned */
      }
      const pool = state.handle && state.handle.issuedMax >= POOL_START ? { from: POOL_START, to: state.handle.issuedMax } : undefined;
      // Full look-ahead for @username coins on this device's first sync (e.g. after a restore); small after that.
      const knownPoolMax = Math.max(-1, ...state.addresses.filter((a) => a.index >= POOL_START && a.txCount > 0).map((a) => a.index));
      const poolTo = Math.max(pool?.to ?? -1, knownPoolMax);
      const addresses = await scanAddresses(state.stored.xpub, net, api, poolTo >= POOL_START ? { from: POOL_START, to: poolTo } : undefined, {
        poolGap: firstSync ? 20 : 5,
      });
      const used = addresses.filter((a) => a.txCount > 0);
      const [utxoLists, txLists] = await Promise.all([
        Promise.all(used.map((a) => api.utxos(a.address).then((us) => us.map((u) => ({ ...u, a }))))),
        Promise.all(used.map((a) => api.txs(a.address))),
      ]);
      state.addresses = addresses;
      state.utxos = utxoLists.flat().map(({ a, ...u }) => ({
        txid: u.txid, vout: u.vout, value: u.value, confirmed: u.status.confirmed,
        address: a.address, change: a.change, index: a.index,
      }));
      state.history = buildHistory(txLists.flat(), new Set(addresses.map((a) => a.address)));
      state.lastSync = Date.now();
      state.live = true;
      writeJson(snapKey(netName), {
        xpub: state.stored.xpub, addresses: state.addresses, utxos: state.utxos, history: state.history, lastSync: state.lastSync,
      } satisfies Snapshot);
    } catch (e) {
      state.error = e instanceof Error ? e.message : "Couldn't update your wallet.";
      if (state.lastSync) state.error = "Couldn't reach the Bitcoin network. Showing your last known balance.";
    } finally {
      state.loading = false;
    }
  }

  function fees(): Promise<FeeRates> {
    return api.fees();
  }

  function plan(to: string, amount: number, feeRate: number, sendMax: boolean): SendPlan {
    return planSend(state.utxos, to, amount, feeRate, { sendMax });
  }

  /** Unlock the wallet for this session (Bitcoin and Lightning). Throws WrongPassword. */
  async function unlock(password: string): Promise<void> {
    if (!state.stored) throw new Error("No wallet on this device.");
    sessionPhrase = await decryptPhrase(state.stored.secret, password);
    state.unlocked = true;
  }

  function lockSession() {
    sessionPhrase = null;
    state.unlocked = false;
  }

  function sessionPhraseOrNull(): string | null {
    return sessionPhrase;
  }

  /** The phrase for signing: from the unlocked session, or by checking the password (which also unlocks). */
  async function phraseFor(password?: string): Promise<string> {
    if (sessionPhrase) return sessionPhrase;
    if (!password) throw new Error("Enter your wallet password.");
    await unlock(password);
    return sessionPhrase!;
  }

  async function send(p: SendPlan, password?: string, note = ""): Promise<string> {
    if (!state.stored) throw new Error("No wallet on this device.");
    const phrase = await phraseFor(password);
    const change = nextUnused(state.addresses, 1)?.address;
    if (!change) throw new Error("Refresh your wallet and try again.");
    const signed = signPlan(p, phrase, net, change);
    const txid = await api.broadcast(signed.hex);
    if (note) setNote(txid, note);
    setTimeout(refresh, 1500);
    return txid;
  }

  /** Work out a faster (or cancelling) replacement for one of our pending payments. */
  async function planReplace(txid: string, kind: "speed" | "cancel", feeRate: number): Promise<BumpPlan> {
    const [tx, spends] = await Promise.all([api.tx(txid), api.outspends(txid)]);
    const own = new Set(state.addresses.map((a) => a.address));
    const dependsOn = tx.vout.some((o, i) => o.scriptpubkey_address && own.has(o.scriptpubkey_address) && spends[i]?.spent);
    if (dependsOn) {
      throw new Error("Another payment already uses the change from this one, so it can't be changed. Wait for it to confirm.");
    }
    const back = nextUnused(state.addresses, 1)?.address;
    if (!back) throw new Error("Refresh your wallet and try again.");
    return planBump(tx, kind, feeRate, state.addresses, state.utxos, back);
  }

  async function sendReplace(p: BumpPlan, password?: string): Promise<string> {
    if (!state.stored) throw new Error("No wallet on this device.");
    const phrase = await phraseFor(password);
    const signed = signTx(p.inputs, p.outputs, p.fee, phrase, net);
    const txid = await api.broadcast(signed.hex);
    const old = state.notes[p.replaces];
    setNote(txid, p.kind === "cancel" ? `Cancelled${old ? `: ${old}` : ""}` : old ?? "");
    setTimeout(refresh, 1500);
    return txid;
  }

  function setNote(txid: string, text: string) {
    const clean = text.trim().slice(0, 120);
    const next = { ...state.notes };
    if (clean) next[txid] = clean;
    else delete next[txid];
    state.notes = next;
    writeJson(notesKey(netName), next);
    void uploadNotes();
  }

  function exportCsv(): string {
    return historyCsv(state.history, state.notes);
  }

  async function exportDescriptors(password: string) {
    return walletDescriptors(await revealPhrase(password), net);
  }

  function setHideBalance(on: boolean) {
    state.hideBalance = on;
    writeJson(prefsKey(), { hideBalance: on });
  }

  async function revealPhrase(password: string): Promise<string> {
    if (!state.stored) throw new Error("No wallet on this device.");
    return decryptPhrase(state.stored.secret, password);
  }

  async function changePassword(oldPassword: string, newPassword: string) {
    const phrase = await revealPhrase(oldPassword);
    const stored = { ...state.stored!, secret: await encryptPhrase(phrase, newPassword) };
    persist(stored);
    if (stored.cloud) await uploadWallet(newPassword);
  }

  async function remove(opts: { alsoCloud?: boolean } = {}) {
    state.handle = null;
    if (opts.alsoCloud) {
      const kv = telegramStore();
      if (kv) await deleteBackup(kv, netName).catch(() => undefined);
      state.cloudHasBackup = false;
    } else if (state.stored?.cloud) {
      state.cloudHasBackup = true;
    }
    lockSession();
    writeStore(null, netName);
    writeJson(snapKey(netName), null);
    state.live = false;
    state.stored = null;
    state.addresses = [];
    state.utxos = [];
    state.history = [];
  }

  /** Add or edit a contact. Returns an error message, or "" on success. */
  function saveContact(input: {
    id?: string; name: string; address: string; note?: string; username?: string; identityPubkey?: string;
  }): string {
    const res = checkContact(state.contacts, input, net);
    if (!res.ok) return res.reason;
    const next = state.contacts.filter((c) => c.id !== res.contact.id).concat(res.contact);
    writeContacts(next, netName);
    state.contacts = next;
    void uploadContacts();
    return "";
  }

  function deleteContact(id: string) {
    const next = state.contacts.filter((c) => c.id !== id);
    writeContacts(next, netName);
    state.contacts = next;
    void uploadContacts();
  }

  // ------------------------------------------------------------ @username

  function setHandle(h: { username: string | null; available: number; max_index: number; issued_max_index: number }) {
    state.handle = { username: h.username, available: h.available, maxIndex: h.max_index, issuedMax: h.issued_max_index };
  }

  /** Load my @username (if any) and quietly top up its address pool. */
  async function loadHandle() {
    if (!state.stored) return;
    try {
      setHandle(await xpApi.handleMe(netName));
      await topUp();
    } catch {
      /* not signed in / offline: usernames just stay hidden */
    }
  }

  async function ensureIdentity(password?: string) {
    const w = state.stored!;
    if (w.identityKey && w.identityPub) return w;
    if (!password) throw new Error("Enter your wallet password to set up a username.");
    const phrase = await decryptPhrase(w.secret, password);
    const next = { ...w, ...identityFields(phrase) };
    persist(next);
    return next;
  }

  function nextPoolStart(): number {
    return Math.max(POOL_START, (state.handle?.maxIndex ?? -1) + 1);
  }

  async function claimUsername(name: string, password?: string) {
    const w = await ensureIdentity(password);
    const remote = state.handle;
    // a different wallet (or none) owned the pool before: start a fresh batch
    const from = remote?.username && remote.maxIndex >= POOL_START ? nextPoolStart() : POOL_START;
    const addresses = signPoolAddresses(w.xpub, w.identityKey!, net, from, POOL_BATCH);
    setHandle(await xpApi.handleClaim({ network: netName, username: normalizeUsername(name), identity_pubkey: w.identityPub!, addresses }));
  }

  async function topUp() {
    const w = state.stored;
    const h = state.handle;
    if (!w?.identityKey || !w.identityPub || !h?.username || h.available >= POOL_LOW) return;
    const addresses = signPoolAddresses(w.xpub, w.identityKey, net, nextPoolStart(), POOL_BATCH);
    try {
      setHandle(await xpApi.handleTopUp({ network: netName, identity_pubkey: w.identityPub, addresses }));
    } catch {
      /* e.g. username now owned by another of my wallets: leave it */
    }
  }

  /**
   * Get a fresh address for @username and check it really belongs to them:
   * the signature must verify, and the identity key must match the one we
   * pinned the first time we paid them.
   */
  async function resolveUsername(raw: string): Promise<{ username: string; address: string; identityPubkey: string; changed: boolean }> {
    const username = normalizeUsername(raw);
    const got = await xpApi.handleAddress(username, netName);
    if (!verifyPoolAddress(got.identity_pubkey, net, got.address, got.signature)) {
      throw new Error(`The address for @${username} failed its security check. Nothing was sent.`);
    }
    const pinned = state.contacts.find((c) => c.username === username)?.identityPubkey;
    return { username, address: got.address, identityPubkey: got.identity_pubkey, changed: !!pinned && pinned !== got.identity_pubkey };
  }

  /** After paying @username: save them (or update their pinned key). */
  function rememberUsername(username: string, identityPubkey: string) {
    const existing = state.contacts.find((c) => c.username === username);
    if (existing) {
      if (existing.identityPubkey !== identityPubkey) saveContact({ ...existing, identityPubkey });
      return;
    }
    let name = "@" + username;
    if (state.contacts.some((c) => c.name.toLowerCase() === name)) name = `${name} (Satish)`;
    saveContact({ name, address: "", username, identityPubkey });
  }

  return {
    loadHandle, claimUsername, resolveUsername, rememberUsername, topUp,
    state, net, saveContact, deleteContact, confirmed, pending, spendable, receiveAddress,
    save, refresh, fees, plan, send, revealPhrase, changePassword, remove,
    unlock, lockSession, sessionPhraseOrNull,
    planReplace, sendReplace, setNote, exportCsv, exportDescriptors, setHideBalance,
    checkCloud, restoreFromCloud, enableCloud, disableCloud,
    explorerTx: (txid: string) => `${net.explorer}/tx/${txid}`,
  };
}
