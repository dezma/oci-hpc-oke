#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CONTROL="$ROOT/control"
OUT="$ROOT/terraform/operator/payload/oke-rdma-control.tar.gz"
VENDOR=1
if [[ "${1:-}" == "--no-vendor" ]]; then VENDOR=0; fi
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/payload/wheelhouse"
cp -R "$CONTROL/app" "$CONTROL/web" "$CONTROL/validation" "$TMP/payload/"
find "$TMP/payload" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$TMP/payload" -type f -name "*.pyc" -delete
cp "$CONTROL/requirements.lock" "$TMP/payload/requirements.lock"

if [[ $VENDOR -eq 1 ]]; then
  python3 -m pip download --only-binary=:all: -r "$CONTROL/requirements.lock" -d "$TMP/payload/wheelhouse"
else
  printf '%s\n' 'No vendored wheels in this development payload. build-orm.sh vendors them by default.' > "$TMP/payload/wheelhouse/README.txt"
fi

mkdir -p "$(dirname "$OUT")"
tar -C "$TMP/payload" -czf "$OUT" .
printf 'Wrote %s\nSHA256 %s\n' "$OUT" "$(sha256sum "$OUT" | awk '{print $1}')"
