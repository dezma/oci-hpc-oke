from __future__ import annotations

import json
import subprocess

from fastapi.testclient import TestClient

from app.config import load_settings, save_rdma_config
from app.jobs import validate_request
from app.main import app
from app.provider import DemoProvider, LiveProvider


def test_demo_environment_never_claims_measurement():
    s = load_settings()
    p = DemoProvider(s)
    result = p.rdma_validation()
    assert result["status"] == "simulated"
    assert result["bandwidth_gbit_s"] is None


def test_mutating_action_requires_exact_environment_name():
    s = load_settings()
    try:
        validate_request(s, "configure_vfs", "wrong")
    except ValueError as exc:
        assert s.environment_name in str(exc)
    else:
        raise AssertionError("expected confirmation failure")
    validate_request(s, "configure_vfs", s.environment_name)


def test_api_requires_token():
    client = TestClient(app)
    assert client.get("/health/live").status_code == 200
    assert client.get("/api/v1/environment").status_code == 401
    ok = client.post("/api/v1/session", headers={"Authorization": "Bearer demo"})
    assert ok.status_code == 200
    env = client.get("/api/v1/environment", headers={"Authorization": "Bearer demo"})
    assert env.status_code == 200
    assert env.json()["mode"] == "demo"


def test_security_headers_present():
    client = TestClient(app)
    response = client.get("/")
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "geolocation=()" in response.headers["permissions-policy"]


def test_runtime_rdma_config_is_persisted_and_reloaded():
    before = load_settings()
    saved = save_rdma_config({
        "rdma_pf_name": "ens999f0np0",
        "rdma_mtu": 4220,
        "rdma_vfs_per_node": 3,
        "rdma_resource_name": "oci_rdma_vf",
        "rdma_ip_pool_cidr": "10.239.252.0/24",
        "rdma_tools_image": "example.invalid/tools@sha256:" + "a" * 64,
    })
    assert saved.rdma_pf_name == "ens999f0np0"
    assert saved.rdma_vfs_per_node == 3
    assert load_settings().rdma_ip_pool_cidr == "10.239.252.0/24"
    # Restore test defaults for the tests below.
    save_rdma_config(before.rdma_config())


def test_api_exposes_editable_rdma_config_and_demo_discovery():
    client = TestClient(app)
    headers = {"Authorization": "Bearer demo"}
    discovery = client.get("/api/v1/rdma/discovery", headers=headers)
    assert discovery.status_code == 200
    assert discovery.json()["recommended"]["name"] == "ens800f0np0"

    payload = {
        "rdma_pf_name": "ens800f0np0",
        "rdma_mtu": 4220,
        "rdma_vfs_per_node": 2,
        "rdma_resource_name": "oci_rdma_vf",
        "rdma_ip_pool_cidr": "10.239.251.0/24",
        "rdma_tools_image": "example.invalid/rdma-tools@sha256:" + "b" * 64,
    }
    updated = client.put("/api/v1/rdma/config", headers=headers, json=payload)
    assert updated.status_code == 200
    assert updated.json()["configured"] is True
    config = client.get("/api/v1/rdma/config", headers=headers).json()
    assert config["config"]["rdma_pf_name"] == "ens800f0np0"


def test_validation_pods_preserve_non_host_non_privileged_boundary():
    s = load_settings()
    docs = LiveProvider(s)._validation_pods()
    assert len(docs) == 2
    for pod in docs:
        spec = pod["spec"]
        container = spec["containers"][0]
        security = container["securityContext"]
        assert spec["hostNetwork"] is False
        assert spec["hostPID"] is False
        assert spec["hostIPC"] is False
        assert spec["automountServiceAccountToken"] is False
        assert security["privileged"] is False
        assert security["allowPrivilegeEscalation"] is False
        assert security["readOnlyRootFilesystem"] is True
        assert security["capabilities"]["drop"] == ["ALL"]
        assert set(security["capabilities"]["add"]) == {"IPC_LOCK", "NET_RAW"}
        assert container["resources"]["requests"][s.rdma_resource_full] == "1"


