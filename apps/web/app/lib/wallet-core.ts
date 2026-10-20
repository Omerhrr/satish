/**
 * Self-custodial Bitcoin wallet engine. Runs entirely on the user's device.
 *
 * - BIP39 recovery phrase, BIP84 native SegWit (bc1q / tb1q) accounts.
 * - The phrase is only ever held in memory while signing, and stored on the
 *   device encrypted with the user's password (PBKDF2-SHA256 + AES-GCM).
 * - The XP server never receives the phrase, keys, or signed transactions.
 * - Chain data and broadcasting go through an Esplora API (mempool.space).
 *
 * Pure TypeScript with no Vue imports so it can be unit-tested directly.
 */

import * as btc from "@scure/btc-signer";
import { HDKey } from "@scure/bip32";
import * as bip39 from "@scure/bip39";
import { wordlist } from "@scure/bip39/wordlists/english";
import { hex } from "@scure/base";

export type NetworkName = "mainnet" | "testnet";

export interface NetworkInfo {
  name: NetworkName;
  label: string;
  coinType: 0 | 1;
  btc: typeof btc.NETWORK;
  esplora: string;
  explorer: string;
}

export const NETWORKS: Record<NetworkName, NetworkInfo> = {
  mainnet: {
    name: "mainnet",
    label: "Bitcoin",
    coinType: 0,
    btc: btc.NETWORK,
    esplora: "https://mempool.space/api",
    explorer: "https://mempool.space",
  },
  testnet: {
    name: "testnet",
    label: "Bitcoin Testnet",
    coinType: 1,
    btc: btc.TEST_NETWORK,
    esplora: "https://mempool.space/testnet4/api",
    explorer: "https://mempool.space/testnet4",
  },
};

export const GAP_LIMIT = 20;
export const DUST_SATS = 546;
const RBF_SEQUENCE = 0xfffffffd;

// ---------------------------------------------------------------- phrases

export function newRecoveryPhrase(words: 12 | 24 = 12): string {
  return bip39.generateMnemonic(wordlist, words === 24 ? 256 : 128);
}

export function normalizePhrase(phrase: string): string {
  return phrase.trim().toLowerCase().split(/\s+/).join(" ");
}

export function isValidPhrase(phrase: string): boolean {
  return bip39.validateMnemonic(normalizePhrase(phrase), wordlist);
}

export function isWord(word: string): boolean {
  return wordlist.includes(word.trim().toLowerCase());
}

// ---------------------------------------------------------------- keys

export function accountPath(net: NetworkInfo): string {
  return `m/84'/${net.coinType}'/0'`;
}

/** Account-level private node (m/84'/coin'/0'). Only used while signing. */
export function accountFromPhrase(phrase: string, net: NetworkInfo): HDKey {
  const seed = bip39.mnemonicToSeedSync(normalizePhrase(phrase));
  return HDKey.fromMasterSeed(seed).derive(accountPath(net));
}

/** Public account key. Safe to keep: it can watch but never spend. */
export function accountXpub(phrase: string, net: NetworkInfo): string {
  return accountFromPhrase(phrase, net).publicExtendedKey;
}

export function addressAt(xpub: string, net: NetworkInfo, change: 0 | 1, index: number): string {
  const node = HDKey.fromExtendedKey(xpub).deriveChild(change).deriveChild(index);
  return btc.p2wpkh(node.publicKey!, net.btc).address!;
}

// ---------------------------------------------------------------- addresses

export type AddressCheck =
  | { ok: true; address: string }
  | { ok: false; reason: string };

export function checkAddress(input: string, net: NetworkInfo): AddressCheck {
  const address = input.trim();
  if (!address) return { ok: false, reason: "Enter a Bitcoin address." };
  try {
    btc.Address(net.btc).decode(address);
    return { ok: true, address };
  } catch {
    const other = net.name === "mainnet" ? NETWORKS.testnet : NETWORKS.mainnet;
    try {
      btc.Address(other.btc).decode(address);
      return {
        ok: false,
        reason:
          net.name === "mainnet"
            ? "That's a test-network address. This wallet uses real bitcoin."
            : "That's a real-bitcoin address. This wallet is on the test network.",
      };
    } catch {
      return { ok: false, reason: "That doesn't look like a valid Bitcoin address." };
    }
  }
}

/** Parse "bitcoin:addr?amount=0.001" (BIP21) or a bare address. */
export function parsePaymentRequest(text: string): { address: string; amountSats?: number; label?: string } {
  const raw = text.trim();
  if (!/^bitcoin:/i.test(raw)) return { address: raw };
  const [head, query = ""] = raw.slice(8).split("?");
  const params = new URLSearchParams(query);
  const amt = params.get("amount");
  return {
    address: head,
    amountSats: amt && !Number.isNaN(Number(amt)) ? btcToSats(amt) : undefined,
    label: params.get("label") ?? undefined,
  };
}

