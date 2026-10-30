"""Generate the pinned lnd gRPC stubs (phase 4, decision D11).

Downloads the lnd v0.21.4-beta release source (the SAME tag our provider
speaks to) and compiles its own .proto set with grpcio-tools into
``lightning_adapter/lnd_stubs/``. Generated code is committed so wire drift
against the pinned release is a reviewable diff - the same philosophy as the
DSH revision manifest (D8).

Layout produced:
    lnd_stubs/
      lightning_pb2{,_grpc,.pyi}          (lnrpc/lightning.proto)
      stateservice_pb2{,_grpc,.pyi}       (lnrpc/stateservice/stateservice.proto)
      walletunlocker_pb2{,_grpc,.pyi}     (lnrpc/walletunlocker.proto)
      routerrpc/ invoicesrpc/ walletrpc/ chainrpc/
      peersrpc/ signrpc/ autopilotrpc/    (subservice protos)

Re-run only on a deliberate re-pin; changing the pinned version requires
updating LND_VERSION in lightning_adapter/lnd_provider.py and re-recording
the version-specific API facts in the lnd provider notes in git history (Satish now uses Breez Spark, docs/wallet.md).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

LND_VERSION = "v0.21.4-beta"
LND_SOURCE_URL = (
    f"https://github.com/lightningnetwork/lnd/archive/refs/tags/{LND_VERSION}.tar.gz"
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = (
    REPO_ROOT / "services" / "lightning-adapter" / "lightning_adapter" / "lnd_stubs"
)

# top-level modules: (proto relative to the lnrpc/ -I root, module stem)
TOP_LEVEL = [
    ("lightning.proto", "lightning"),
    ("stateservice.proto", "stateservice"),
    ("walletunlocker.proto", "walletunlocker"),
]

# subpackages: (package dir, proto relative to lnrpc/)
SUBPACKAGES = [
    ("routerrpc", "routerrpc/router.proto"),
    ("invoicesrpc", "invoicesrpc/invoices.proto"),
    ("walletrpc", "walletrpc/walletkit.proto"),
    ("chainrpc", "chainrpc/chainnotifier.proto"),
    ("peersrpc", "peersrpc/peers.proto"),
    ("signrpc", "signrpc/signer.proto"),
    ("autopilotrpc", "autopilotrpc/autopilot.proto"),
]

PKG_PREFIX = "lightning_adapter.lnd_stubs"


def _rewrite_imports(text: str) -> str:
    """Make generated sibling imports package-absolute.

    protoc emits ``from lnrpc import lightning_pb2 ...`` /
    ``import lightning_pb2 ...``; inside our package those names only
    resolve after rewriting to ``lightning_adapter.lnd_stubs.*``.
    """
    for name in (
        "lnrpc",
        "routerrpc",
        "invoicesrpc",
        "walletrpc",
        "chainrpc",
        "peersrpc",
        "signrpc",
        "autopilotrpc",
        "lightning_pb2",
        "stateservice_pb2",
        "walletunlocker_pb2",
    ):
        text = text.replace(
            f"from {name} import", f"from {PKG_PREFIX}.{name} import"
        )
        text = text.replace(
            f"from {name}.", f"from {PKG_PREFIX}.{name}."
        )
        text = text.replace(
            f"import {name}.", f"import {PKG_PREFIX}.{name}."
        )
        # bare module import inside the same package (grpc files):
        if name.endswith("_pb2"):
            text = text.replace(
                f"\nimport {name} ", f"\nfrom {PKG_PREFIX} import {name} "
            )
            text = text.replace(
                f"\nimport {name}\n", f"\nfrom {PKG_PREFIX} import {name}\n"
            )
    return text


def download_source(dest: Path) -> Path:
    tar_path = dest / "lnd-source.tar.gz"
    print(f"downloading {LND_VERSION} source ...")
    urllib.request.urlretrieve(LND_SOURCE_URL, tar_path)
    extract_dir = dest / "lnd-src"
    extract_dir.mkdir(exist_ok=True)
    with tarfile.open(tar_path) as tar:
        tar.extractall(extract_dir, filter="data")
    return extract_dir / f"lnd-{LND_VERSION.lstrip(chr(118))}"


def _compile(src_root: Path, proto: str, out: Path) -> None:
    """Compile a proto path relative to src_root/lnrpc (lnd's single -I root).

    lnd's protos import siblings as ``lightning.proto`` and subpackages as
    ``signrpc/signer.proto`` - all relative to ``lnrpc/`` - so that single
    -I resolves everything. Outputs land under ``out`` mirroring the proto's
    path below lnrpc/; callers relocate.
    """
    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{src_root / 'lnrpc'}",
        f"--python_out={out}",
        f"--grpc_python_out={out}",
        f"--pyi_out={out}",
        proto,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=src_root / "lnrpc")
    if proc.returncode != 0:
        raise RuntimeError(f"protoc failed for {proto}:\n{proc.stderr}")


def _relocate(src: Path, dst: Path, stem: str) -> None:
    """Move generated <stem>_pb2* files from src (mirrored tree) up to dst."""
    for suffix in ("_pb2.py", "_pb2.pyi", "_pb2_grpc.py"):
        candidate = src / (stem + suffix)
        if candidate.exists():
            shutil.move(str(candidate), dst / (stem + suffix))


def generate(src_root: Path) -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)
    (OUT_DIR / "__init__.py").write_text(
        '"""Generated lnd gRPC stubs - pinned '
        f"{LND_VERSION} release protos.\n\n"
        "Do not edit by hand; regenerate via scripts/gen_lnd_stubs.py.\n"
        '"""\n'
    )

    for proto, stem in TOP_LEVEL:
        _compile(src_root, proto, OUT_DIR)
        _relocate(OUT_DIR / "lnrpc", OUT_DIR, stem)
        for suffix in ("_pb2.py", "_pb2.pyi", "_pb2_grpc.py"):
            path = OUT_DIR / (stem + suffix)
            if path.exists():
                path.write_text(_rewrite_imports(path.read_text()))
        print(f"  {stem}: top-level ok")

    for pkg_dir, proto in SUBPACKAGES:
        pkg_out = OUT_DIR / pkg_dir
        pkg_out.mkdir(exist_ok=True)
        (pkg_out / "__init__.py").write_text("")
        _compile(src_root, proto, OUT_DIR)
        # lnrpc/<pkg>/<stem>_pb2* -> <pkg>/<stem>_pb2*
        mirrored = OUT_DIR / "lnrpc" / pkg_dir
        _relocate(mirrored, pkg_out, Path(proto).stem)
        for py in pkg_out.glob("*_pb2*.py"):
            py.write_text(_rewrite_imports(py.read_text()))
        print(f"  {pkg_dir}: {len(list(pkg_out.glob('*.py')))} files")

    shutil.rmtree(OUT_DIR / "lnrpc", ignore_errors=True)
    print(f"stubs written to {OUT_DIR}")


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="lnd-stubs-"))
    try:
        src_root = download_source(workdir)
        generate(src_root)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
