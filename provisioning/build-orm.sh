#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT_DIR="$ROOT/dist"
mkdir -p "$OUT_DIR"

if [[ "${OKE_RDMA_SKIP_VENDOR:-0}" == "1" ]]; then
  OUT="$OUT_DIR/oci-oke-rdma-quickstart-orm-dev.zip"
  "$ROOT/provisioning/build-operator-payload.sh" --no-vendor
  echo "WARNING: building a development-only Resource Manager package without vendored Python wheels." >&2
else
  OUT="$OUT_DIR/oci-oke-rdma-quickstart-orm.zip"
  "$ROOT/provisioning/build-operator-payload.sh"
fi

if command -v terraform >/dev/null 2>&1; then
  terraform -chdir="$ROOT/terraform" fmt -recursive
fi

rm -f "$OUT"
(
  cd "$ROOT/terraform"
  zip -qr "$OUT" . \
    -x '.terraform/*' \
    -x '*.tfstate' \
    -x '*.tfstate.*' \
    -x '*.tfplan'
)
printf 'Resource Manager stack package: %s\n' "$OUT"