// ---------------------------------------------------------------- amounts

export function satsToBtc(sats: number): string {
  const neg = sats < 0;
  const s = Math.abs(Math.trunc(sats)).toString().padStart(9, "0");
  const whole = s.slice(0, -8);
  const frac = s.slice(-8).replace(/0+$/, "");
  return (neg ? "-" : "") + whole + (frac ? "." + frac : "");
}

export function btcToSats(value: string): number {
  const v = value.trim();
  if (!/^\d*(\.\d{0,8})?$/.test(v) || v === "" || v === ".") throw new Error("Enter a valid amount.");
  const [w, f = ""] = v.split(".");
  return Number(w || "0") * 1e8 + Number((f + "00000000").slice(0, 8));
}

// ---------------------------------------------------------------- encryption

export interface EncryptedSecret {
  v: 1;
  kdf: "PBKDF2-SHA256";
  iter: number;
  salt: string;
  iv: string;
  ct: string;
}

const PBKDF2_ITERATIONS = 310_000;

async function deriveAesKey(password: string, salt: Uint8Array, iter: number): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, [
    "deriveKey",
  ]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations: iter },
    base,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

export async function encryptPhrase(phrase: string, password: string): Promise<EncryptedSecret> {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await deriveAesKey(password, salt, PBKDF2_ITERATIONS);
  const ct = new Uint8Array(
    await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(normalizePhrase(phrase))),
  );
  return { v: 1, kdf: "PBKDF2-SHA256", iter: PBKDF2_ITERATIONS, salt: hex.encode(salt), iv: hex.encode(iv), ct: hex.encode(ct) };
}

export class WrongPassword extends Error {
  constructor() {
    super("Wrong password.");
  }
}

export async function decryptPhrase(secret: EncryptedSecret, password: string): Promise<string> {
  const key = await deriveAesKey(password, hex.decode(secret.salt), secret.iter);
  try {
    const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: hex.decode(secret.iv) }, key, hex.decode(secret.ct));
    return new TextDecoder().decode(pt);
  } catch {
    throw new WrongPassword();
  }
}

// ---------------------------------------------------------------- chain data

export interface Utxo {
  txid: string;
  vout: number;
  value: number;
  confirmed: boolean;
  address: string;
  change: 0 | 1;
  index: number;
}

export interface AddressInfo {
  address: string;
  change: 0 | 1;
  index: number;
  txCount: number;
  confirmed: number;
  unconfirmed: number;
}

export interface HistoryItem {
  txid: string;
  amount: number; // net effect on this wallet, sats (negative = sent)
  fee: number;
  confirmed: boolean;
  time?: number; // unix seconds
}

