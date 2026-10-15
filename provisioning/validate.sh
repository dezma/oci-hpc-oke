#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python3 -m compileall -q "$ROOT/control/app" "$ROOT/control/validation"
PYTHONPATH="$ROOT/control" python3 -m pytest -q "$ROOT/tests"
python3 - <<PY
import pathlib, yaml
for p in pathlib.Path('$ROOT/terraform').glob('*.yaml'):
    list(yaml.safe_load_all(p.read_text()))
print('YAML parse: ok')
PY
node --check "$ROOT/control/web/app.js" >/dev/null 2>&1 || {
  echo 'Node.js unavailable or JavaScript syntax check failed.' >&2
  exit 1
}
for f in "$ROOT"/provisioning/*.sh; do
  bash -n "$f"
done
if command -v terraform >/dev/null 2>&1; then
  terraform -chdir="$ROOT/terraform" fmt -check -recursive
  if [[ -d "$ROOT/terraform/.terraform" ]]; then
    terraform -chdir="$ROOT/terraform" validate
  else
    echo 'terraform provider validation skipped: run terraform init -backend=false first'
  fi
else
  echo 'terraform not installed: skipped terraform fmt/validate'
fi
