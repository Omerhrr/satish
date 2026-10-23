/**
 * Self-custodial Bitcoin wallet engine. Runs entirely on the user's device.
 *
 * - BIP39 recovery phrase, BIP84 native SegWit (bc1q / tb1q) accounts.
 * - The phrase is only ever held in memory while signing, and stored on the
 *   device encrypted with the user's password (PBKDF2-SHA256 + AES-GCM).
 * - The Satish server never receives the phrase, keys, or signed transactions.
 * - Chain data and broadcasting go through an Esplora API (mempool.space).
 *
 * Pure TypeScript with no Vue imports so it can be unit-tested directly.
 */

import * as btc from "@scure/btc-signer";
import { HDKey } from "@scure/bip32";
import * as bip39 from "@scure/bip39";
import { wordlist } from "@scure/bip39/wordlists/english";
import { hex } from "@scure/base";
import { secp256k1 } from "@noble/curves/secp256k1";
import { sha256 } from "@noble/hashes/sha256";

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
export const CHANGE_GAP = 10; // change addresses are used strictly in order
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
  replaceable: boolean; // can still be sped up or cancelled (unconfirmed, RBF-signalling, all inputs ours)
}

export interface FeeRates {
  fast: number;
  normal: number;
  slow: number;
  minimum: number;
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export class NetworkBusy extends Error {}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Esplora client that is gentle with public servers (mempool.space rate-limits
 * bursts): at most `maxParallel` requests at once, and retries with back-off on
 * network errors, 429 and 5xx. Inside Telegram a rate-limited reply shows up
 * only as "Failed to fetch", so that is retried too.
 */
export class Esplora {
  private active = 0;
  private waiting: (() => void)[] = [];
  private gapMs: number;
  private tokens: number;
  private refilledAt = Date.now();
  private queue: Promise<void> = Promise.resolve();
  constructor(
    private base: string,
    private fetchImpl: FetchLike = (i, init) => fetch(i, init),
    private opts: { maxParallel?: number; retries?: number; backoffMs?: number; minGapMs?: number; burst?: number } = {},
  ) {
    this.gapMs = opts.minGapMs ?? 150;
    this.tokens = opts.burst ?? 6;
  }

  /**
   * Token bucket: a burst of requests goes out at once (a quick sync finishes
   * in about a second), then about one request per gapMs. Slows down after
   * push-back, speeds up again on success.
   */
  private pace(): Promise<void> {
    const turn = this.queue.then(async () => {
      const cap = this.opts.burst ?? 6;
      const refill = () => {
        const now = Date.now();
        if (this.gapMs > 0) this.tokens = Math.min(cap, this.tokens + (now - this.refilledAt) / this.gapMs);
        else this.tokens = cap;
        this.refilledAt = now;
      };
      refill();
      if (this.tokens < 1) {
        await sleep((1 - this.tokens) * this.gapMs);
        refill();
      }
      this.tokens -= 1;
    });
    this.queue = turn.catch(() => undefined);
    return turn;
  }

  private eased(ok: boolean) {
    const base = this.opts.minGapMs ?? 150;
    this.gapMs = ok ? Math.max(base, Math.round(this.gapMs * 0.8)) : Math.min(2000, Math.round(this.gapMs * 1.5) + 150);
  }

  private async slot<T>(fn: () => Promise<T>): Promise<T> {
    const max = this.opts.maxParallel ?? 4;
    if (this.active >= max) await new Promise<void>((r) => this.waiting.push(r));
    this.active++;
    try {
      return await fn();
    } finally {
      this.active--;
      this.waiting.shift()?.();
    }
  }

