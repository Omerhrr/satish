import { describe, expect, test } from "bun:test";
import { WrongPassword, encryptPhrase, type Contact } from "../app/lib/wallet-core";
import { backupContacts, backupWallet, deleteBackup, hasBackup, keys, newBackupKey, restoreBackup, type KeyValueStore } from "../app/lib/cloud-backup";

const PHRASE = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";

function memStore(): KeyValueStore & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    async getMany(ks) { return Object.fromEntries(ks.map((k) => [k, data.get(k) ?? ""])); },
    async set(k, v) {
      if (!/^[A-Za-z0-9_-]{1,128}$/.test(k)) throw new Error("bad key " + k);
      if (v.length > 4096) throw new Error("value too long");
      data.set(k, v);
    },
    async remove(ks) { ks.forEach((k) => data.delete(k)); },
  };
}

describe("telegram cloud backup", () => {
  test("round trip with contacts, nothing readable in the cloud", async () => {
    const kv = memStore();
    const bk = newBackupKey();
    const secret = await encryptPhrase(PHRASE, "pw-12345678");
    await backupWallet(kv, "testnet", { xpub: "tpubX", secret, backupKey: bk, createdAt: 1 }, "pw-12345678");
    const contacts: Contact[] = Array.from({ length: 40 }, (_, i) => ({ id: String(i), name: `Friend number ${i}`, address: "tb1q6rz28mcfaxtmd6v789l9rrlrusdprr9pqcpvkl", note: "school fees and rent", createdAt: i }));
    await backupContacts(kv, "testnet", bk, contacts);
    const dump = [...kv.data.values()].join("");
    expect(dump).not.toContain("abandon");
    expect(dump).not.toContain("Friend");
    expect(Number(kv.data.get(keys("testnet").count))).toBeGreaterThan(1); // chunked
    expect(await hasBackup(kv, "testnet")).toBe(true);
    expect(await hasBackup(kv, "mainnet")).toBe(false);
    const r = await restoreBackup(kv, "testnet", "pw-12345678");
    expect(r.phrase).toBe(PHRASE);
    expect(r.backupKey).toBe(bk);
    expect(r.contacts.length).toBe(40);
    expect(r.contacts[39].name).toBe("Friend number 39");
  });

  test("wrong password, damaged contacts, delete", async () => {
    const kv = memStore();
    const bk = newBackupKey();
    await backupWallet(kv, "testnet", { xpub: "x", secret: await encryptPhrase(PHRASE, "right-pass"), backupKey: bk, createdAt: 1 }, "right-pass");
    await expect(restoreBackup(kv, "testnet", "wrong-pass")).rejects.toBeInstanceOf(WrongPassword);
    await backupContacts(kv, "testnet", bk, [{ id: "1", name: "Ada", address: "tb1q", createdAt: 1 }]);
    kv.data.set(keys("testnet").chunk(0), "garbage.garbage");
    const r = await restoreBackup(kv, "testnet", "right-pass");
    expect(r.phrase).toBe(PHRASE);
    expect(r.contacts).toEqual([]); // wallet still recovers
    await deleteBackup(kv, "testnet");
    expect(await hasBackup(kv, "testnet")).toBe(false);
  });
});
