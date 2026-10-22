import { describe, expect, test } from "bun:test";
import * as btc from "@scure/btc-signer";
import {
  NETWORKS, Esplora, POOL_START, accountXpub, addressAt, buildHistory, historyCsv, planBump,
  scanAddresses, signTx, walletDescriptors, SendError, type AddressInfo, type EsploraTx, type Utxo,
} from "../app/lib/wallet-core";

const PHRASE = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";
const T = NETWORKS.testnet, M = NETWORKS.mainnet;
const X = accountXpub(PHRASE, T);
const EXT = "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx";

function fakeChain(funded: Map<string, number>) {
  let calls = 0;
  const fetchImpl = async (url: string) => {
    calls++;
    const v = funded.get(url.split("/address/")[1]) ?? 0;
    const stats = { funded_txo_sum: v, spent_txo_sum: 0, tx_count: v ? 1 : 0 };
    return new Response(JSON.stringify({ chain_stats: stats, mempool_stats: { funded_txo_sum: 0, spent_txo_sum: 0, tx_count: 0 } }));
  };
  return { api: new Esplora("https://x", fetchImpl, { minGapMs: 0 }), calls: () => calls };
}

describe("restore finds @username payments", () => {
  test("coins at pool addresses are found with no help from the server", async () => {
    const chain = fakeChain(new Map([[addressAt(X, T, 0, POOL_START + 5), 40_000], [addressAt(X, T, 0, 3), 1_000]]));
    const infos = await scanAddresses(X, T, chain.api);
    const total = infos.filter((i) => i.txCount).reduce((s, i) => s + i.confirmed, 0);
    expect(total).toBe(41_000);
  });

  test("a later pool payment beyond a gap is found when the server says it was handed out", async () => {
    const far = POOL_START + 60;
    const chain = fakeChain(new Map([[addressAt(X, T, 0, far), 7_000]]));
    const blind = await scanAddresses(X, T, chain.api);
    expect(blind.some((i) => i.index === far && i.txCount)).toBe(false);
    const told = await scanAddresses(X, T, chain.api, { from: POOL_START, to: far });
    expect(told.find((i) => i.index === far)?.confirmed).toBe(7_000);
  });
});

function own(): AddressInfo[] {
  const list: AddressInfo[] = [];
  for (const change of [0, 1] as const)
    for (let i = 0; i < 5; i++) list.push({ address: addressAt(X, T, change, i), change, index: i, txCount: 1, confirmed: 0, unconfirmed: 0 });
  return list;
}

function pendingTx(inValue: number, outs: { address: string; value: number }[], fee: number, vsize: number): EsploraTx {
  return {
    txid: "aa".repeat(32), fee, weight: vsize * 4, status: { confirmed: false },
    vin: [{ txid: "bb".repeat(32), vout: 0, sequence: 0xfffffffd, prevout: { scriptpubkey_address: addressAt(X, T, 0, 0), value: inValue } }],
    vout: outs.map((o) => ({ scriptpubkey_address: o.address, value: o.value })),
  };
}

describe("speed up and cancel", () => {
  const CHANGE = addressAt(X, T, 1, 0);
  const tx = pendingTx(50_000, [{ address: EXT, value: 20_000 }, { address: CHANGE, value: 29_850 }], 150, 141);

  test("speed up keeps the recipient whole and takes the fee from change", () => {
    const p = planBump(tx, "speed", 5, own(), [], addressAt(X, T, 1, 1));
    expect(p.outputs[0]).toEqual({ address: EXT, value: 20_000 });
    expect(p.outputs[1].address).toBe(CHANGE);
    expect(p.fee).toBe(705);
    expect(p.outputs[1].value).toBe(50_000 - 20_000 - 705);
    expect(p.extraFee).toBe(555);
    const signed = signTx(p.inputs, p.outputs, p.fee, PHRASE, T);
    const parsed = btc.Transaction.fromRaw(Buffer.from(signed.hex, "hex"));
    expect(parsed.getInput(0).sequence).toBe(0xfffffffd);
    expect(signed.fee).toBe(705);
  });

  test("the new fee rate always goes up, even if a lower one is asked for", () => {
    const p = planBump(tx, "speed", 1, own(), [], CHANGE);
    expect(p.fee).toBeGreaterThan(150 + 140);
    expect(p.feeRate).toBeGreaterThan(p.oldFeeRate);
  });

  test("cancel sends everything back to our own address", () => {
    const back = addressAt(X, T, 1, 2);
    const p = planBump(tx, "cancel", 5, own(), [], back);
    expect(p.outputs).toHaveLength(1);
    expect(p.outputs[0].address).toBe(back);
    expect(p.outputs[0].value + p.fee).toBe(50_000);
    expect(p.outputs.some((o) => o.address === EXT)).toBe(false);
  });

  test("adds a spare coin when there's no change to take the fee from", () => {
    const tight = pendingTx(20_400, [{ address: EXT, value: 20_000 }], 400, 110);
    const spare: Utxo = { txid: "cc".repeat(32), vout: 1, value: 10_000, confirmed: true, address: addressAt(X, T, 0, 1), change: 0, index: 1 };
    expect(() => planBump(tight, "speed", 20, own(), [], CHANGE)).toThrow(SendError);
    const p = planBump(tight, "speed", 20, own(), [spare], CHANGE);
    expect(p.inputs).toHaveLength(2);
    expect(p.outputs[0]).toEqual({ address: EXT, value: 20_000 });
    const signed = signTx(p.inputs, p.outputs, p.fee, PHRASE, T);
    expect(signed.fee).toBe(p.fee);
  });

  test("refuses payments that used someone else's coins or are confirmed", () => {
    const foreign = { ...tx, vin: [{ ...tx.vin[0], prevout: { scriptpubkey_address: EXT, value: 50_000 } }] };
    expect(() => planBump(foreign, "speed", 5, own(), [], CHANGE)).toThrow(/another wallet/);
    expect(() => planBump({ ...tx, status: { confirmed: true } }, "cancel", 5, own(), [], CHANGE)).toThrow(/confirmed/);
  });

  test("history marks only our unconfirmed RBF payments as changeable", () => {
    const set = new Set(own().map((a) => a.address));
    const [h] = buildHistory([tx], set);
    expect(h.replaceable).toBe(true);
    const [c] = buildHistory([{ ...tx, status: { confirmed: true, block_time: 1 } }], set);
    expect(c.replaceable).toBe(false);
  });
});