export interface FeeRates {
  fast: number;
  normal: number;
  slow: number;
  minimum: number;
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export class Esplora {
  constructor(
    private base: string,
    private fetchImpl: FetchLike = (i, init) => fetch(i, init),
  ) {}

  private async get<T>(path: string): Promise<T> {
    const res = await this.fetchImpl(this.base + path);
    if (!res.ok) throw new Error(`Couldn't reach the Bitcoin network (${res.status}). Try again.`);
    return (await res.json()) as T;
  }

  async address(addr: string) {
    return this.get<{
      chain_stats: { funded_txo_sum: number; spent_txo_sum: number; tx_count: number };
      mempool_stats: { funded_txo_sum: number; spent_txo_sum: number; tx_count: number };
    }>(`/address/${addr}`);
  }

  async utxos(addr: string) {
    return this.get<{ txid: string; vout: number; value: number; status: { confirmed: boolean } }[]>(
      `/address/${addr}/utxo`,
    );
  }

  async txs(addr: string) {
    return this.get<EsploraTx[]>(`/address/${addr}/txs`);
  }

  async fees(): Promise<FeeRates> {
    const f = await this.get<{ fastestFee: number; halfHourFee: number; hourFee: number; minimumFee: number }>(
      "/v1/fees/recommended",
    );
    return { fast: f.fastestFee, normal: f.halfHourFee, slow: f.hourFee, minimum: f.minimumFee };
  }

  async broadcast(txHex: string): Promise<string> {
    const res = await this.fetchImpl(this.base + "/tx", { method: "POST", body: txHex });
    const text = (await res.text()).trim();
    if (!res.ok) throw new Error(friendlyBroadcastError(text));
    return text;
  }
}

export interface EsploraTx {
  txid: string;
  fee: number;
  status: { confirmed: boolean; block_time?: number };
  vin: { prevout: { scriptpubkey_address?: string; value: number } | null }[];
  vout: { scriptpubkey_address?: string; value: number }[];
}

function friendlyBroadcastError(text: string): string {
  if (/min relay fee|insufficient fee|mempool min fee/i.test(text)) return "The network fee is too low. Choose a faster fee and try again.";
  if (/missing ?inputs|bad-txns-inputs-missingorspent|already spent/i.test(text))
    return "Some of these coins were already spent. Refresh your wallet and try again.";
  if (/dust/i.test(text)) return "That amount is too small to send.";
  return "The network didn't accept this transaction. Nothing was sent.";
}

/** Scan both address chains until GAP_LIMIT unused addresses in a row. */
export async function scanAddresses(xpub: string, net: NetworkInfo, api: Esplora): Promise<AddressInfo[]> {
  const out: AddressInfo[] = [];
  for (const change of [0, 1] as const) {
    let index = 0;
    let unusedRun = 0;
    while (unusedRun < GAP_LIMIT) {
      const batch = Array.from({ length: 10 }, (_, i) => index + i);
      const infos = await Promise.all(
        batch.map(async (i) => {
          const address = addressAt(xpub, net, change, i);
          const a = await api.address(address);
          return {
            address,
            change,
            index: i,
            txCount: a.chain_stats.tx_count + a.mempool_stats.tx_count,
            confirmed: a.chain_stats.funded_txo_sum - a.chain_stats.spent_txo_sum,
            unconfirmed: a.mempool_stats.funded_txo_sum - a.mempool_stats.spent_txo_sum,
          } satisfies AddressInfo;
        }),
      );
      for (const info of infos) {
        out.push(info);
        unusedRun = info.txCount === 0 ? unusedRun + 1 : 0;
        if (unusedRun >= GAP_LIMIT) break;
      }
      index += batch.length;
    }
  }
  return out;
}

export function nextUnused(addresses: AddressInfo[], change: 0 | 1): AddressInfo | undefined {
  return addresses.filter((a) => a.change === change && a.txCount === 0).sort((a, b) => a.index - b.index)[0];
}

export function buildHistory(txs: EsploraTx[], own: Set<string>): HistoryItem[] {
  const seen = new Map<string, HistoryItem>();
  for (const tx of txs) {
    if (seen.has(tx.txid)) continue;
    let delta = 0;
    for (const i of tx.vin) if (i.prevout?.scriptpubkey_address && own.has(i.prevout.scriptpubkey_address)) delta -= i.prevout.value;
    for (const o of tx.vout) if (o.scriptpubkey_address && own.has(o.scriptpubkey_address)) delta += o.value;
    seen.set(tx.txid, { txid: tx.txid, amount: delta, fee: tx.fee, confirmed: tx.status.confirmed, time: tx.status.block_time });
  }
  return [...seen.values()].sort((a, b) => {
    if (a.confirmed !== b.confirmed) return a.confirmed ? 1 : -1;
    return (b.time ?? 0) - (a.time ?? 0);
  });
}

// ---------------------------------------------------------------- sending

/** vbytes for a P2WPKH-only transaction. */
export function estimateVsize(inputs: number, outputs: number): number {
  return Math.ceil(10.5 + 68 * inputs + 31 * outputs);
}

export interface SendPlan {
  inputs: Utxo[];
  to: string;
  amount: number;
  fee: number;
  change: number; // 0 = no change output
  feeRate: number;
  total: number;
}

export class SendError extends Error {}

/**
 * Pick coins (largest first) and work out the fee and change.
 * sendMax spends everything minus the fee.
 */
export function planSend(
  utxos: Utxo[],
  to: string,
  amount: number,
  feeRate: number,
  opts: { sendMax?: boolean } = {},
): SendPlan {
  if (feeRate < 1) feeRate = 1;
  const coins = [...utxos].sort((a, b) => b.value - a.value);
  const available = coins.reduce((s, u) => s + u.value, 0);
  if (!coins.length || available === 0) throw new SendError("Your wallet is empty.");

  if (opts.sendMax) {
    const fee = Math.ceil(estimateVsize(coins.length, 1) * feeRate);
    const send = available - fee;
    if (send < DUST_SATS) throw new SendError("Not enough to cover the network fee.");
    return { inputs: coins, to, amount: send, fee, change: 0, feeRate, total: available };
  }

  if (!Number.isInteger(amount) || amount <= 0) throw new SendError("Enter an amount to send.");
  if (amount < DUST_SATS) throw new SendError(`The minimum you can send is ${DUST_SATS} sats.`);

  const picked: Utxo[] = [];
  let sum = 0;
  for (const c of coins) {
    picked.push(c);
    sum += c.value;
    const feeWithChange = Math.ceil(estimateVsize(picked.length, 2) * feeRate);
    if (sum >= amount + feeWithChange) {
      const change = sum - amount - feeWithChange;
      if (change >= DUST_SATS) {
        return { inputs: picked, to, amount, fee: feeWithChange, change, feeRate, total: amount + feeWithChange };
      }
      // Change would be dust: drop it and give the remainder to miners.
      const fee = sum - amount;
      return { inputs: picked, to, amount, fee, change: 0, feeRate, total: sum };
    }
    const feeNoChange = Math.ceil(estimateVsize(picked.length, 1) * feeRate);
    if (sum >= amount + feeNoChange) {
      return { inputs: picked, to, amount, fee: sum - amount, change: 0, feeRate, total: sum };
    }
  }
  throw new SendError("You don't have enough bitcoin for this amount plus the network fee.");
}

export interface SignedTx {
  hex: string;
  txid: string;
  vsize: number;
  fee: number;
}

/** Build and sign. The phrase is used only inside this call. */
export function signPlan(plan: SendPlan, phrase: string, net: NetworkInfo, changeAddress: string): SignedTx {
  const account = accountFromPhrase(phrase, net);
  const tx = new btc.Transaction({ allowUnknownOutputs: false });
  const keys: Uint8Array[] = [];
  for (const u of plan.inputs) {
    const node = account.deriveChild(u.change).deriveChild(u.index);
    const payment = btc.p2wpkh(node.publicKey!, net.btc);
    if (payment.address !== u.address) throw new SendError("Wallet keys don't match these coins. Nothing was sent.");
    tx.addInput({
      txid: u.txid,
      index: u.vout,
      witnessUtxo: { script: payment.script, amount: BigInt(u.value) },
      sequence: RBF_SEQUENCE,
    });
    keys.push(node.privateKey!);
  }
  tx.addOutputAddress(plan.to, BigInt(plan.amount), net.btc);
  if (plan.change > 0) tx.addOutputAddress(changeAddress, BigInt(plan.change), net.btc);
  keys.forEach((k, i) => tx.signIdx(k, i));
  tx.finalize();
  const fee = Number(tx.fee);
  if (fee !== plan.fee) throw new SendError("Fee check failed. Nothing was sent.");
  return { hex: tx.hex, txid: tx.id, vsize: tx.vsize, fee };
}

// ---------------------------------------------------------------- address book

export interface Contact {
  id: string;
  name: string;
  address: string;
  note?: string;
  createdAt: number;
}

export type ContactCheck = { ok: true; contact: Contact } | { ok: false; reason: string };

export function cleanName(name: string): string {
  return name.trim().replace(/\s+/g, " ");
}

/** Validate a new or edited contact against the book (unique name + address). */
export function checkContact(
  book: Contact[],
  input: { id?: string; name: string; address: string; note?: string },
  net: NetworkInfo,
): ContactCheck {
  const name = cleanName(input.name);
  if (!name) return { ok: false, reason: "Give this address a name." };
  if (name.length > 40) return { ok: false, reason: "Keep the name under 40 characters." };
  const addr = checkAddress(parsePaymentRequest(input.address).address, net);
  if (!addr.ok) return addr;
  const others = book.filter((c) => c.id !== input.id);
  const sameName = others.find((c) => c.name.toLowerCase() === name.toLowerCase());
  if (sameName) return { ok: false, reason: `You already have a contact called "${sameName.name}".` };
  const sameAddr = others.find((c) => c.address === addr.address);
  if (sameAddr) return { ok: false, reason: `This address is already saved as "${sameAddr.name}".` };
  const existing = book.find((c) => c.id === input.id);
  return {
    ok: true,
    contact: {
      id: input.id ?? randomId(),
      name,
      address: addr.address,
      note: input.note?.trim() || undefined,
      createdAt: existing?.createdAt ?? Date.now(),
    },
  };
}

/** Resolve what the user typed in "To": a saved name, or an address/URI. */
export function resolveRecipient(book: Contact[], text: string): { address: string; contact?: Contact; amountSats?: number } {
  const t = text.trim();
  const byName = book.find((c) => c.name.toLowerCase() === cleanName(t).toLowerCase());
  if (byName) return { address: byName.address, contact: byName };
  const req = parsePaymentRequest(t);
  const byAddr = book.find((c) => c.address === req.address);
  return { address: req.address, contact: byAddr, amountSats: req.amountSats };
}

export function searchContacts(book: Contact[], query: string): Contact[] {
  const q = query.trim().toLowerCase();
  const sorted = [...book].sort((a, b) => a.name.localeCompare(b.name));
  if (!q) return sorted;
  return sorted.filter((c) => c.name.toLowerCase().includes(q) || c.address.toLowerCase().startsWith(q));
}

function randomId(): string {
  return hex.encode(crypto.getRandomValues(new Uint8Array(8)));
}
