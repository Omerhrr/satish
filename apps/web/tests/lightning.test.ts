import { describe, expect, test } from "bun:test";
import { LightningError, LightningWallet, describeInput, feeOf, toLnPayment, type SdkModule } from "../app/lib/lightning";

const PHRASE = "abandon " .repeat(11) + "about";

function fakeModule(over: Record<string, unknown> = {}) {
  const calls: { connect?: any; receive: any[]; prepare: any[]; send: any[] } = { receive: [], prepare: [], send: [] };
  let inited = false;
  const sdk = {
    addEventListener: async () => "L1",
    removeEventListener: async () => true,
    disconnect: async () => undefined,
    getInfo: async () => ({ balanceSats: 5000, identityPubkey: "02ab", tokenBalances: new Map() }),
    listPayments: async () => ({
      payments: [
        { id: "p1", paymentType: "receive", status: "completed", amount: 2000n, fees: 0n, timestamp: 1_700_000_000, method: "lightning",
          details: { type: "lightning", description: "lunch", invoice: "lnbc", destinationPubkey: "", htlcDetails: {} } },
      ],
    }),
    receivePayment: async (r: any) => {
      calls.receive.push(r);
      return { paymentRequest: r.paymentMethod.type === "bolt11Invoice" ? "lnbcrt1fake" : "sp1fake", fee: 0n };
    },
    parse: async (t: string) => {
      if (t.startsWith("lnbc")) return { type: "bolt11Invoice", amountMsat: 2_000_000, description: "rice", timestamp: 2_000_000_000, expiry: 3600 };
      if (t.includes("@")) return { type: "lightningAddress", address: t, payRequest: { minSendable: 1000, maxSendable: 100_000_000, domain: "x" } };
      throw new Error("nope");
    },
    prepareSendPayment: async (r: any) => {
      calls.prepare.push(r);
      return { amount: r.amount ?? 2000n, feePolicy: "feesExcluded", paymentMethod: { type: "bolt11Invoice", lightningFeeSats: 3, sparkTransferFeeSats: undefined } };
    },
    sendPayment: async (r: any) => {
      calls.send.push(r);
      return { payment: { id: "s1", paymentType: "send", status: "completed", amount: 2000n, fees: 3n, timestamp: 1, method: "lightning" } };
    },
    listUnclaimedDeposits: async () => ({ deposits: [{ txid: "t", vout: 0, amountSats: 9000, isMature: true, claimError: { type: "maxDepositClaimFeeExceeded", requiredFeeSats: 700 } }] }),
    claimDeposit: async () => ({}),
    getLightningAddress: async () => undefined,
    checkLightningAddressAvailable: async () => true,
    registerLightningAddress: async (r: any) => ({ lightningAddress: `${r.username}@breez.tips` }),
    ...over,
  };
  const mod: SdkModule = {
    default: async () => {
      inited = true;
    },
    defaultConfig: (network) => ({ network } as any),
    connect: async (req) => {
      calls.connect = req;
      return sdk as any;
    },
  };
  return { mod, calls, sdk, inited: () => inited };
}

