import { describe, expect, test } from "bun:test";
import * as btc from "@scure/btc-signer";
import {
  NETWORKS, Esplora, SendError, WrongPassword, accountXpub, addressAt, btcToSats, buildHistory,
  checkAddress, decryptPhrase, encryptPhrase, isValidPhrase, newRecoveryPhrase, nextUnused,
  parsePaymentRequest, planSend, satsToBtc, scanAddresses, signPlan, type Utxo,
} from "../app/lib/wallet-core";

const PHRASE = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";
const T = NETWORKS.testnet, M = NETWORKS.mainnet;

describe("keys (BIP84 official vectors)", () => {
  test("mainnet first receive/change", () => {
    const x = accountXpub(PHRASE, M);
    expect(x).toBe("xpub6CatWdiZiodmUeTDp8LT5or8nmbKNcuyvz7WyksVFkKB4RHwCD3XyuvPEbvqAQY3rAPshWcMLoP2fMFMKHPJ4ZeZXYVUhLv1VMrjPC7PW6V");
    expect(addressAt(x, M, 0, 0)).toBe("bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu");
    expect(addressAt(x, M, 0, 1)).toBe("bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g");
    expect(addressAt(x, M, 1, 0)).toBe("bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el");
  });
  test("testnet uses coin type 1 and tb1 addresses", () => {
    expect(addressAt(accountXpub(PHRASE, T), T, 0, 0)).toBe("tb1q6rz28mcfaxtmd6v789l9rrlrusdprr9pqcpvkl");
  });
  test("new phrases are valid 12 words and unique", () => {
    const a = newRecoveryPhrase(), b = newRecoveryPhrase();
    expect(a.split(" ").length).toBe(12);
    expect(isValidPhrase(a)).toBe(true);
    expect(a).not.toBe(b);
    expect(isValidPhrase("abandon ".repeat(12).trim())).toBe(false);
    expect(isValidPhrase("  ABANDON abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about ")).toBe(true);
  });
});

describe("encryption", () => {
  test("round trip and wrong password", async () => {
    const box = await encryptPhrase(PHRASE, "correct horse");
    expect(JSON.stringify(box)).not.toContain("abandon");
    expect(await decryptPhrase(box, "correct horse")).toBe(PHRASE);
    await expect(decryptPhrase(box, "wrong")).rejects.toBeInstanceOf(WrongPassword);
  });
});

describe("addresses and amounts", () => {
  test("network mismatch is explained", () => {
    expect(checkAddress("tb1q6rz28mcfaxtmd6v789l9rrlrusdprr9pqcpvkl", T).ok).toBe(true);
    const r = checkAddress("bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu", T);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toContain("real-bitcoin");
    expect(checkAddress("hello", T).ok).toBe(false);
  });
  test("BIP21 and BTC/sats conversion", () => {
    expect(parsePaymentRequest("bitcoin:tb1qabc?amount=0.0015&label=Shop")).toEqual({ address: "tb1qabc", amountSats: 150000, label: "Shop" });
    expect(btcToSats("0.00000001")).toBe(1);
    expect(btcToSats("1.5")).toBe(150_000_000);
    expect(() => btcToSats("1.123456789")).toThrow();
    expect(satsToBtc(150_000_000)).toBe("1.5");
    expect(satsToBtc(1)).toBe("0.00000001");
  });
});

function utxo(value: number, index: number, change: 0 | 1 = 0): Utxo {
  const x = accountXpub(PHRASE, T);
  return { txid: (index + 1).toString(16).padStart(64, "0"), vout: 0, value, confirmed: true, address: addressAt(x, T, change, index), change, index };
}

