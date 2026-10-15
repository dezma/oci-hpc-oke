from __future__ import annotations
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "control"))
TMP = pathlib.Path(tempfile.gettempdir())
os.environ.setdefault("HPC_CONTROL_DB", str(TMP / "oke-rdma-control-test.db"))
os.environ.setdefault("HPC_CONTROL_DEMO_TOKEN", "demo")
os.environ.setdefault("HPC_CONTROL_RDMA_CONFIG", str(TMP / "oke-rdma-control-test-rdma.json"))

# Keep test runs deterministic even when a previous local test exercised the config endpoint.
try:
    pathlib.Path(os.environ["HPC_CONTROL_RDMA_CONFIG"]).unlink()
except FileNotFoundError:
    pass
