import { describe, expect, test } from "bun:test";
import { NETWORKS, identityFromPhrase, signSparkAddress, verifySparkAddress } from "../app/lib/wallet-core";

const PHRASE = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";
const T = NETWORKS.testnet;
const SPARK = "sprt1pgssyuuuhnrrdjswal5c3s3rafw9w3y5dd4cjy3duxlf7hjzkp0rqx6dj6mrhu";

describe("@username Lightning address signatures", () => {
  test("sign, verify, and bound to network + address", () => {
    const id = identityFromPhrase(PHRASE, T);
    const sig = signSparkAddress(id.privHex, T, "regtest", SPARK);
    expect(verifySparkAddress(id.pubHex, T, "regtest", SPARK, sig)).toBe(true);
    expect(verifySparkAddress(id.pubHex, T, "mainnet", SPARK, sig)).toBe(false);
    expect(verifySparkAddress(id.pubHex, T, "regtest", SPARK.slice(0, -2) + "qq", sig)).toBe(false);
    expect(verifySparkAddress(id.pubHex, T, "regtest", SPARK, "zz")).toBe(false);
  });
});