describe("export", () => {
  test("descriptors match the standard BIP84 test vector", () => {
    const d = walletDescriptors(PHRASE, M);
    expect(d.fingerprint).toBe("73c5da0a");
    expect(d.xpub.startsWith("xpub")).toBe(true);
    expect(d.receive).toBe(`wpkh([73c5da0a/84h/0h/0h]${d.xpub}/0/*)`);
    expect(walletDescriptors(PHRASE, T).xpub.startsWith("tpub")).toBe(true);
  });

  test("CSV has notes and escapes commas", () => {
    const csv = historyCsv(
      [{ txid: "t1", amount: -5000, fee: 200, confirmed: true, time: 1_700_000_000, replaceable: false }],
      { t1: "rice, beans" },
    );
    expect(csv.split("\n")[0]).toBe("date,type,amount_sats,fee_sats,note,status,txid");
    expect(csv).toContain('"rice, beans"');
    expect(csv).toContain("sent,-5000,200");
  });
});

describe("chained pending payments", () => {
  test("a payment whose change is already spent can't be changed, and the newer one is listed first", () => {
    const set = new Set(own().map((a) => a.address));
    const CH = addressAt(X, T, 1, 0);
    const parent = pendingTx(50_000, [{ address: EXT, value: 20_000 }, { address: CH, value: 29_850 }], 150, 141);
    const child: EsploraTx = {
      txid: "dd".repeat(32), fee: 200, weight: 440, status: { confirmed: false },
      vin: [{ txid: parent.txid, vout: 1, sequence: 0xfffffffd, prevout: { scriptpubkey_address: CH, value: 29_850 } }],
      vout: [{ scriptpubkey_address: EXT, value: 29_650 }],
    };
    const h = buildHistory([parent, child], set);
    expect(h.map((x) => x.txid)).toEqual([child.txid, parent.txid]);
    expect(h[0].replaceable).toBe(true);
    expect(h[1].replaceable).toBe(false);
  });
});

describe("gentle with the Bitcoin network service", () => {
  test("never more than 3 requests at once, and rate limits are retried", async () => {
    let active = 0, peak = 0, calls = 0;
    const fetchImpl = async (url: string) => {
      calls++;
      active++;
      peak = Math.max(peak, active);
      await new Promise((r) => setTimeout(r, 5));
      active--;
      if (calls % 10 === 0) return new Response("slow down", { status: 429 });
      if (calls % 13 === 0) throw new TypeError("Failed to fetch");
      const stats = { funded_txo_sum: 0, spent_txo_sum: 0, tx_count: 0 };
      return new Response(JSON.stringify({ chain_stats: stats, mempool_stats: stats }));
    };
    const api = new Esplora("https://x", fetchImpl, { backoffMs: 1, minGapMs: 0 });
    const infos = await scanAddresses(X, T, api, undefined, { poolGap: 5 });
    expect(peak).toBeLessThanOrEqual(3);
    expect(infos.length).toBeGreaterThanOrEqual(35);
  }, 30000);

  test("gives up with a plain message after retries", async () => {
    const api = new Esplora("https://x", async () => new Response("no", { status: 429 }), { backoffMs: 1, retries: 2, minGapMs: 0 });
    await expect(api.address("tb1q")).rejects.toThrow(/busy/);
    const down = new Esplora("https://x", async () => { throw new TypeError("Failed to fetch"); }, { backoffMs: 1, retries: 1, minGapMs: 0 });
    await expect(down.address("tb1q")).rejects.toThrow(/Check your connection/);
  });

  test("a later sync scans only a few addresses past the last @username payment", async () => {
    let calls = 0;
    const fetchImpl = async () => {
      calls++;
      const stats = { funded_txo_sum: 0, spent_txo_sum: 0, tx_count: 0 };
      return new Response(JSON.stringify({ chain_stats: stats, mempool_stats: stats }));
    };
    await scanAddresses(X, T, new Esplora("https://x", fetchImpl, { minGapMs: 0 }), undefined, { poolGap: 5 });
    expect(calls).toBeLessThanOrEqual(40);
  });
});