describe("lightning wallet", () => {
  test("opens with the same 12 words, separate storage per network and user", async () => {
    const f = fakeModule();
    const w = new LightningWallet(f.mod, "regtest", "", "42");
    await w.connect(PHRASE);
    expect(f.inited()).toBe(true);
    expect(f.calls.connect.seed).toEqual({ type: "mnemonic", mnemonic: PHRASE });
    expect(f.calls.connect.storageDir).toBe("satish-ln-regtest-42");
    expect(f.calls.connect.config.apiKey).toBeUndefined();
    expect(await w.balance()).toBe(5000);
  });

  test("mainnet refuses to start without an API key, and passes it when set", async () => {
    await expect(new LightningWallet(fakeModule().mod, "mainnet", "", "1").connect(PHRASE)).rejects.toThrow(/API key/);
    const f = fakeModule();
    await new LightningWallet(f.mod, "mainnet", "KEY", "1").connect(PHRASE);
    expect(f.calls.connect.config.apiKey).toBe("KEY");
  });

  test("invoices, Spark address, payments list", async () => {
    const f = fakeModule();
    const w = new LightningWallet(f.mod, "regtest", "", "1");
    await w.connect(PHRASE);
    expect((await w.invoice(2000, "lunch")).request).toBe("lnbcrt1fake");
    expect(f.calls.receive[0].paymentMethod).toMatchObject({ type: "bolt11Invoice", amountSats: 2000, description: "lunch" });
    await expect(w.invoice(1.5, "")).rejects.toThrow(LightningError);
    expect(await w.sparkAddress()).toBe("sp1fake");
    const [p] = await w.payments();
    expect(p).toMatchObject({ direction: "receive", amount: 2000, kind: "lightning", description: "lunch", status: "completed" });
  });

  test("parse, prepare with fee, send with idempotency key", async () => {
    const f = fakeModule();
    const w = new LightningWallet(f.mod, "regtest", "", "1");
    await w.connect(PHRASE);
    expect(await w.parse("lightning:lnbc2u1xyz")).toMatchObject({ kind: "invoice", amount: 2000, description: "rice", expired: false });
    expect(await w.parse("ada@wallet.com")).toMatchObject({ kind: "lightningAddress", min: 1, max: 100_000 });
    await expect(w.parse("hello")).rejects.toThrow(/doesn't look like/);
    const { prep, quote } = await w.prepare("lnbc2u1xyz");
    expect(quote).toEqual({ amount: 2000, fee: 3 });
    const key = "0b9f6a52-3c1e-4d8a-9f1b-2a7c5e6d4b31"; // Spark only accepts UUID keys
    await w.send(prep, key);
    expect(f.calls.send[0]).toMatchObject({ idempotencyKey: key, options: { type: "bolt11Invoice", preferSpark: true } });
    await w.send(prep, "not-a-uuid");
    expect(f.calls.send[1].idempotencyKey).toBeUndefined();
  });

  test("failed payments throw; deposits explain high fees; lightning address only on mainnet", async () => {
    const f = fakeModule({
      sendPayment: async () => ({ payment: { id: "x", paymentType: "send", status: "failed", amount: 1n, fees: 0n, timestamp: 1, method: "lightning" } }),
    });
    const w = new LightningWallet(f.mod, "regtest", "", "1");
    await w.connect(PHRASE);
    const { prep } = await w.prepare("lnbc");
    await expect(w.send(prep, "k")).rejects.toThrow(/failed/);
    expect((await w.unclaimedDeposits())[0].problem).toMatch(/700 sats/);
    expect(await w.lightningAddress()).toBeNull();
    await expect(w.registerLightningAddress("ada")).rejects.toThrow(/real Bitcoin network/);
    const m = fakeModule();
    const main = new LightningWallet(m.mod, "mainnet", "KEY", "1");
    await main.connect(PHRASE);
    expect(await main.registerLightningAddress("ada")).toBe("ada@breez.tips");
  });

  test("expired invoices and unified QR codes", () => {
    expect(describeInput({ type: "bolt11Invoice", timestamp: 100, expiry: 10, description: "" } as any, 1000)).toMatchObject({ expired: true });
    const bip21 = {
      type: "bip21", amountSat: 5000, uri: "", extras: [],
      paymentMethods: [{ type: "bitcoinAddress", address: "bc1qx" }, { type: "bolt11Invoice", amountMsat: 5_000_000, timestamp: 2_000_000_000, expiry: 60 }],
    } as any;
    expect(describeInput(bip21, 1_999_999_999)).toMatchObject({ kind: "invoice", amount: 5000 });
    expect(feeOf({ amount: 100n, paymentMethod: { type: "sparkAddress", fee: "0" } } as any)).toEqual({ amount: 100, fee: 0 });
    expect(toLnPayment({ id: "w", paymentType: "send", status: "pending", amount: 9n, fees: 1n, timestamp: 2, method: "withdraw" } as any).kind).toBe("withdraw");
  });

  test("disconnect forgets the session", async () => {
    const w = new LightningWallet(fakeModule().mod, "regtest", "", "1");
    await w.connect(PHRASE);
    await w.disconnect();
    expect(w.connected).toBe(false);
    await expect(w.balance()).rejects.toThrow(/Open your Lightning wallet/);
  });
});

import { lightningCsv } from "../app/lib/lightning";

describe("lightning csv", () => {
  test("exports payments with net amounts and safe quoting", () => {
    const csv = lightningCsv([
      { id: "a", direction: "receive", status: "completed", amount: 1500, fee: 0, time: 1761700000, kind: "lightning", description: "lunch, rice" },
      { id: "b", direction: "send", status: "completed", amount: 1000, fee: 3, time: 1761700100, kind: "spark", description: 'say "hi"' },
    ]);
    const lines = csv.trim().split("\r\n");
    expect(lines[0]).toBe("date,direction,type,status,amount_sats,fee_sats,net_sats,description,payment_id");
    expect(lines[1]).toContain(',1500,0,1500,"lunch, rice",a');
    expect(lines[2]).toContain(',1000,3,-1003,"say ""hi""",b');
  });
});