def test_vf_readiness_requires_operator_success_and_expected_capacity():
    class FakeLiveProvider(LiveProvider):
        def kubectl(self, args, **kwargs):
            if args[:4] == ["get", "nodes", "-l", "oci-rdma=true"]:
                data = {
                    "items": [
                        {"metadata": {"name": "node-a"}, "status": {"allocatable": {self.s.rdma_resource_full: "2"}}},
                        {"metadata": {"name": "node-b"}, "status": {"allocatable": {self.s.rdma_resource_full: "2"}}},
                    ]
                }
                return subprocess.CompletedProcess(args, 0, json.dumps(data), "")
            if "sriovnetworknodestates.sriovnetwork.openshift.io" in args:
                data = {
                    "items": [
                        {"metadata": {"name": "node-a"}, "status": {"syncStatus": "Succeeded"}},
                        {"metadata": {"name": "node-b"}, "status": {"syncStatus": "Succeeded"}},
                    ]
                }
                return subprocess.CompletedProcess(args, 0, json.dumps(data), "")
            raise AssertionError(args)

    readiness = FakeLiveProvider(load_settings())._vf_readiness()
    assert readiness["ready"] is True
    assert all(node["ready"] for node in readiness["nodes"])


def test_hardware_discovery_finds_common_mellanox_pf():
    class FakeDiscoveryProvider(LiveProvider):
        def _rdma_nodes(self):
            return [{"metadata": {"name": "node-a"}}, {"metadata": {"name": "node-b"}}]

        def _node_states(self, *, check=False):
            def state(name, pci):
                return {
                    "metadata": {"name": name},
                    "status": {
                        "syncStatus": "Succeeded",
                        "interfaces": [{
                            "name": "ens800f0np0",
                            "driver": "mlx5_core",
                            "vendor": "15b3",
                            "deviceID": "demo",
                            "pciAddress": pci,
                            "mtu": 4220,
                            "totalvfs": 8,
                            "linkType": "ETH",
                        }],
                    },
                }
            return [state("node-a", "0000:81:00.0"), state("node-b", "0000:81:00.0")]

    result = FakeDiscoveryProvider(load_settings()).rdma_discovery()
    assert result["recommended"]["name"] == "ens800f0np0"
    assert result["recommended"]["mtu"] == 4220
    assert result["recommended"]["likely_rdma"] is True


def test_configure_network_blocks_before_vfs_are_reconciled(monkeypatch):
    import pytest
    from app.provider import ProviderError

    p = LiveProvider(load_settings())
    monkeypatch.setattr(
        p,
        "_vf_readiness",
        lambda: {
            "ready": False,
            "resource": p.s.rdma_resource_full,
            "expected_vfs_per_node": p.s.rdma_vfs_per_node,
            "nodes": [],
        },
    )
    with pytest.raises(ProviderError, match="VF reconciliation is not complete"):
        p.configure_network()


def test_node_diagnostics_api_is_authenticated_and_available_in_demo():
    client = TestClient(app)
    unauthorized = client.get("/api/v1/nodes")
    assert unauthorized.status_code == 401
    response = client.get("/api/v1/nodes", headers={"Authorization": "Bearer demo"})
    assert response.status_code == 200
    body = response.json()
    assert body["overall"] == "pass"
    assert len(body["nodes"]) == 2
    assert body["nodes"][0]["plugins"][0]["status"] == "RUNNING"


def test_hardware_discovery_rejects_mtu_mismatch():
    from app.provider import LiveProvider, ProviderError
    import pytest

    class FakeProvider(LiveProvider):
        def _rdma_nodes(self):
            return [{"metadata": {"name": "node-a"}}, {"metadata": {"name": "node-b"}}]

        def _node_states(self, *, check=False):
            return [
                {"metadata": {"name": "node-a"}, "status": {"syncStatus": "Succeeded", "interfaces": [{"name": "ens800f0np0", "driver": "mlx5_core", "vendor": "15b3", "mtu": 4220, "totalvfs": 8}]}},
                {"metadata": {"name": "node-b"}, "status": {"syncStatus": "Succeeded", "interfaces": [{"name": "ens800f0np0", "driver": "mlx5_core", "vendor": "15b3", "mtu": 1500, "totalvfs": 8}]}},
            ]

    provider = FakeProvider(load_settings())
    result = provider.rdma_discovery()
    candidate = result["common_candidates"][0]
    assert candidate["eligible"] is False
    assert candidate["mtu_consistent"] is False
    assert result["recommended"] is None
    with pytest.raises(ProviderError, match="not safe for VF configuration"):
        provider.validate_rdma_selection({"rdma_pf_name": "ens800f0np0", "rdma_mtu": 4220, "rdma_vfs_per_node": 2})


