/**
 * Social recovery: split the recovery phrase into 3 shares, any 2 of which
 * rebuild it (Shamir's secret sharing over GF(256), the same field AES uses).
 * One share alone reveals nothing about the phrase.
 *
 * Share text: "satish-share-v1-<x>-<hex payload>-<check>"
 *   x: share number (1..255)
 *   payload: the share bytes for the phrase's entropy (16 or 32 bytes)
 *   check: first 4 bytes of sha256(entropy), the same in every share, so
 *          rebuilding with the wrong pieces is caught instead of giving a
 *          wrong wallet.
 */
import * as bip39 from "@scure/bip39";
import { wordlist } from "@scure/bip39/wordlists/english";
import { hex } from "@scure/base";
import { sha256 } from "@noble/hashes/sha256";

const EXP = new Uint8Array(512);
const LOG = new Uint8Array(256);
(() => {
  let x = 1;
  for (let i = 0; i < 255; i++) {
    EXP[i] = x;
    LOG[x] = i;
    x ^= x << 1; // multiply by 3 (generator) in GF(2^8) with AES polynomial
    if (x & 0x100) x ^= 0x11b;
  }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255]!;
})();

const mul = (a: number, b: number) => (a && b ? EXP[LOG[a]! + LOG[b]!]! : 0);
const div = (a: number, b: number) => {
  if (!b) throw new Error("division by zero");
  return a ? EXP[(LOG[a]! + 255 - LOG[b]!) % 255]! : 0;
};

function randomBytes(n: number): Uint8Array {
  const out = new Uint8Array(n);
  crypto.getRandomValues(out);
  return out;
}

const PREFIX = "satish-share-v1";

export function splitPhrase(phrase: string, shares = 3, threshold = 2): string[] {
  if (threshold < 2 || threshold > shares || shares > 255) throw new Error("bad share settings");
  const words = phrase.trim().toLowerCase().split(/\s+/).join(" ");
  const secret = bip39.mnemonicToEntropy(words, wordlist);
  const check = hex.encode(sha256(secret).slice(0, 4));
  // One random polynomial per secret byte: f(0) = byte, degree threshold-1.
  const coeffs = Array.from({ length: secret.length }, (_, i) => [secret[i]!, ...randomBytes(threshold - 1)]);
  const out: string[] = [];
  for (let x = 1; x <= shares; x++) {
    const y = new Uint8Array(secret.length);
    for (let i = 0; i < secret.length; i++) {
      let acc = 0;
      for (let d = coeffs[i]!.length - 1; d >= 0; d--) acc = mul(acc, x) ^ coeffs[i]![d]!;
      y[i] = acc;
    }
    out.push(`${PREFIX}-${x}-${hex.encode(y)}-${check}`);
  }
  return out;
}

export function parseShare(text: string): { x: number; y: Uint8Array; check: string } | null {
  const m = new RegExp(`^${PREFIX}-(\\d{1,3})-([0-9a-f]+)-([0-9a-f]{8})$`).exec(text.trim().toLowerCase());
  if (!m) return null;
  const x = Number(m[1]);
  const y = hex.decode(m[2]!);
  if (x < 1 || x > 255 || (y.length !== 16 && y.length !== 32)) return null;
  return { x, y, check: m[3]! };
}

/** Rebuild the 12/24-word phrase from any `threshold` shares. */
export function combineShares(texts: string[]): string {
  const parsed = texts.map(parseShare);
  if (parsed.some((p) => !p)) throw new Error("One of those isn't a Satish backup share.");
  const shares = parsed as { x: number; y: Uint8Array; check: string }[];
  const xs = new Set(shares.map((s) => s.x));
  if (xs.size !== shares.length) throw new Error("Those are copies of the same share. Use two different ones.");
  if (new Set(shares.map((s) => s.check)).size !== 1 || new Set(shares.map((s) => s.y.length)).size !== 1)
    throw new Error("Those shares come from different backups.");
  const len = shares[0]!.y.length;
  const secret = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    // Lagrange interpolation at x = 0.
    let acc = 0;
    for (const a of shares) {
      let num = 1;
      let den = 1;
      for (const b of shares) {
        if (a.x === b.x) continue;
        num = mul(num, b.x);
        den = mul(den, a.x ^ b.x);
      }
      acc ^= mul(a.y[i]!, div(num, den));
    }
    secret[i] = acc;
  }
  if (hex.encode(sha256(secret).slice(0, 4)) !== shares[0]!.check)
    throw new Error("Not enough matching shares. You need 2 different shares from the same backup.");
  return bip39.entropyToMnemonic(secret, wordlist);
}