describe("coin selection", () => {
  const to = "tb1q6rz28mcfaxtmd6v789l9rrlrusdprr9pqcpvkl";
  test("with change", () => {
    const p = planSend([utxo(100_000, 0), utxo(50_000, 1)], to, 30_000, 2);
    expect(p.inputs.length).toBe(1);
    expect(p.amount + p.fee + p.change).toBe(100_000);
    expect(p.change).toBeGreaterThan(0);
  });
  test("send max", () => {
    const p = planSend([utxo(100_000, 0), utxo(50_000, 1)], to, 0, 3, { sendMax: true });
    expect(p.inputs.length).toBe(2);
    expect(p.amount + p.fee).toBe(150_000);
    expect(p.change).toBe(0);
  });
  test("dust change goes to fee", () => {
    const p = planSend([utxo(10_000, 0)], to, 9_500, 1);
    expect(p.change).toBe(0);
    expect(p.amount + p.fee).toBe(10_000);
  });
  test("insufficient and too small", () => {
    expect(() => planSend([utxo(10_000, 0)], to, 20_000, 1)).toThrow(SendError);
    expect(() => planSend([utxo(10_000, 0)], to, 100, 1)).toThrow(SendError);
    expect(() => planSend([], to, 1000, 1)).toThrow(SendError);
  });
});

describe("signing", () => {
  test("produces a valid, fully signed segwit transaction", () => {
    const x = accountXpub(PHRASE, T);
    const to = "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx";
    const plan = planSend([utxo(100_000, 0), utxo(40_000, 3, 1)], to, 120_000, 5);
    const signed = signPlan(plan, PHRASE, T, addressAt(x, T, 1, 4));
    const tx = btc.Transaction.fromRaw(Buffer.from(signed.hex, "hex"), { allowUnknownOutputs: true });
    expect(tx.inputsLength).toBe(2);
    expect(signed.txid).toMatch(/^[0-9a-f]{64}$/);
    expect(signed.fee).toBe(plan.fee);
    expect(signed.fee / signed.vsize).toBeGreaterThanOrEqual(5);
    expect(tx.getInput(0).finalScriptWitness?.length).toBe(2);
  });
  test("refuses coins that aren't this wallet's", () => {
    const plan = planSend([{ ...utxo(100_000, 0), address: "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx" }], "tb1q6rz28mcfaxtmd6v789l9rrlrusdprr9pqcpvkl", 10_000, 1);
    expect(() => signPlan(plan, PHRASE, T, "tb1q6rz28mcfaxtmd6v789l9rrlrusdprr9pqcpvkl")).toThrow(SendError);
  });
});

describe("scanning against a fake network", () => {
  test("finds funds, respects the gap limit, builds history", async () => {
    const x = accountXpub(PHRASE, T);
    const used = new Map([[addressAt(x, T, 0, 0), 50_000], [addressAt(x, T, 0, 2), 25_000]]);
    let calls = 0;
    const fake = async (url: string) => {
      calls++;
      const addr = url.split("/address/")[1];
      const v = used.get(addr) ?? 0;
      const stats = { funded_txo_sum: v, spent_txo_sum: 0, tx_count: v ? 1 : 0 };
      return new Response(JSON.stringify({ chain_stats: stats, mempool_stats: { funded_txo_sum: 0, spent_txo_sum: 0, tx_count: 0 } }));
    };
    const infos = await scanAddresses(x, T, new Esplora("https://x", fake));
    expect(infos.filter((i) => i.txCount).reduce((s, i) => s + i.confirmed, 0)).toBe(75_000);
    expect(nextUnused(infos, 0)?.index).toBe(1);
    expect(calls).toBeLessThan(100);
    const own = new Set(infos.map((i) => i.address));
    const hist = buildHistory([
      { txid: "a", fee: 200, status: { confirmed: true, block_time: 10 }, vin: [{ prevout: { scriptpubkey_address: "ext", value: 50_200 } }], vout: [{ scriptpubkey_address: addressAt(x, T, 0, 0), value: 50_000 }] },
      { txid: "b", fee: 150, status: { confirmed: false }, vin: [{ prevout: { scriptpubkey_address: addressAt(x, T, 0, 0), value: 50_000 } }], vout: [{ scriptpubkey_address: "ext", value: 20_000 }, { scriptpubkey_address: addressAt(x, T, 1, 0), value: 29_850 }] },
    ], own);
    expect(hist[0]).toMatchObject({ txid: "b", amount: -20_150, confirmed: false });
    expect(hist[1]).toMatchObject({ txid: "a", amount: 50_000 });
  });
});

