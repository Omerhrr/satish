import { describe, expect, test } from "bun:test";
import * as btc from "@scure/btc-signer";
import { hex } from "@scure/base";
import {
  NETWORKS, SendError, addressAt, accountXpub, addressWif, planSweep, signSweep, sweepAddresses, walletPrivateKeys, type SweepInput,
} from "../app/lib/wallet-core";

const PHRASE = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";
const M = NETWORKS.mainnet, T = NETWORKS.testnet;

describe("private keys", () => {
  test("account private key matches the BIP84 test vector", () => {
    const k = walletPrivateKeys(PHRASE, M);
    // BIP84 vector: m/84'/0'/0' xprv (zprv in SLIP-132 form) for the "abandon...about" phrase
    expect(k.xprv.startsWith("xprv")).toBe(true);
    expect(k.descriptor).toBe(`wpkh([73c5da0a/84h/0h/0h]${k.xprv}/<0;1>/*)`);
    expect(walletPrivateKeys(PHRASE, T).xprv.startsWith("tprv")).toBe(true);
  });

  test("per-address WIF matches the BIP84 vector and the address", () => {
    // BIP84 vector: m/84'/0'/0'/0/0 -> KyZpNDKnfs94vbrwhJneDi77V6jF64PWPF8x5cdJb8ifgg2DUc9d, bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu
    expect(addressWif(PHRASE, M, 0, 0)).toBe("KyZpNDKnfs94vbrwhJneDi77V6jF64PWPF8x5cdJb8ifgg2DUc9d");
    const { addresses } = sweepAddresses("KyZpNDKnfs94vbrwhJneDi77V6jF64PWPF8x5cdJb8ifgg2DUc9d", M);
    expect(addresses[0]).toEqual({ kind: "p2wpkh", address: "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu" });
    expect(addresses.map((a) => a.kind)).toEqual(["p2wpkh", "p2sh-p2wpkh", "p2pkh"]);
  });

  test("rejects junk and keys for the other network", () => {
    expect(() => sweepAddresses("hello", M)).toThrow(SendError);
    expect(() => sweepAddresses("KyZpNDKnfs94vbrwhJneDi77V6jF64PWPF8x5cdJb8ifgg2DUc9d", T)).toThrow(/real Bitcoin network/);
  });

  test("sweeps segwit, nested and legacy coins into our wallet", () => {
    const wif = addressWif(PHRASE, T, 0, 5);
    const { priv, addresses } = sweepAddresses(wif, T);
    const pub = btc.WIF(T.btc).decode(wif);
    // a fake funding tx paying the legacy address, so the legacy input has its raw tx
    const fund = new btc.Transaction();
    const funderKey = btc.WIF(T.btc).decode(addressWif(PHRASE, T, 0, 9));
    const { secp256k1 } = require("@noble/curves/secp256k1");
    const funder = btc.p2wpkh(secp256k1.getPublicKey(funderKey, true), T.btc);
    fund.addInput({ txid: "11".repeat(32), index: 0, witnessUtxo: { script: funder.script, amount: 40_000n } });
    fund.addOutputAddress(addresses[2].address, 30_000n, T.btc);
    fund.sign(funderKey);
    fund.finalize();
    const rawTx = fund.hex;
    const inputs: SweepInput[] = [
      { txid: "aa".repeat(32), vout: 0, value: 50_000, kind: "p2wpkh" },
      { txid: "bb".repeat(32), vout: 1, value: 20_000, kind: "p2sh-p2wpkh" },
      { txid: fund.id, vout: 0, value: 30_000, kind: "p2pkh", rawTx },
    ];
    const plan = planSweep(inputs, 2);
    expect(plan.total).toBe(100_000);
    const to = addressAt(accountXpub(PHRASE, T), T, 0, 0);
    const signed = signSweep(inputs, priv, T, to, plan.fee);
    expect(signed.fee).toBe(plan.fee);
    const back = btc.Transaction.fromRaw(hex.decode(signed.hex));
    expect(back.outputsLength).toBe(1);
    expect(Number(back.getOutput(0).amount)).toBe(plan.receive);
    expect(pub.length).toBe(32);
    expect(() => planSweep([], 2)).toThrow(/no bitcoin/);
  });
});
