"""Generate an Ed25519 key pair for signing Onramper buy links.

Put the PRIVATE line in deploy/.env as XP_ONRAMPER_SIGNING_KEY and register
the PUBLIC key with Onramper (dashboard / support). Never share the private key.
"""

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

key = Ed25519PrivateKey.generate()
private_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
public_pem = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
print("XP_ONRAMPER_SIGNING_KEY=" + private_pem.strip().replace("\n", "\\n"))
print()
print("Public key to give Onramper:")
print(public_pem)
