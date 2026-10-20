# Wallet (decision D22): self-custodial, on the user's device

**Status:** implemented in the Mini App (`apps/web/app/lib/wallet-core.ts`,
`apps/web/app/composables/useWallet.ts`, `apps/web/app/pages/wallet.vue`).
Testnet4 by default; mainnet with `NUXT_PUBLIC_BITCOIN_NETWORK=mainnet`.
The server has **no wallet endpoints**: there is nothing on it to hack, leak
or subpoena that could move a user's bitcoin.

## Custody model (read before touching anything)

1. **Keys are born and live on the phone.** A BIP39 phrase (12 words) is
   generated with the browser's CSPRNG (`@scure/bip39`). Accounts are BIP84
   native SegWit, `m/84'/0'/0'` (mainnet) or `m/84'/1'/0'` (testnet).
2. **At rest the phrase is encrypted** with the user's wallet password:
   PBKDF2-SHA256 (310,000 iterations) → AES-256-GCM (WebCrypto). Only the
   ciphertext and the public account key (xpub, watch-only) are stored, in
   the Telegram webview's local storage, keyed per network and Telegram user.
3. **The phrase is decrypted only to sign**, inside one function call, and
   never leaves the device. Signing uses `@scure/btc-signer` (audited, pure TS).
4. **Before signing** the user sees recipient (name and full address), amount,
   fee and total; the signer refuses coins whose derived address doesn't match
   (`SendError`) and checks the final fee equals the reviewed fee.
5. **Chain data and broadcast** go to an Esplora API (default mempool.space,
   `NUXT_PUBLIC_ESPLORA_URL` to use your own). Trade-off: the API sees which
   addresses are queried (KL-17).
6. **Optional backup** to the user's own Telegram Cloud Storage, still
   encrypted with the wallet password (D25). The 12 words remain the master key.
7. **The AI agent and the XP server cannot sign or see the phrase**; they
   are not in the code path at all.

## Features

Create (with a 3-word backup check), restore (12/24 words or Telegram
backup), balance (confirmed + pending), history (explorer links), receive
(fresh address after each payment, BIP21 QR), send (address, contact name or
scanned QR; Fast/Normal/Slow fee; Max; RBF-enabled), address book (D22a),
show phrase, change password, remove from device, buy bitcoin (D24), pay for
XP in one tap (D23), naira values on mainnet.

## Evidence

- `apps/web/tests/wallet-core.test.ts`: official BIP84 vectors (mainnet +
  testnet), encryption round-trip and wrong password, network mismatch,
  BIP21 parsing, coin selection (change, dust, max, insufficient), a fully
  signed transaction, refusal to sign foreign coins, gap-limit scanning and
  history against a fake Esplora, address book rules.
- `apps/web/tests/cloud-backup.test.ts`: backup round-trip, chunking,
  nothing readable in the cloud, wrong password, damaged contacts.
- Browser click-throughs (create → receive → send → reopen; restore from
  Telegram on a "new phone"; pay an XP pack from the wallet against the real
  API in on-chain mode) were run headless before each release.

## Retired

The earlier server-side BDK wallet (phrase sent to the server to unlock and
sign) was removed: it contradicted the self-custody claim. Its database
tables remain (empty) so existing migrations, export and closure keep working.
