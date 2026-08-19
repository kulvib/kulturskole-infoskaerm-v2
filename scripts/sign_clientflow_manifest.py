#!/usr/bin/env python3
"""Sign a trusted ClientFlow manifest/catalog without writing private keys to the repo."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from clientflow_manifest_crypto import SIGNATURE_ALGORITHM, public_key_id, sign_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path, help="Unsigned or previously signed manifest JSON")
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--passphrase-file", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    allowed_contracts = {
        (2, "stable-signed"),
        (3, "release-catalog-signed"),
    }
    contract = (manifest.get("manifest_schema"), manifest.get("channel"))
    if contract not in allowed_contracts:
        raise SystemExit(
            "Only schema 2/stable-signed or schema 3/release-catalog-signed may be signed"
        )
    manifest["signature_algorithm"] = SIGNATURE_ALGORITHM
    manifest["signature_key_id"] = public_key_id(args.public_key)
    manifest.pop("signature", None)
    manifest["signature"] = sign_manifest(
        manifest,
        args.private_key,
        passphrase_file=args.passphrase_file,
    )
    output = args.output or args.manifest
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Signed {output} with key {manifest['signature_key_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
