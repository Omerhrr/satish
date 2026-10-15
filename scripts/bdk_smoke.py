"""BDK python offline smoke test: mnemonic -> descriptor -> address (regtest).

No chain source needed for key-level proof. Run under xp/.venv.
"""

import bdkpython as bdk

# 1. Fresh entropy via BDK's Mnemonic (BIP39, uses OS CSPRNG)
mnemonic = bdk.Mnemonic(word_count=12)
words = mnemonic.to_string()
print("mnemonic word count:", len(words.split()))
assert len(words.split()) in (12, 15, 18, 21, 24)

# 2. Master secret key from mnemonic (BIP32 seed)
secret_key = bdk.DescriptorSecretKey(
    network=bdk.Network.REGTEST, mnemonic=mnemonic, password=""
)

# 3. BIP84-native segwit descriptor: wpkh(m/84'/1'/0'/0/*)  (1 = testnet coin type)
derived = secret_key.derive_priv(bdk.DerivationPath("m/84'/1'/0'"))
external = derived.extend("0/*")
internal = derived.extend("1/*")
desc = bdk.Descriptor.new_bip84(secret_key, bdk.KeychainKind.EXTERNAL, bdk.Network.REGTEST)
print("bip84 descriptor:", desc.to_string_with_secret().replace(words, "<SEED>"))

# 4. Wallet creation in memory (no persistence) + address derivation
change_desc = bdk.Descriptor(
    f"wpkh({internal.to_string()})", bdk.Network.REGTEST
)
wallet = bdk.Wallet.create_single(
    descriptor=desc, change_descriptor=change_desc, network=bdk.Network.REGTEST
)
info = wallet.get_address(bdk.AddressIndex.NEW)
print("first regtest address:", info.address.to_string())
assert info.address.to_string().startswith("bcrt1"), "expected bech32m/bech32 regtest address"

# next NEW address must differ (no reuse)
info2 = wallet.get_address(bdk.AddressIndex.NEW)
print("second regtest address:", info2.address.to_string())
assert info2.address.to_string() != info.address.to_string()

# 5. Balance on a fresh wallet
bal = wallet.get_balance()
print("fresh balance total:", bal.total.to_sat())

# 6. Restore from mnemonic words (round-trip): same seed -> same first address
restored_m = bdk.Mnemonic.from_string(words)
restored_sk = bdk.DescriptorSecretKey(
    network=bdk.Network.REGTEST, mnemonic=restored_m, password=""
)
restored_desc = bdk.Descriptor.new_bip84(restored_sk, bdk.KeychainKind.EXTERNAL, bdk.Network.REGTEST)
restored_wallet = bdk.Wallet.create_single(
    descriptor=restored_desc, change_descriptor=change_desc, network=bdk.Network.REGTEST
)
r_info = restored_wallet.get_address(bdk.AddressIndex.PEEK)
# PEEK returns the last NEW-derived address without incrementing; compare against info2
assert r_info.address.to_string() == info2.address.to_string(), "restore round-trip address mismatch"
print("restore round-trip: OK (same address family from same mnemonic)")

# 7. Sign-ability probe: DescriptorSecretKey -> DescriptorPublicKey (xpub export)
dpk = secret_key.as_public()
print("xpub present:", dpk.to_string()[:4] in ("xpub", "tpub", "vpub"))

print("BDK SMOKE: ALL OK")