def test_addon_lifecycle_field_parsing_uses_oci_wire_names():
    from app.provider import LiveProvider
    assert LiveProvider._addon_state({"lifecycle-state": "ACTIVE"}) == "ACTIVE"
    assert LiveProvider._addon_version({"current-installed-version": "v25.10.0-1"}) == "v25.10.0-1"


def test_hardware_discovery_does_not_recommend_vcn_pf_when_rdma_pf_is_unhealthy():
    class FakeProvider(LiveProvider):
        def _rdma_nodes(self):
            return [{"metadata": {"name": "node-a"}}, {"metadata": {"name": "node-b"}}]

        def _node_states(self, *, check=False):
            return [
                {
                    "metadata": {"name": "node-a"},
                    "status": {
                        "syncStatus": "Succeeded",
                        "interfaces": [
                            {"name": "ens300f0np0", "driver": "mlx5_core", "vendor": "15b3", "mtu": 9000, "totalvfs": 54},
                            {"name": "ens800f0np0", "driver": "mlx5_core", "vendor": "15b3", "mtu": 4220, "totalvfs": 127},
                            {"name": "ens800f1np1", "driver": "mlx5_core", "vendor": "15b3", "mtu": 1500, "totalvfs": 127},
                        ],
                    },
                },
                {
                    "metadata": {"name": "node-b"},
                    "status": {
                        "syncStatus": "Succeeded",
                        "interfaces": [
                            {"name": "ens300f0np0", "driver": "mlx5_core", "vendor": "15b3", "mtu": 9000, "totalvfs": 54},
                            {"name": "ens800f0np0", "driver": "mlx5_core", "vendor": "15b3", "mtu": 1500, "totalvfs": 127},
                            {"name": "ens800f1np1", "driver": "mlx5_core", "vendor": "15b3", "mtu": 1500, "totalvfs": 127},
                        ],
                    },
                },
            ]

    result = FakeProvider(load_settings()).rdma_discovery()
    assert result["recommended"] is None
    by_name = {item["name"]: item for item in result["common_candidates"]}
    assert by_name["ens300f0np0"]["eligible"] is False
    assert any("VCN/control-plane PF" in reason for reason in by_name["ens300f0np0"]["blockers"])
    assert by_name["ens800f0np0"]["eligible"] is False
    assert by_name["ens800f1np1"]["eligible"] is False


def test_hardware_discovery_prefers_healthy_high_capacity_4220_pf():
    class FakeProvider(LiveProvider):
        def _rdma_nodes(self):
            return [{"metadata": {"name": "node-a"}}, {"metadata": {"name": "node-b"}}]

        def _node_states(self, *, check=False):
            interfaces = [
                {"name": "ens300f0np0", "driver": "mlx5_core", "vendor": "15b3", "mtu": 9000, "totalvfs": 54},
                {"name": "ens800f0np0", "driver": "mlx5_core", "vendor": "15b3", "mtu": 4220, "totalvfs": 127},
                {"name": "ens800f1np1", "driver": "mlx5_core", "vendor": "15b3", "mtu": 1500, "totalvfs": 127},
            ]
            return [
                {"metadata": {"name": "node-a"}, "status": {"syncStatus": "Succeeded", "interfaces": interfaces}},
                {"metadata": {"name": "node-b"}, "status": {"syncStatus": "Succeeded", "interfaces": interfaces}},
            ]

    result = FakeProvider(load_settings()).rdma_discovery()
    assert result["recommended"]["name"] == "ens800f0np0"
    assert result["recommended"]["mtu"] == 4220


def test_configure_vfs_blocks_when_node_diagnostics_are_blocking(monkeypatch):
    import pytest
    from app.provider import ProviderError

    provider = LiveProvider(load_settings())
    monkeypatch.setattr(provider, "node_diagnostics", lambda: {
        "overall": "block",
        "summary": {"discovery_blockers": ["MTU mismatch"]},
    })
    with pytest.raises(ProviderError, match="managed RDMA nodes are unhealthy"):
        provider.configure_vfs()
