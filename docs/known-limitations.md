# Known limitations

What Satish can't do yet, or does with a catch. If you find something missing from this list, please add it.

## Security and trust

| | What it means | Plan |
|---|---|---|
| No independent security review yet | The code is tested and reviewed internally, but no outside auditor has checked it. On mainnet the app suggests keeping only spending money in Satish. | An external review before encouraging larger balances. |
| The operator Lightning wallet's phrase is on the server | Whoever controls the server could spend what's in that wallet: TK income, and developer Lightning payments during the seconds before they are forwarded. | Keep a small balance there and move income out often. Longer term, a design where Satish never holds payments, even briefly. |
| Forwarding developer Lightning payments may raise licensing questions | Satish briefly receives money on a developer's behalf. | Get legal advice before running this at scale on mainnet. |
| Spark's trust model | Lightning transfers are co-signed by independent operators. They can't take funds, and people can always withdraw on-chain, but it is weaker than plain Bitcoin. | Explained in the app; keep savings on Bitcoin. |

## Lightning

| | What it means | Plan |
|---|---|---|
| Lightning on the test network can't pay real Lightning invoices | Spark's regtest is a private test network. | Test real Lightning on mainnet with small amounts. |
| Moving money between Bitcoin and Lightning is mainnet only | The test networks for each are different chains. | None needed. |
| Forwarding only works to Spark addresses | A developer's payments are forwarded to their Satish (Spark) Lightning wallet. | Allow other Lightning addresses. |
| Lightning paths haven't run against the live network from our build machines | They are tested against a stand-in built to the real SDK's types, and run on the deployed app. | Keep testing on the live deployment. |

## Bitcoin

| | What it means | Plan |
|---|---|---|
| mempool.space sees which addresses a wallet looks up | Privacy. | Point `NUXT_PUBLIC_ESPLORA_URL` at your own server. |
| Payment alerts can lag a minute or two | They check public servers every minute. | Own server or a push feed. |
| The receiver can't speed up a stuck incoming payment | Only the sender can (replace-by-fee). | Child-pays-for-parent. |
| On-chain fees are high for small TK purchases | On mainnet a fee can be a few hundred sats. | Use Lightning for small amounts. |

## Other

| | What it means | Plan |
|---|---|---|
| Buying bitcoin needs an Onramper account | Off until the keys are set; the app shows a "buy on an exchange and withdraw" guide instead. Naira availability depends on Onramper's partners. | Set up the account. |
| Some translations need review | Hausa, Yoruba, Igbo and Pidgin text was written without native-speaker review; untranslated screens fall back to English. | Native review. |
| The wallet isn't synced between devices | Each device restores from the 12 words or the Telegram backup. | By design: keys stay per device. |
| Satish AI quality depends on outside services | DeepSeek for answers, Brave Search for better results. Without keys it gives placeholder answers. | Set the keys. |
| The ad-library tool uses sample data | The commerce comparison logic is real, but there is no live ad-library connection. | A live connector. |
| Operator tools use one shared credential | `/ops` needs `XP_OPS_OPERATOR_TOKEN`, but there are no per-person operator accounts. | Per-operator sign-in. |
| Closing an account needs a zero TK balance | Since everyone starts with 300 free TK, people must spend it or ask the operator before closing. | Let people give up leftover TK when closing. |
| No automated CI on GitHub yet | Tests are run before each release by hand. | Add GitHub Actions. |
