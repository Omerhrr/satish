/**
 * Encrypted wallet backup in the user's own Telegram Cloud Storage.
 *
 * Telegram keeps a small key/value store per bot and user, synced across the
 * user's devices. We store only ciphertext there:
 *   - the recovery phrase, encrypted with the wallet password (same box as on
 *     the device: PBKDF2-SHA256 + AES-GCM),
 *   - a random backup key, also encrypted with the wallet password,
 *   - the address book, encrypted with that backup key (so contacts can be
 *     backed up on every change without asking for the password).
 * Neither Telegram nor XP can read any of it. Restoring needs the password.
 *
 * Telegram limits: keys 1-128 chars [A-Za-z0-9_-], values up to 4096 chars.
 */
import { base64 } from "@scure/base";
import {
  decryptPhrase, encryptPhrase,
  type Contact, type EncryptedSecret, type NetworkName,
} from "./wallet-core";

export interface KeyValueStore {
  getMany(keys: string[]): Promise<Record<string, string>>;
  set(key: string, value: string): Promise<void>;
  remove(keys: string[]): Promise<void>;
}

export interface WalletBackup {
  v: 1;
  xpub: string;
  secret: EncryptedSecret; // recovery phrase, password-encrypted
  keyBox: EncryptedSecret; // backup key (hex), password-encrypted
  createdAt: number;
}

const CHUNK = 4000;
const MAX_CHUNKS = 20;

export const keys = (net: NetworkName) => ({
  wallet: `xpw1_${net}_wallet`,
  count: `xpw1_${net}_contacts_n`,
  chunk: (i: number) => `xpw1_${net}_contacts_${i}`,
  notesCount: `xpw1_${net}_notes_n`,
  notesChunk: (i: number) => `xpw1_${net}_notes_${i}`,
});

const MAX_NOTE_CHUNKS = 10;

export function newBackupKey(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(32)), (b) => b.toString(16).padStart(2, "0")).join("");
}

function hexToBytes(hex: string): Uint8Array {
  return new Uint8Array(hex.match(/.{2}/g)!.map((h) => parseInt(h, 16)));
}

async function aesKey(hex: string): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", hexToBytes(hex), "AES-GCM", false, ["encrypt", "decrypt"]);
}

export async function sealWithKey(keyHex: string, text: string): Promise<string> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await aesKey(keyHex), new TextEncoder().encode(text)));
  return base64.encode(iv) + "." + base64.encode(ct);
}

export async function openWithKey(keyHex: string, sealed: string): Promise<string> {
  const [iv, ct] = sealed.split(".");
  const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: base64.decode(iv) }, await aesKey(keyHex), base64.decode(ct));
  return new TextDecoder().decode(pt);
}

/** Write the wallet part. Call when the wallet is created or the password changes. */
export async function backupWallet(
  kv: KeyValueStore,
  net: NetworkName,
  w: { xpub: string; secret: EncryptedSecret; backupKey: string; createdAt: number },
  password: string,
): Promise<void> {
  const record: WalletBackup = {
    v: 1,
    xpub: w.xpub,
    secret: w.secret,
    keyBox: await encryptPhrase(w.backupKey, password),
    createdAt: w.createdAt,
  };
  await kv.set(keys(net).wallet, JSON.stringify(record));
}

/** Write the address book (no password needed: uses the backup key). */
export async function backupContacts(kv: KeyValueStore, net: NetworkName, backupKey: string, contacts: Contact[]): Promise<void> {
  const sealed = await sealWithKey(backupKey, JSON.stringify(contacts));
  const parts = Math.ceil(sealed.length / CHUNK) || 1;
  if (parts > MAX_CHUNKS) throw new Error("Your address book is too big to back up.");
  const k = keys(net);
  for (let i = 0; i < parts; i++) await kv.set(k.chunk(i), sealed.slice(i * CHUNK, (i + 1) * CHUNK));
  await kv.set(k.count, String(parts));
}

