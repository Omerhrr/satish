# Wallet integration contract (phase-3, decision D10)

Status: **implemented and proven on bitcoin regtest** (101 tests including a
spawning-bitcoind integration suite). Mainnet remains release-gated.

## What was selected, and what was honestly evaluated

| Criterion | bdkpython 3.1.1 (BDK 1.x core) | bitcoind wallet | Electrum-as-library |
| --- | --- | --- | --- |
| Python binding | official UniFFI wheel, no Rust toolchain at deploy | JSON-RPC only (no key mgmt in app) | import-only, heavy transitive deps |
| Key/PSBT layer | BIP39/32/84/389, PSBT sign+finalize in-process | keys live in wallet.dat (server custody, opaque) | possible but drags Qt ecosystem |
| License | MIT/Apache-2.0 | MIT | MIT |
| Maintenance | bitcoindevkit.org, active 2026 | active but wrong layer for app-side keys | slower release cadence |
| Regtest story | proven here end-to-end | same node, but keys+node coupling rejected by threat model | n/a |

`scripts/regtest_proof.py` is the recorded evidence: it spawns bitcoind 29.0,
then runs create → receive → balance → fee → PSBT → sign → finalize →
testmempoolaccept → broadcast → confirm → restore + failure paths, all green.

## Custody model (read before touching anything)

1. **Nothing secret is ever persisted.** Each wallet's on-disk state
   (`data/wallets/wallet-<id>.sqlite`) is created from **public descriptors**.
   A test reads the sqlite bytes and asserts no mnemonic word-pair and no
   `xprv`/`tprv` appears.
2. **Signing is memory-only.** `unlock` verifies the phrase against the
   wallet descriptor (mismatch ⇒ `MnemonicMismatch`), builds a private
   in-memory wallet, and holds it for `XP_WALLET_UNLOCK_TTL_MINUTES`
   (default 10). `lock` or TTL expiry drops it. The phrase is never written
   to disk, DB, logs, task context, or Telegram.
3. **Two-wallet split.** The persisted public wallet owns the UTXO graph and
   builds the PSBT; the unlocked private wallet signs it (its derivation
   coverage is synced to the persisted wallet's indexes at unlock time).
4. **Agents never sign.** `sign_prepared` rejects `agent:*`/`dsh` actors
   unconditionally (`AgentSigningForbidden` → HTTP 403).
5. **The review binds the signature.** `prepare` returns the review payload
   (network, destination, amount, fee, warnings) plus a SHA-256
   `authorization_digest` over exactly those fields. `sign` requires the
   digest to match. What was shown is what gets signed - no substitution.
6. **Aliases are labels.** Aliases are unique per user; `prepare` resolves an
   alias once and the digest binds the resolved address, so relabeling the
   address book cannot redirect a prepared transaction (tested).
7. **This is a server-side signing vault.** Do not describe it as
   non-custodial or browser-side; the capabilities endpoint discloses this.

## Transaction policy (map to HTTP)

| Step | Endpoint | Errors |
| --- | --- | --- |
| create | `POST /api/v1/wallets` | 422 bad word count |
| restore | `POST /api/v1/wallets/restore` | 422 invalid mnemonic; idempotent re-open |
| list | `GET /api/v1/wallets` | - |
| balance | `GET /api/v1/wallets/{id}/balance` | 404 foreign/unknown id |
| unlock | `POST /api/v1/wallets/{id}/unlock` | 403 wrong phrase; 422 garbage |
| lock | `POST /api/v1/wallets/{id}/lock` | - |
| derive address (+alias) | `POST /api/v1/wallets/{id}/addresses` | 409 alias taken |
| address book | `GET /wallets/{id}/addresses`, `PATCH /wallets/{id}/addresses/{addr}` | 404 |
| prepare | `POST /wallets/{id}/prepare` | 422 dust/unparseable/wrong network; 409 insufficient funds |
| review | response of prepare + `provider.prepared_review` | 404 unknown prepared id |
| sign | `POST /wallets/{id}/sign` | 403 agent/mismatch; 423 vault locked; 404 |
| broadcast | `POST /wallets/{id}/broadcast` | 502 definite reject; 504 uncertain (node down) |
| history | `GET /wallets/{id}/transactions` | - |

Fee policy: `estimatesmartfee 6` when the chain source has data; otherwise
`XP_WALLET_FALLBACK_FEE_RATE_SAT_VB` (default 2) with an explicit warning;
every request is capped at `XP_WALLET_MAX_FEE_RATE_SAT_VB` (default 50) and
clamping is disclosed in the review warnings.

## Chain-source seam

On regtest there is no electrs/esplora. Relevant transactions enter the wallet
graph via `provider.import_transaction(raw_hex)` ("bring-your-own-chain-source");
the API's `reopen()` restores graph/balance/addresses from the public
descriptor sqlite after a restart. Swapping in a full Electrum/Esplora sync
later means replacing only this seam - the signing, review, and policy layers
are untouched.

## Backup, restore, and migration guide

**What a user must back up:** the 24-word BIP39 recovery phrase, shown ONCE by
`POST /wallets` (`mnemonic_once`) and never again. The phrase IS the wallet:
wallet ids are deterministic (`descriptor_id`), so the same phrase always
reopens the same addresses, history, and funds.

**Restore drill (tested):**
1. `POST /api/v1/wallets/restore {"mnemonic": "…"}` - same id, same first
   address as the original wallet.
2. After a server restart, `reopen()` needs only the stored public
   descriptors; the user's phrase is required again only for signing.
3. Export/verify flow: the Mini App shows the phrase once behind a
   security-sensitive action; the user verifies possession by checking the
   first address offline before trusting the backup.

**Migration:** copy nothing but the phrase. The sqlite files are cache, not
truth; deleting them and restoring from the phrase rebuilds state.

**Honest limitation:** until phase-4 adds external-signer support, phrase
entry during unlock transmits the phrase to the API over TLS. That is the
known cost of the server-side signing-vault design and is disclosed in the
Mini App wallet screen.

## Configuration

```
XP_WALLET_DATA_DIR=./data/wallets
XP_BITCOIND_RPC_URL=http://127.0.0.1:18443   # absent ⇒ chain ops disabled
XP_BITCOIND_RPC_USER=...
XP_BITCOIND_RPC_PASSWORD=...
XP_WALLET_UNLOCK_TTL_MINUTES=10
XP_WALLET_FALLBACK_FEE_RATE_SAT_VB=2
XP_WALLET_MAX_FEE_RATE_SAT_VB=50
XP_WALLET_DEFAULT_WORD_COUNT=24
```

## Open items (honest)

- Full chain-source sync (Electrum/Esplora) for automatic balance discovery -
  `import_transaction` seam is the replacement point.
- Browser-side / external-signer signing (phase-4+) to close the
  phrase-over-TLS window entirely.
- Mainnet enablement waits on the security-review release gate (provider
  constructor refuses it today).
- Lightning (phase-4) selection (LDK vs CLN vs lnd) is a separate decision -
  no Lightning code depends on this one.