  private async fetchRetry(path: string, init?: RequestInit): Promise<Response> {
    const retries = this.opts.retries ?? 5;
    const backoff = this.opts.backoffMs ?? 700;
    for (let attempt = 0; ; attempt++) {
      let res: Response | null = null;
      try {
        res = await this.slot(async () => {
          await this.pace();
          return this.fetchImpl(this.base + path, init);
        });
      } catch {
        res = null; // network error / blocked by rate limit (no CORS headers on 429)
      }
      const good = !!res && res.status !== 429 && res.status < 500;
      this.eased(good);
      if (!good) this.tokens = 0; // stop the burst as soon as the server pushes back
      if (good) return res!;
      if (attempt >= retries) {
        throw new NetworkBusy(
          res ? `The Bitcoin network service is busy (${res.status}). Try again in a minute.` : "Couldn't reach the Bitcoin network. Check your connection and try again.",
        );
      }
      await sleep(backoff * 2 ** attempt + Math.random() * 300);
    }
  }

  private async get<T>(path: string): Promise<T> {
    const res = await this.fetchRetry(path);
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

  async txHex(txid: string): Promise<string> {
    const res = await this.fetchRetry(`/tx/${txid}/hex`);
    if (!res.ok) throw new Error(`Couldn't reach the Bitcoin network (${res.status}). Try again.`);
    return (await res.text()).trim();
  }

  async tx(txid: string) {
    return this.get<EsploraTx>(`/tx/${txid}`);
  }

  async outspends(txid: string) {
    return this.get<{ spent: boolean; status?: { confirmed: boolean } }[]>(`/tx/${txid}/outspends`);
  }

  async broadcast(txHex: string): Promise<string> {
    // Not retried blindly: a timeout after the server accepted it must not look like a failure.
    let res: Response;
    try {
      res = await this.fetchImpl(this.base + "/tx", { method: "POST", body: txHex });
    } catch {
      throw new Error("Couldn't reach the Bitcoin network, so nothing was sent. Check your connection and try again.");
    }
    const text = (await res.text()).trim();
    if (!res.ok) throw new Error(friendlyBroadcastError(text));
    return text;
  }
}

export interface EsploraTx {
  txid: string;
  fee: number;
  weight?: number;
  status: { confirmed: boolean; block_time?: number };
  vin: { txid?: string; vout?: number; sequence?: number; prevout: { scriptpubkey_address?: string; value: number } | null }[];
  vout: { scriptpubkey_address?: string; value: number }[];
}

function friendlyBroadcastError(text: string): string {
  if (/min relay fee|insufficient fee|mempool min fee/i.test(text)) return "The network fee is too low. Choose a faster fee and try again.";
  if (/missing ?inputs|bad-txns-inputs-missingorspent|already spent/i.test(text))
    return "Some of these coins were already spent. Refresh your wallet and try again.";
  if (/dust/i.test(text)) return "That amount is too small to send.";
  if (/insufficient fee|rejecting replacement|replacement/i.test(text))
    return "The new fee isn't high enough to replace the old payment. Pick a faster fee.";
  return "The network didn't accept this transaction. Nothing was sent.";
}

/**
 * Scan both address chains until GAP_LIMIT unused addresses in a row, plus
 * the @username pool (receive index POOL_START and up). The pool is always
 * gap-scanned, so a wallet restored on a new phone still finds coins paid to
 * its @username even before it knows which pool addresses were handed out.
 * `extra.to` (from the server, when known) makes sure the scan reaches at
 * least the last address given to a payer.
 */
export async function scanAddresses(
  xpub: string,
  net: NetworkInfo,
  api: Esplora,
  extra?: { from: number; to: number },
  opts: { poolGap?: number } = {},
): Promise<AddressInfo[]> {
  const out: AddressInfo[] = [];
  const lookup = async (change: 0 | 1, i: number): Promise<AddressInfo> => {
    const address = addressAt(xpub, net, change, i);
    const a = await api.address(address);
    return {
      address, change, index: i,
      txCount: a.chain_stats.tx_count + a.mempool_stats.tx_count,
      confirmed: a.chain_stats.funded_txo_sum - a.chain_stats.spent_txo_sum,
      unconfirmed: a.mempool_stats.funded_txo_sum - a.mempool_stats.spent_txo_sum,
    };
  };
  const gapScan = async (change: 0 | 1, start: number, mustReach: number, gap: number) => {
    let index = start;
    let unusedRun = 0;
    while (index <= mustReach || unusedRun < gap) {
      const batch = Array.from({ length: 5 }, (_, k) => index + k);
      const infos = await Promise.all(batch.map((k) => lookup(change, k)));
      for (const info of infos) {
        out.push(info);
        unusedRun = info.txCount === 0 ? unusedRun + 1 : 0;
      }
      index += batch.length;
    }
  };
  await Promise.all([
    gapScan(0, 0, -1, GAP_LIMIT),
    gapScan(1, 0, -1, CHANGE_GAP),
    gapScan(0, POOL_START, extra && extra.to >= POOL_START ? extra.to : POOL_START - 1, opts.poolGap ?? GAP_LIMIT),
  ]);
  return out.sort((a, b) => a.change - b.change || a.index - b.index);
}

/**
 * Fast re-check for a wallet we've already scanned: look only at addresses
 * already in use plus a few fresh ones on each chain. If any fresh one has
 * been used since, `needFull` tells the caller to do a full gap scan.
 */
export async function quickScan(
  xpub: string,
  net: NetworkInfo,
  api: Esplora,
  known: AddressInfo[],
  poolTo = -1,
): Promise<{ addresses: AddressInfo[]; needFull: boolean }> {
  const byKey = new Map(known.map((a) => [`${a.change}/${a.index}`, a]));
  const want = new Map<string, { change: 0 | 1; index: number; fresh: boolean }>();
  for (const a of known) if (a.txCount > 0) want.set(`${a.change}/${a.index}`, { change: a.change, index: a.index, fresh: false });
  const lastUsed = (change: 0 | 1, pool: boolean) =>
    Math.max(pool ? POOL_START - 1 : -1, ...known.filter((a) => a.change === change && (a.index >= POOL_START) === pool && a.txCount > 0).map((a) => a.index));
  const ahead = (change: 0 | 1, from: number, n: number) => {
    for (let i = from; i < from + n; i++) if (!want.has(`${change}/${i}`)) want.set(`${change}/${i}`, { change, index: i, fresh: true });
  };
  ahead(0, lastUsed(0, false) + 1, 2); // the address on the Receive screen, and one after
  ahead(1, lastUsed(1, false) + 1, 1); // next change address
  const poolFrom = lastUsed(0, true) + 1;
  ahead(0, poolFrom, Math.max(2, poolTo - poolFrom + 1)); // @username addresses handed out so far
  const looked = await Promise.all(
    [...want.values()].map(async (w) => {
      const address = addressAt(xpub, net, w.change, w.index);
      const s = await api.address(address);
      return {
        fresh: w.fresh,
        info: {
          address, change: w.change, index: w.index,
          txCount: s.chain_stats.tx_count + s.mempool_stats.tx_count,
          confirmed: s.chain_stats.funded_txo_sum - s.chain_stats.spent_txo_sum,
          unconfirmed: s.mempool_stats.funded_txo_sum - s.mempool_stats.spent_txo_sum,
        } satisfies AddressInfo,
      };
    }),
  );
  for (const l of looked) byKey.set(`${l.info.change}/${l.info.index}`, l.info);
  const needFull = looked.some((l) => l.fresh && l.info.txCount > 0);
  return { addresses: [...byKey.values()].sort((a, b) => a.change - b.change || a.index - b.index), needFull };
}

export function sameStats(a: AddressInfo | undefined, b: AddressInfo): boolean {
  return !!a && a.txCount === b.txCount && a.confirmed === b.confirmed && a.unconfirmed === b.unconfirmed;
}

export function nextUnused(addresses: AddressInfo[], change: 0 | 1): AddressInfo | undefined {
  return addresses.filter((a) => a.change === change && a.txCount === 0).sort((a, b) => a.index - b.index)[0];
}

export function buildHistory(txs: EsploraTx[], own: Set<string>): HistoryItem[] {
  const seen = new Map<string, HistoryItem>();
  // A pending payment whose coins are already used by another pending payment
  // can't be replaced on its own (the second one would become invalid).
  const parents = new Set<string>();
  for (const tx of txs) if (!tx.status.confirmed) for (const i of tx.vin) if (i.txid) parents.add(i.txid);
  for (const tx of txs) {
    if (seen.has(tx.txid)) continue;
    let delta = 0;
    for (const i of tx.vin) if (i.prevout?.scriptpubkey_address && own.has(i.prevout.scriptpubkey_address)) delta -= i.prevout.value;
    for (const o of tx.vout) if (o.scriptpubkey_address && own.has(o.scriptpubkey_address)) delta += o.value;
    const allOurs = tx.vin.length > 0 && tx.vin.every((i) => !!i.prevout?.scriptpubkey_address && own.has(i.prevout.scriptpubkey_address));
    const rbf = tx.vin.some((i) => (i.sequence ?? 0xffffffff) < 0xfffffffe);
    seen.set(tx.txid, {
      txid: tx.txid, amount: delta, fee: tx.fee, confirmed: tx.status.confirmed, time: tx.status.block_time,
      replaceable: !tx.status.confirmed && allOurs && rbf && !parents.has(tx.txid),
    });
  }
  return [...seen.values()].sort((a, b) => {
    if (a.confirmed !== b.confirmed) return a.confirmed ? 1 : -1;
    if (!a.confirmed) return Number(parents.has(a.txid)) - Number(parents.has(b.txid)); // newest (child) first
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
  const outputs = [{ address: plan.to, value: plan.amount }];
  if (plan.change > 0) outputs.push({ address: changeAddress, value: plan.change });
  return signTx(plan.inputs, outputs, plan.fee, phrase, net);
}

export function signTx(
  inputs: Utxo[],
  outputs: { address: string; value: number }[],
  expectedFee: number,
  phrase: string,
  net: NetworkInfo,
): SignedTx {
  const account = accountFromPhrase(phrase, net);
  const tx = new btc.Transaction({ allowUnknownOutputs: false });
  const keys: Uint8Array[] = [];
  for (const u of inputs) {
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
  for (const o of outputs) tx.addOutputAddress(o.address, BigInt(o.value), net.btc);
  keys.forEach((k, i) => tx.signIdx(k, i));
  tx.finalize();
  const fee = Number(tx.fee);
  if (fee !== expectedFee) throw new SendError("Fee check failed. Nothing was sent.");
  return { hex: tx.hex, txid: tx.id, vsize: tx.vsize, fee };
}

// ---------------------------------------------------------------- speed up / cancel (RBF)

export interface BumpPlan {
  kind: "speed" | "cancel";
  replaces: string;
  inputs: Utxo[];
  outputs: { address: string; value: number }[];
  fee: number;
  oldFee: number;
  feeRate: number;
  oldFeeRate: number;
  extraFee: number; // how much more this costs than the original
}

/**
 * Replace an unconfirmed payment of ours with a higher-fee version (BIP125).
 * - "speed": same recipients, higher fee taken from change (or extra coins).
 * - "cancel": everything goes back to our own address, minus the higher fee.
 * Rules: every input must be ours, the new fee must beat the old one by at
 * least 1 sat/vB of the new size, and the fee rate must go up.
 */
export function planBump(
  tx: EsploraTx,
  kind: "speed" | "cancel",
  wantRate: number,
  addresses: AddressInfo[],
  spare: Utxo[],
  ownAddress: string,
): BumpPlan {
  if (tx.status.confirmed) throw new SendError("This payment is already confirmed.");
  const own = new Map(addresses.map((a) => [a.address, a]));
  const inputs: Utxo[] = tx.vin.map((i) => {
    const addr = i.prevout?.scriptpubkey_address;
    const info = addr ? own.get(addr) : undefined;
    if (!info || !i.prevout || i.txid === undefined || i.vout === undefined) {
      throw new SendError("This payment used coins from another wallet, so it can't be changed here.");
    }
    return { txid: i.txid, vout: i.vout, value: i.prevout.value, confirmed: false, address: addr!, change: info.change, index: info.index };
  });
  if (!tx.vin.some((i) => (i.sequence ?? 0xffffffff) < 0xfffffffe)) {
    throw new SendError("This payment wasn't sent in a way that allows changing it. Wait for it to confirm.");
  }
  const oldVsize = Math.ceil((tx.weight ?? estimateVsize(tx.vin.length, tx.vout.length) * 4) / 4);
  const oldFeeRate = tx.fee / oldVsize;
  const rate = Math.max(Math.ceil(wantRate), Math.floor(oldFeeRate) + 1);
  const minFee = (vsize: number) => Math.max(Math.ceil(vsize * rate), tx.fee + vsize);
  const done = (outputs: { address: string; value: number }[], fee: number, used: Utxo[]): BumpPlan => ({
    kind, replaces: tx.txid, inputs: used, outputs, fee, oldFee: tx.fee,
    feeRate: Math.round((fee / estimateVsize(used.length, outputs.length)) * 10) / 10,
    oldFeeRate: Math.round(oldFeeRate * 10) / 10, extraFee: fee - tx.fee,
  });

  const used = [...inputs];
  const sum = () => used.reduce((s, u) => s + u.value, 0);

  if (kind === "cancel") {
    const fee = minFee(estimateVsize(used.length, 1));
    const back = sum() - fee;
    if (back < DUST_SATS) throw new SendError("This payment is too small to cancel: the fee would use it all.");
    return done([{ address: ownAddress, value: back }], fee, used);
  }

  const recipients = tx.vout
    .filter((o) => !(o.scriptpubkey_address && own.get(o.scriptpubkey_address)?.change === 1))
    .map((o) => {
      if (!o.scriptpubkey_address) throw new SendError("This payment has an output this wallet can't rebuild.");
      return { address: o.scriptpubkey_address, value: o.value };
    });
  const changeAddr = tx.vout.find((o) => o.scriptpubkey_address && own.get(o.scriptpubkey_address)?.change === 1)?.scriptpubkey_address ?? ownAddress;
  const paying = recipients.reduce((s, o) => s + o.value, 0);
  const pool = spare
    .filter((u) => u.confirmed && u.txid !== tx.txid && !used.some((x) => x.txid === u.txid && x.vout === u.vout))
    .sort((a, b) => b.value - a.value);

  for (;;) {
    const withChange = minFee(estimateVsize(used.length, recipients.length + 1));
    const change = sum() - paying - withChange;
    if (change >= DUST_SATS) return done([...recipients, { address: changeAddr, value: change }], withChange, [...used]);
    const noChange = minFee(estimateVsize(used.length, recipients.length));
    if (sum() - paying >= noChange) return done(recipients, sum() - paying, [...used]);
    const next = pool.shift();
    if (!next) throw new SendError("You don't have enough spare bitcoin to pay the higher fee.");
    used.push(next);
  }
}

// ---------------------------------------------------------------- export

/**
 * Output descriptors so the same wallet can be watched or restored in
 * Sparrow, BlueWallet, Nunchuk and others (BIP84, account 0).
 */
export function walletDescriptors(phrase: string, net: NetworkInfo): { receive: string; change: string; xpub: string; path: string; fingerprint: string } {
  const seed = bip39.mnemonicToSeedSync(normalizePhrase(phrase));
  const versions = net.coinType === 1 ? { private: 0x04358394, public: 0x043587cf } : undefined;
  const master = HDKey.fromMasterSeed(seed, versions);
  const account = master.derive(accountPath(net));
  const fingerprint = master.fingerprint.toString(16).padStart(8, "0");
  const origin = `[${fingerprint}/84h/${net.coinType}h/0h]`;
  return {
    receive: `wpkh(${origin}${account.publicExtendedKey}/0/*)`,
    change: `wpkh(${origin}${account.publicExtendedKey}/1/*)`,
    xpub: account.publicExtendedKey,
    path: `m/84'/${net.coinType}'/0'`,
    fingerprint,
  };
}

// ---------------------------------------------------------------- private keys

/** The account private key (can spend everything) for advanced users and other wallets. */
export function walletPrivateKeys(phrase: string, net: NetworkInfo): { xprv: string; descriptor: string; path: string; fingerprint: string } {
  const seed = bip39.mnemonicToSeedSync(normalizePhrase(phrase));
  const versions = net.coinType === 1 ? { private: 0x04358394, public: 0x043587cf } : undefined;
  const master = HDKey.fromMasterSeed(seed, versions);
  const account = master.derive(accountPath(net));
  const fingerprint = master.fingerprint.toString(16).padStart(8, "0");
  return {
    xprv: account.privateExtendedKey,
    descriptor: `wpkh([${fingerprint}/84h/${net.coinType}h/0h]${account.privateExtendedKey}/<0;1>/*)`,
    path: accountPath(net),
    fingerprint,
  };
}

/** Private key (WIF) for one address of this wallet. */
export function addressWif(phrase: string, net: NetworkInfo, change: 0 | 1, index: number): string {
  const node = accountFromPhrase(phrase, net).deriveChild(change).deriveChild(index);
  return btc.WIF(net.btc).encode(node.privateKey!);
}

export type SweepKind = "p2wpkh" | "p2sh-p2wpkh" | "p2pkh";

/** Addresses a single private key (WIF) can hold coins at. Throws SendError on a bad key. */
export function sweepAddresses(wif: string, net: NetworkInfo): { priv: Uint8Array; addresses: { kind: SweepKind; address: string }[] } {
  let priv: Uint8Array;
  try {
    priv = btc.WIF(net.btc).decode(wif.trim());
  } catch {
    const other = net.name === "mainnet" ? NETWORKS.testnet : NETWORKS.mainnet;
    try {
      btc.WIF(other.btc).decode(wif.trim());
      throw new SendError(`That private key is for the ${other.name === "mainnet" ? "real Bitcoin network" : "test network"}, not this wallet's.`);
    } catch (e) {
      if (e instanceof SendError) throw e;
    }
    throw new SendError("That isn't a valid private key. It usually starts with K, L, 5 (or c on the test network).");
  }
  const pub = secp256k1.getPublicKey(priv, true);
  return {
    priv,
    addresses: [
      { kind: "p2wpkh", address: btc.p2wpkh(pub, net.btc).address! },
      { kind: "p2sh-p2wpkh", address: btc.p2sh(btc.p2wpkh(pub, net.btc), net.btc).address! },
      { kind: "p2pkh", address: btc.p2pkh(pub, net.btc).address! },
    ],
  };
}

export interface SweepInput {
  txid: string;
  vout: number;
  value: number;
  kind: SweepKind;
  rawTx?: string; // needed for legacy (p2pkh) coins
}

const SWEEP_VBYTES: Record<SweepKind, number> = { p2wpkh: 68, "p2sh-p2wpkh": 91, p2pkh: 148 };

export function planSweep(inputs: SweepInput[], feeRate: number): { total: number; fee: number; receive: number } {
  if (!inputs.length) throw new SendError("There's no bitcoin on that private key.");
  const total = inputs.reduce((s, i) => s + i.value, 0);
  const vsize = Math.ceil(10.5 + 31 + inputs.reduce((s, i) => s + SWEEP_VBYTES[i.kind], 0));
  const fee = Math.ceil(vsize * Math.max(1, feeRate));
  const receive = total - fee;
  if (receive < DUST_SATS) throw new SendError("The coins on that key are too small to cover the network fee.");
  return { total, fee, receive };
}

/** Move everything on a private key to one of our own addresses. */
export function signSweep(inputs: SweepInput[], priv: Uint8Array, net: NetworkInfo, to: string, fee: number): SignedTx {
  const pub = secp256k1.getPublicKey(priv, true);
  const tx = new btc.Transaction({ allowUnknownOutputs: false });
  for (const i of inputs) {
    if (i.kind === "p2wpkh") {
      tx.addInput({ txid: i.txid, index: i.vout, witnessUtxo: { script: btc.p2wpkh(pub, net.btc).script, amount: BigInt(i.value) }, sequence: RBF_SEQUENCE });
    } else if (i.kind === "p2sh-p2wpkh") {
      const p = btc.p2sh(btc.p2wpkh(pub, net.btc), net.btc);
      tx.addInput({ txid: i.txid, index: i.vout, witnessUtxo: { script: p.script, amount: BigInt(i.value) }, redeemScript: p.redeemScript, sequence: RBF_SEQUENCE });
    } else {
      if (!i.rawTx) throw new SendError("Couldn't load an old coin on that key. Try again.");
      tx.addInput({ txid: i.txid, index: i.vout, nonWitnessUtxo: hex.decode(i.rawTx), sequence: RBF_SEQUENCE });
    }
  }
  const total = inputs.reduce((s, i) => s + i.value, 0);
  tx.addOutputAddress(to, BigInt(total - fee), net.btc);
  tx.sign(priv);
  tx.finalize();
  if (Number(tx.fee) !== fee) throw new SendError("Fee check failed. Nothing was sent.");
  return { hex: tx.hex, txid: tx.id, vsize: tx.vsize, fee };
}

function csvCell(v: string | number): string {
  const t = String(v);
  return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
}

/** History as CSV (date, type, sats, fee, note, status, txid). */
export function historyCsv(items: HistoryItem[], notes: Record<string, string> = {}): string {
  const rows = [["date", "type", "amount_sats", "fee_sats", "note", "status", "txid"]];
  for (const t of items) {
    rows.push([
      t.time ? new Date(t.time * 1000).toISOString() : "",
      t.amount >= 0 ? "received" : "sent",
      String(t.amount),
      t.amount < 0 ? String(t.fee) : "0",
      notes[t.txid] ?? "",
      t.confirmed ? "confirmed" : "pending",
      t.txid,
    ]);
  }
  return rows.map((r) => r.map(csvCell).join(",")).join("\n") + "\n";
}

// ---------------------------------------------------------------- address book

export interface Contact {
  id: string;
  name: string;
  address: string; // "" for @username contacts (a fresh address is fetched per payment)
  username?: string; // XP @username, without the @
  identityPubkey?: string; // pinned the first time we paid them
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
  input: { id?: string; name: string; address: string; note?: string; username?: string; identityPubkey?: string },
  net: NetworkInfo,
): ContactCheck {
  const name = cleanName(input.name);
  if (!name) return { ok: false, reason: "Give this address a name." };
  if (name.length > 40) return { ok: false, reason: "Keep the name under 40 characters." };
  const others0 = book.filter((c) => c.id !== input.id);
  const existing0 = book.find((c) => c.id === input.id);
  const user = input.username ? normalizeUsername(input.username) : (/^@/.test(input.address.trim()) ? normalizeUsername(input.address) : "");
  if (user) {
    const problem = usernameProblem(user);
    if (problem) return { ok: false, reason: problem };
    const dupName = others0.find((c) => c.name.toLowerCase() === name.toLowerCase());
    if (dupName) return { ok: false, reason: `You already have a contact called "${dupName.name}".` };
    const dupUser = others0.find((c) => c.username === user);
    if (dupUser) return { ok: false, reason: `@${user} is already saved as "${dupUser.name}".` };
    return {
      ok: true,
      contact: {
        id: input.id ?? randomId(), name, address: "", username: user,
        identityPubkey: input.identityPubkey ?? existing0?.identityPubkey,
        note: input.note?.trim() || undefined, createdAt: existing0?.createdAt ?? Date.now(),
      },
    };
  }
  const addr = checkAddress(parsePaymentRequest(input.address).address, net);
  if (!addr.ok) return addr;
  const others = book.filter((c) => c.id !== input.id);
  const sameName = others.find((c) => c.name.toLowerCase() === name.toLowerCase());
  if (sameName) return { ok: false, reason: `You already have a contact called "${sameName.name}".` };
  const sameAddr = others.find((c) => c.address && c.address === addr.address);
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
export function resolveRecipient(
  book: Contact[],
  text: string,
): { address: string; contact?: Contact; amountSats?: number; username?: string } {
  const t = text.trim();
  if (t.startsWith("@")) {
    const username = normalizeUsername(t);
    return { address: "", username, contact: book.find((c) => c.username === username) };
  }
  const byName = book.find((c) => c.name.toLowerCase() === cleanName(t).toLowerCase());
  if (byName) return { address: byName.address, contact: byName, username: byName.username };
  const req = parsePaymentRequest(t);
  const byAddr = book.find((c) => c.address === req.address);
  return { address: req.address, contact: byAddr, amountSats: req.amountSats };
}

export function searchContacts(book: Contact[], query: string): Contact[] {
  const q = query.trim().toLowerCase();
  const sorted = [...book].sort((a, b) => a.name.localeCompare(b.name));
  if (!q) return sorted;
  const qq = q.replace(/^@/, "");
  return sorted.filter(
    (c) => c.name.toLowerCase().includes(q) || (c.address && c.address.toLowerCase().startsWith(q)) || (c.username ?? "").includes(qq),
  );
}

function randomId(): string {
  return hex.encode(crypto.getRandomValues(new Uint8Array(8)));
}

// ---------------------------------------------------------------- @usernames

/**
 * The wallet's identity key lives on a private chain (m/84'/coin'/0'/7/0).
 * It can only vouch for receive addresses ("this address is mine"); it can't
 * spend. Payers verify these signatures so even a compromised XP server
 * can't swap in its own address for @username.
 */

export const IDENTITY_CHAIN = 7;
export const POOL_START = 1000; // username addresses live at 0/1000+, away from the Receive screen's 0/0..

export function identityFromPhrase(phrase: string, net: NetworkInfo): { privHex: string; pubHex: string } {
  const node = accountFromPhrase(phrase, net).deriveChild(IDENTITY_CHAIN).deriveChild(0);
  return { privHex: hex.encode(node.privateKey!), pubHex: hex.encode(node.publicKey!) };
}

export function addressMessage(net: NetworkInfo, address: string): Uint8Array {
  return sha256(new TextEncoder().encode(`xp-handle-v1|${net.name}|${address}`));
}

export interface SignedPoolAddress {
  address: string;
  index: number;
  signature: string;
}

/** Sign receive addresses (derived from the xpub) with the identity key. */
export function signPoolAddresses(xpub: string, identityPrivHex: string, net: NetworkInfo, from: number, count: number): SignedPoolAddress[] {
  const priv = hex.decode(identityPrivHex);
  return Array.from({ length: count }, (_, i) => {
    const index = from + i;
    const address = addressAt(xpub, net, 0, index);
    const signature = hex.encode(secp256k1.sign(addressMessage(net, address), priv).toDERRawBytes());
    return { address, index, signature };
  });
}

export function verifyPoolAddress(identityPubHex: string, net: NetworkInfo, address: string, signatureHex: string): boolean {
  try {
    return secp256k1.verify(hex.decode(signatureHex), addressMessage(net, address), hex.decode(identityPubHex), { format: "der" });
  } catch {
    return false;
  }
}

/** Spark addresses as wallets may hand them over: "spark:" URI prefix, any case. */
export function normalizeSpark(address: string): string {
  let a = address.trim();
  if (/^spark:/i.test(a)) a = a.slice(6);
  return a.toLowerCase();
}

/** What the identity key signs to vouch for a @username's Lightning (Spark) address. */
export function sparkMessage(net: NetworkInfo, lnNetwork: string, address: string): Uint8Array {
  return sha256(new TextEncoder().encode(`xp-handle-ln-v1|${net.name}|${lnNetwork}|${address}`));
}

export function signSparkAddress(identityPrivHex: string, net: NetworkInfo, lnNetwork: string, address: string): string {
  return hex.encode(secp256k1.sign(sparkMessage(net, lnNetwork, address), hex.decode(identityPrivHex)).toDERRawBytes());
}

export function verifySparkAddress(identityPubHex: string, net: NetworkInfo, lnNetwork: string, address: string, signatureHex: string): boolean {
  try {
    return secp256k1.verify(hex.decode(signatureHex), sparkMessage(net, lnNetwork, address), hex.decode(identityPubHex), { format: "der" });
  } catch {
    return false;
  }
}

export function normalizeUsername(raw: string): string {
  return raw.trim().replace(/^@/, "").toLowerCase();
}

export function usernameProblem(name: string): string {
  if (!/^[a-z0-9_]{3,20}$/.test(name)) return "Use 3-20 characters: lowercase letters, numbers and _.";
  return "";
}