import { checkContact, resolveRecipient, searchContacts, type Contact } from "../app/lib/wallet-core";

describe("address book", () => {
  const A = "tb1q6rz28mcfaxtmd6v789l9rrlrusdprr9pqcpvkl";
  const B = "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx";
  test("validates and normalises", () => {
    const r = checkContact([], { name: "  Mama   Shop ", address: A }, T);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.contact.name).toBe("Mama Shop");
    expect(checkContact([], { name: "", address: A }, T).ok).toBe(false);
    const wrong = checkContact([], { name: "X", address: "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu" }, T);
    expect(wrong.ok).toBe(false);
  });
  test("no duplicate names or addresses; editing keeps id", () => {
    const first = checkContact([], { name: "Ada", address: A }, T);
    if (!first.ok) throw new Error();
    const book: Contact[] = [first.contact];
    expect(checkContact(book, { name: "ada", address: B }, T).ok).toBe(false);
    expect(checkContact(book, { name: "Bola", address: A }, T).ok).toBe(false);
    const edit = checkContact(book, { id: first.contact.id, name: "Ada K", address: A }, T);
    expect(edit.ok && edit.contact.id === first.contact.id).toBe(true);
  });
  test("resolves names, addresses and search", () => {
    const book: Contact[] = [
      { id: "1", name: "Ada", address: A, createdAt: 1 },
      { id: "2", name: "Bola Market", address: B, createdAt: 2 },
    ];
    expect(resolveRecipient(book, " ada ")).toMatchObject({ address: A, contact: { name: "Ada" } });
    expect(resolveRecipient(book, `bitcoin:${B}?amount=0.0001`)).toMatchObject({ address: B, amountSats: 10000, contact: { name: "Bola Market" } });
    expect(resolveRecipient(book, "tb1qunknown").contact).toBeUndefined();
    expect(searchContacts(book, "mark").map((c) => c.name)).toEqual(["Bola Market"]);
  });
});

import { identityFromPhrase, signPoolAddresses, verifyPoolAddress, POOL_START, normalizeUsername } from "../app/lib/wallet-core";

describe("@usernames", () => {
  test("pool addresses are signed by the identity key and verify; tampering fails", () => {
    const id = identityFromPhrase(PHRASE, T);
    const x = accountXpub(PHRASE, T);
    const pool = signPoolAddresses(x, id.privHex, T, POOL_START, 3);
    expect(pool.map((p) => p.index)).toEqual([1000, 1001, 1002]);
    expect(pool[0].address).toBe(addressAt(x, T, 0, 1000));
    expect(verifyPoolAddress(id.pubHex, T, pool[0].address, pool[0].signature)).toBe(true);
    expect(verifyPoolAddress(id.pubHex, T, pool[1].address, pool[0].signature)).toBe(false); // wrong address
    expect(verifyPoolAddress(id.pubHex, M, pool[0].address, pool[0].signature)).toBe(false); // wrong network
    const other = identityFromPhrase("legal winner thank year wave sausage worth useful legal winner thank yellow", T);
    expect(verifyPoolAddress(other.pubHex, T, pool[0].address, pool[0].signature)).toBe(false);
    expect(id.pubHex).toMatch(/^0[23][0-9a-f]{64}$/);
  });
  test("contacts can hold usernames; @ resolves", () => {
    const r = checkContact([], { name: "Ada", address: "@Ada_K" }, T);
    expect(r.ok && r.contact.username === "ada_k" && r.contact.address === "").toBe(true);
    if (!r.ok) throw new Error();
    expect(checkContact([r.contact], { name: "Other", address: "@ada_k" }, T).ok).toBe(false);
    expect(resolveRecipient([r.contact], "@ADA_K")).toMatchObject({ username: "ada_k", contact: { name: "Ada" } });
    expect(resolveRecipient([r.contact], "ada")).toMatchObject({ username: "ada_k" });
    expect(resolveRecipient([], "@new_person")).toMatchObject({ username: "new_person", address: "" });
    expect(normalizeUsername(" @Bob ")).toBe("bob");
  });
});
