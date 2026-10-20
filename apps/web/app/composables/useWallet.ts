/**
 * Wallet state for the screens. Everything stays on this device:
 * - the encrypted recovery phrase (needs the password to open),
 * - the public account key, so the balance shows without a password.
 * Nothing here is ever sent to the XP server. An optional backup goes to the
 * user's own Telegram Cloud Storage, encrypted (see lib/cloud-backup.ts).
 */
import {
  backupContacts, backupWallet, deleteBackup, hasBackup, newBackupKey, restoreBackup, telegramStore,
} from "~/lib/cloud-backup";
import {
  Esplora, NETWORKS, accountXpub, buildHistory, decryptPhrase, encryptPhrase, nextUnused,
  normalizePhrase, planSend, scanAddresses, signPlan, checkContact,
  type AddressInfo, type Contact, type EncryptedSecret, type FeeRates, type HistoryItem, type NetworkName, type SendPlan, type Utxo,
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
}

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
});

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
  const netName = (config.public.bitcoinNetwork === "mainnet" ? "mainnet" : "testnet") as NetworkName;
  const net = NETWORKS[netName];
  const api = new Esplora((config.public.esploraUrl as string) || net.esplora);

  if (!state.ready) {
    state.stored = readStore(netName);
    state.contacts = readContacts(netName);
    state.cloudAvailable = !!telegramStore();
    state.ready = true;
  }

  const confirmed = computed(() => state.addresses.reduce((s, a) => s + a.confirmed, 0));
  const pending = computed(() => state.addresses.reduce((s, a) => s + a.unconfirmed, 0));
  const spendable = computed(() => state.utxos.reduce((s, u) => s + u.value, 0));
  const receiveAddress = computed(() => nextUnused(state.addresses, 0)?.address ?? null);

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
    if (!kv) throw new Error("Telegram backup isn't available here. Open XP inside Telegram.");
    const r = await restoreBackup(kv, netName, password);
    persist({ v: 1, network: netName, xpub: r.xpub, secret: r.secret, backedUp: true, createdAt: r.createdAt, backupKey: r.backupKey, cloud: true });
    if (r.contacts.length) {
      writeContacts(r.contacts, netName);
      state.contacts = r.contacts;
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
    };
    persist(stored);
    if (opts.cloud !== false) await uploadWallet(password);
    state.addresses = [];
    state.utxos = [];
    state.history = [];
    await refresh();
  }

  async function refresh() {
    if (!state.stored) return;
    state.loading = true;
    state.error = "";
    try {
      const addresses = await scanAddresses(state.stored.xpub, net, api);
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
    } catch (e) {
      state.error = e instanceof Error ? e.message : "Couldn't update your wallet.";
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

  async function send(p: SendPlan, password: string): Promise<string> {
    if (!state.stored) throw new Error("No wallet on this device.");
    const phrase = await decryptPhrase(state.stored.secret, password);
    const change = nextUnused(state.addresses, 1)?.address;
    if (!change) throw new Error("Refresh your wallet and try again.");
    const signed = signPlan(p, phrase, net, change);
    const txid = await api.broadcast(signed.hex);
    setTimeout(refresh, 1500);
    return txid;
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
    if (opts.alsoCloud) {
      const kv = telegramStore();
      if (kv) await deleteBackup(kv, netName).catch(() => undefined);
      state.cloudHasBackup = false;
    } else if (state.stored?.cloud) {
      state.cloudHasBackup = true;
    }
    writeStore(null, netName);
    state.stored = null;
    state.addresses = [];
    state.utxos = [];
    state.history = [];
  }

  /** Add or edit a contact. Returns an error message, or "" on success. */
  function saveContact(input: { id?: string; name: string; address: string; note?: string }): string {
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

  return {
    state, net, saveContact, deleteContact, confirmed, pending, spendable, receiveAddress,
    save, refresh, fees, plan, send, revealPhrase, changePassword, remove,
    checkCloud, restoreFromCloud, enableCloud, disableCloud,
    explorerTx: (txid: string) => `${net.explorer}/tx/${txid}`,
  };
}