/** Write payment notes ("rent", "rice"). Oldest notes are dropped if they don't fit. */
export async function backupNotes(kv: KeyValueStore, net: NetworkName, backupKey: string, notes: Record<string, string>): Promise<void> {
  let entries = Object.entries(notes);
  let sealed = await sealWithKey(backupKey, JSON.stringify(Object.fromEntries(entries)));
  while (Math.ceil(sealed.length / CHUNK) > MAX_NOTE_CHUNKS && entries.length) {
    entries = entries.slice(Math.ceil(entries.length / 10));
    sealed = await sealWithKey(backupKey, JSON.stringify(Object.fromEntries(entries)));
  }
  const parts = Math.ceil(sealed.length / CHUNK) || 1;
  const k = keys(net);
  for (let i = 0; i < parts; i++) await kv.set(k.notesChunk(i), sealed.slice(i * CHUNK, (i + 1) * CHUNK));
  await kv.set(k.notesCount, String(parts));
}

export async function hasBackup(kv: KeyValueStore, net: NetworkName): Promise<boolean> {
  const got = await kv.getMany([keys(net).wallet]);
  return !!got[keys(net).wallet];
}

export interface Restored {
  phrase: string;
  xpub: string;
  secret: EncryptedSecret;
  backupKey: string;
  contacts: Contact[];
  notes: Record<string, string>;
  createdAt: number;
}

/** Restore everything with the wallet password. Throws WrongPassword. */
export async function restoreBackup(kv: KeyValueStore, net: NetworkName, password: string): Promise<Restored> {
  const k = keys(net);
  const head = await kv.getMany([k.wallet, k.count, k.notesCount]);
  if (!head[k.wallet]) throw new Error("No backup found in your Telegram account.");
  const record = JSON.parse(head[k.wallet]) as WalletBackup;
  const phrase = await decryptPhrase(record.secret, password);
  const backupKey = await decryptPhrase(record.keyBox, password);
  let contacts: Contact[] = [];
  const n = Math.min(Number(head[k.count] || 0), MAX_CHUNKS);
  if (n > 0) {
    const chunkKeys = Array.from({ length: n }, (_, i) => k.chunk(i));
    const chunks = await kv.getMany(chunkKeys);
    try {
      contacts = JSON.parse(await openWithKey(backupKey, chunkKeys.map((c) => chunks[c] ?? "").join("")));
    } catch {
      contacts = []; // a damaged address-book backup must never block wallet recovery
    }
  }
  let notes: Record<string, string> = {};
  const m = Math.min(Number(head[k.notesCount] || 0), MAX_NOTE_CHUNKS);
  if (m > 0) {
    const noteKeys = Array.from({ length: m }, (_, i) => k.notesChunk(i));
    const chunks = await kv.getMany(noteKeys);
    try {
      notes = JSON.parse(await openWithKey(backupKey, noteKeys.map((c) => chunks[c] ?? "").join("")));
    } catch {
      notes = {};
    }
  }
  return { phrase, xpub: record.xpub, secret: record.secret, backupKey, contacts, notes, createdAt: record.createdAt };
}

export async function deleteBackup(kv: KeyValueStore, net: NetworkName): Promise<void> {
  const k = keys(net);
  await kv.remove([
    k.wallet, k.count, k.notesCount,
    ...Array.from({ length: MAX_CHUNKS }, (_, i) => k.chunk(i)),
    ...Array.from({ length: MAX_NOTE_CHUNKS }, (_, i) => k.notesChunk(i)),
  ]);
}

/** Telegram WebApp.CloudStorage as a KeyValueStore, or null outside Telegram / old clients. */
export function telegramStore(): KeyValueStore | null {
  const tg = (globalThis as any).Telegram?.WebApp;
  const cs = tg?.CloudStorage;
  if (!cs || (tg.isVersionAtLeast && !tg.isVersionAtLeast("6.9"))) return null;
  const call = <T>(fn: (cb: (err: unknown, val: T) => void) => void) =>
    new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Telegram didn't respond.")), 8000);
      fn((err, val) => {
        clearTimeout(timer);
        if (err) reject(new Error("Telegram backup failed."));
        else resolve(val);
      });
    });
  return {
    getMany: (ks) => call<Record<string, string>>((cb) => cs.getItems(ks, cb)),
    set: (key, value) => call<boolean>((cb) => cs.setItem(key, value, cb)).then(() => undefined),
    remove: (ks) => call<boolean>((cb) => cs.removeItems(ks, cb)).then(() => undefined),
  };
}
