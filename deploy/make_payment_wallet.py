"""Create the wallet that receives XP payments (run on YOUR computer, not the server).

Prints a 12-word recovery phrase (write it on paper; it controls the money)
and the PUBLIC account key (xpub) to put in deploy/.env as XP_ONCHAIN_XPUB.
The server only ever gets the public key: it can make payment addresses and
watch them, but it can never spend.

    python3 deploy/make_payment_wallet.py testnet
    python3 deploy/make_payment_wallet.py mainnet

You can also restore the phrase in any BIP84 wallet (Sparrow, BlueWallet,
or the XP wallet itself) to see and spend what customers paid.
"""

import secrets
import sys

from embit import bip32, bip39
from embit.networks import NETWORKS

network = (sys.argv[1] if len(sys.argv) > 1 else "testnet").lower()
if network not in ("testnet", "mainnet"):
    sys.exit("usage: make_payment_wallet.py testnet|mainnet")
net, coin = (NETWORKS["main"], 0) if network == "mainnet" else (NETWORKS["test"], 1)

phrase = bip39.mnemonic_from_bytes(secrets.token_bytes(16))
account = bip32.HDKey.from_seed(bip39.mnemonic_to_seed(phrase)).derive(f"m/84h/{coin}h/0h")
print("RECOVERY PHRASE (write on paper, never put on the server):")
print("  " + phrase)
print()
print(f"Put this in deploy/.env  ({network}, path m/84'/{coin}'/0'):")
print("  XP_ONCHAIN_XPUB=" + account.to_public().to_base58(version=net["xpub"]))
