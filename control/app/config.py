from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Settings:
    environment_name: str
    region: str
    tenancy_id: str
    compartment_id: str
    cluster_id: str
    cluster_name: str
    node_pool_id: str
    compute_cluster_id: str
    kubeconfig: str
    sriov_operator_namespace: str
    nfd_addon_name: str
    cert_manager_addon_name: str
    network_operator_addon_name: str
    operator_kubernetes_access_mode: str
    worker_ssh_enabled: bool = False
    kubernetes_version: str = ""
    kubernetes_minor: str = ""
    ubuntu_release: str = "ubuntu-noble"
    oke_node_package: str = ""
    oke_repo_url: str = ""
    rdma_pf_name: str = ""
    rdma_mtu: int = 0
    rdma_vfs_per_node: int = 2
    rdma_resource_name: str = "oci_rdma_vf"
    rdma_ip_pool_cidr: str = "10.239.251.0/24"
    rdma_tools_image: str = ""
    mode: str = "live"
    workload_namespace: str = "rdma-workloads"

    @property
    def rdma_resource_full(self) -> str:
        return f"nvidia.com/{self.rdma_resource_name}"

    @property
    def vf_network_name(self) -> str:
        return f"{self.environment_name}-rdma-vf"

    @property
    def ip_pool_name(self) -> str:
        return f"{self.environment_name}-rdma-pool"

    @property
    def rdma_configured(self) -> bool:
        return bool(self.rdma_pf_name and self.rdma_mtu >= 1500)

    def rdma_config(self) -> dict[str, Any]:
        return {
            "rdma_pf_name": self.rdma_pf_name,
            "rdma_mtu": self.rdma_mtu,
            "rdma_vfs_per_node": self.rdma_vfs_per_node,
            "rdma_resource_name": self.rdma_resource_name,
            "rdma_ip_pool_cidr": self.rdma_ip_pool_cidr,
            "rdma_tools_image": self.rdma_tools_image,
        }


_RUNTIME_DEFAULTS: dict[str, Any] = {
    "rdma_pf_name": "",
    "rdma_mtu": 0,
    "rdma_vfs_per_node": 2,
    "rdma_resource_name": "oci_rdma_vf",
    "rdma_ip_pool_cidr": "10.239.251.0/24",
    "rdma_tools_image": "",
}


def _static_path() -> Path:
    return Path(os.environ.get("HPC_CONTROL_CONFIG", "/etc/oke-rdma-control/config.json"))


def _runtime_path(static_exists: bool | None = None) -> Path:
    explicit = os.environ.get("HPC_CONTROL_RDMA_CONFIG")
    if explicit:
        return Path(explicit)
    if static_exists is None:
        static_exists = _static_path().exists()
    if static_exists:
        return Path("/var/lib/oke-rdma-control/rdma-config.json")
    return Path("/tmp/oke-rdma-control-demo-rdma-config.json")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def load_settings() -> Settings:
    static_path = _static_path()
    static_exists = static_path.exists()

    if static_exists:
        base = _read_json(static_path)
        base.setdefault("mode", "live")
        # Keep in-place upgrades from older quickstart payloads usable. These
        # fields improve node diagnostics but an older static config may not
        # contain them yet. Empty values degrade to explicit "unavailable"
        # diagnostics rather than preventing the API from starting.
        base.setdefault("tenancy_id", "")
        base.setdefault("compartment_id", "")
        base.setdefault("node_pool_id", "")
        base.setdefault("compute_cluster_id", "")
        base.setdefault("nfd_addon_name", "NodeFeatureDiscovery")
        base.setdefault("cert_manager_addon_name", "CertManager")
        base.setdefault("worker_ssh_enabled", False)
    else:
        # Safe local development defaults. Demo mode never makes live OCI or cluster changes.
        base = {
            "environment_name": "oke-rdma-demo",
            "region": "eu-frankfurt-1",
            "tenancy_id": "ocid1.tenancy.demo",
            "compartment_id": "ocid1.compartment.demo",
            "cluster_id": "ocid1.cluster.demo",
            "cluster_name": "oke-rdma-demo-oke",
            "node_pool_id": "ocid1.nodepool.demo",
            "compute_cluster_id": "ocid1.computecluster.demo",
            "kubeconfig": "/tmp/nonexistent-kubeconfig",
            "sriov_operator_namespace": "nvidia-network-operator",
            "nfd_addon_name": "NodeFeatureDiscovery",
            "cert_manager_addon_name": "CertManager",
            "network_operator_addon_name": "NvidiaNetworkOperator",
            "operator_kubernetes_access_mode": "iam_admin",
            "worker_ssh_enabled": False,
            "kubernetes_version": "v1.36.4",
            "kubernetes_minor": "1.36",
            "ubuntu_release": "ubuntu-noble",
            "oke_node_package": "oci-oke-node-all-1.36.4",
            "oke_repo_url": "https://objectstorage.us-sanjose-1.oraclecloud.com/n/odx-oke/b/okn-repositories/o/prod/ubuntu-noble/kubernetes-1.36 stable main",
            "mode": "demo",
        }

    runtime = dict(_RUNTIME_DEFAULTS)
    runtime.update(_read_json(_runtime_path(static_exists)))

    # Demo starts with a useful example but keeps the values editable in the Control Center.
    if not static_exists and not _runtime_path(static_exists).exists():
        runtime.update({
            "rdma_pf_name": "ens800f0np0",
            "rdma_mtu": 4220,
            "rdma_tools_image": "example.invalid/rdma-tools@sha256:" + "0" * 64,
        })

    allowed = set(Settings.__dataclass_fields__)
    merged = {**base, **runtime}
    unknown = set(merged) - allowed
    if unknown:
        raise ValueError(f"Unsupported Control Center settings: {', '.join(sorted(unknown))}")
    return Settings(**merged)


def save_rdma_config(values: dict[str, Any]) -> Settings:
    """Persist only operator-configurable RDMA values using an atomic replace."""
    unknown = set(values) - set(_RUNTIME_DEFAULTS)
    if unknown:
        raise ValueError(f"Unsupported RDMA settings: {', '.join(sorted(unknown))}")

    path = _runtime_path(_static_path().exists())
    path.parent.mkdir(parents=True, exist_ok=True)
    current = dict(_RUNTIME_DEFAULTS)
    current.update(_read_json(path))
    current.update(values)

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return load_settings()


def public_settings(settings: Settings) -> dict[str, Any]:
    data = asdict(settings)
    # The kubeconfig path and cluster OCID are operational internals, not secrets, but the
    # UI only needs the product-facing subset below.
    return {
        "environment_name": data["environment_name"],
        "region": data["region"],
        "cluster_name": data["cluster_name"],
        "kubernetes_version": data["kubernetes_version"],
        "kubernetes_minor": data["kubernetes_minor"],
        "ubuntu_release": data["ubuntu_release"],
        "oke_node_package": data["oke_node_package"],
        "oke_repo_url": data["oke_repo_url"],
        "operator_kubernetes_access_mode": data["operator_kubernetes_access_mode"],
        "worker_ssh_enabled": data["worker_ssh_enabled"],
        "mode": data["mode"],
        "rdma": settings.rdma_config(),
    }
