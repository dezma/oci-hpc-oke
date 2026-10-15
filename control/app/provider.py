from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path
import subprocess
import time
from typing import Any
import yaml

from .config import Settings


class ProviderError(RuntimeError):
    pass


class LiveProvider:
    """Curated live operations only. No endpoint accepts an arbitrary shell command."""

    def __init__(self, settings: Settings):
        self.s = settings

    def _run(
        self,
        argv: list[str],
        *,
        stdin: str | None = None,
        timeout: int = 90,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            argv,
            input=stdin,
            text=True,
            capture_output=True,
            timeout=timeout,
            env={
                **__import__("os").environ,
                "KUBECONFIG": self.s.kubeconfig,
                "OCI_CLI_AUTH": "instance_principal",
            },
        )
        if check and result.returncode:
            msg = result.stderr.strip() or result.stdout.strip() or f"command failed: {argv[0]}"
            raise ProviderError(msg[-4000:])
        return result

    def kubectl(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return self._run(["kubectl", "--kubeconfig", self.s.kubeconfig, *args], **kwargs)

    def oci(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return self._run(
            ["oci", "--auth", "instance_principal", "--region", self.s.region, *args],
            **kwargs,
        )

    @staticmethod
    def _resource_count(value: Any) -> int:
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return 0

    def _rdma_nodes(self) -> list[dict[str, Any]]:
        result = self.kubectl(["get", "nodes", "-l", "oci-rdma=true", "-o", "json"])
        return json.loads(result.stdout).get("items", [])

    def _node_states(self, *, check: bool = False) -> list[dict[str, Any]]:
        result = self.kubectl(
            [
                "-n",
                self.s.sriov_operator_namespace,
                "get",
                "sriovnetworknodestates.sriovnetwork.openshift.io",
                "-o",
                "json",
            ],
            check=check,
        )
        if result.returncode:
            return []
        try:
            return json.loads(result.stdout).get("items", [])
        except json.JSONDecodeError:
            return []

    @staticmethod
    def _node_internal_ip(node: dict[str, Any]) -> str:
        for address in node.get("status", {}).get("addresses", []) or []:
            if address.get("type") == "InternalIP":
                return str(address.get("address", ""))
        return ""

    @staticmethod
    def _node_instance_id(node: dict[str, Any]) -> str:
        candidates = [
            node.get("spec", {}).get("providerID", ""),
            node.get("metadata", {}).get("annotations", {}).get("oci.oraclecloud.com/instance-id", ""),
            node.get("metadata", {}).get("annotations", {}).get("oci.oraclecloud.com/node.info", ""),
        ]
        for candidate in candidates:
            match = re.search(r"ocid1\.instance\.[A-Za-z0-9._-]+", str(candidate))
            if match:
                return match.group(0)
        return ""

    @staticmethod
    def _normalized_interfaces(status: dict[str, Any]) -> list[dict[str, Any]]:
        interfaces: list[dict[str, Any]] = []
        for iface in status.get("interfaces", []) or []:
            total_vfs = LiveProvider._resource_count(iface.get("totalvfs", iface.get("totalVfs", 0)))
            if total_vfs <= 0:
                continue
            driver = str(iface.get("driver", ""))
            vendor = str(iface.get("vendor", ""))
            admin_state = str(iface.get("linkAdminState", ""))
            interfaces.append({
                "name": str(iface.get("name", "")),
                "mtu": LiveProvider._resource_count(iface.get("mtu", 0)),
                "num_vfs": LiveProvider._resource_count(iface.get("numVfs", iface.get("numvfs", 0))),
                "total_vfs": total_vfs,
                "driver": driver,
                "vendor": vendor,
                "device_id": iface.get("deviceID", iface.get("deviceId", "")),
                "pci_address": iface.get("pciAddress", ""),
                "link_type": iface.get("linkType", ""),
                "link_admin_state": admin_state,
                "link_speed": iface.get("linkSpeed", ""),
                "likely_rdma": driver.startswith("mlx5") or vendor.lower() == "15b3",
            })
        return interfaces

    @staticmethod
    def _addon_name(addon: dict[str, Any]) -> str:
        return str(addon.get("addon-name") or addon.get("addon_name") or addon.get("name") or "")

    @staticmethod
    def _addon_state(addon: dict[str, Any]) -> str:
        return str(
            addon.get("lifecycle-state")
            or addon.get("lifecycle_state")
            or addon.get("state")
            or "UNKNOWN"
        )

    @staticmethod
    def _addon_version(addon: dict[str, Any]) -> str:
        return str(
            addon.get("current-installed-version")
            or addon.get("current_installed_version")
            or addon.get("version")
            or ""
        )

    def _node_pool_instance_map(self) -> dict[str, str]:
        """Return node name/private-IP -> instance OCID from the managed node pool.

        OKE node provider IDs are the preferred source, but older/custom images
        can expose different providerID/annotation formats. The node-pool API is
        a safe read-only fallback and avoids requiring SSH merely to correlate a
        Kubernetes Node with OCI Instance Agent plugin state.
        """
        if not self.s.node_pool_id:
            return {}
        result = self.oci(
            ["ce", "node-pool", "get", "--node-pool-id", self.s.node_pool_id, "--output", "json"],
            timeout=30,
            check=False,
        )
        if result.returncode:
            return {}
        try:
            nodes = json.loads(result.stdout).get("data", {}).get("nodes", []) or []
        except json.JSONDecodeError:
            return {}
        mapping: dict[str, str] = {}
        for item in nodes:
            instance_id = str(item.get("id", ""))
            if not instance_id:
                continue
            for key in (item.get("name"), item.get("private-ip"), item.get("private_ip")):
                if key:
                    mapping[str(key)] = instance_id
        return mapping

    def _instance_details(self, instance_id: str) -> dict[str, Any]:
        if not instance_id:
            return {"available": False, "error": "Kubernetes node has no OCI instance OCID in providerID"}
        result = self.oci(
            ["compute", "instance", "get", "--instance-id", instance_id, "--output", "json"],
            timeout=30,
            check=False,
        )
        if result.returncode:
            return {
                "available": False,
                "error": (result.stderr or result.stdout).strip()[-1000:],
            }
        try:
            data = json.loads(result.stdout).get("data", {})
        except json.JSONDecodeError:
            return {"available": False, "error": "OCI Compute returned invalid JSON"}
        return {
            "available": True,
            "display_name": data.get("display-name", data.get("display_name", "")),
            "shape": data.get("shape", ""),
            "lifecycle_state": data.get("lifecycle-state", data.get("lifecycle_state", "")),
            "availability_domain": data.get("availability-domain", data.get("availability_domain", "")),
        }

    def _instance_agent_plugins(self, instance_id: str) -> dict[str, Any]:
        if not instance_id:
            return {"available": False, "items": [], "error": "Missing OCI instance OCID"}
        result = self.oci(
            [
                "instance-agent",
                "plugin",
                "list",
                "--compartment-id",
                self.s.compartment_id,
                "--instanceagent-id",
                instance_id,
                "--all",
                "--output",
                "json",
            ],
            timeout=30,
            check=False,
        )
        if result.returncode:
            return {
                "available": False,
                "items": [],
                "error": (result.stderr or result.stdout).strip()[-1000:],
            }
        try:
            raw = json.loads(result.stdout).get("data", [])
        except json.JSONDecodeError:
            return {"available": False, "items": [], "error": "OCI Instance Agent returned invalid JSON"}
        items = [{
            "name": item.get("name", ""),
            "status": item.get("status", "UNKNOWN"),
            "message": item.get("message") or "",
            "updated": item.get("time-last-updated-utc", item.get("time_last_updated_utc", "")),
        } for item in raw]
        return {"available": True, "items": items, "error": ""}

    def configuration_status(self) -> dict[str, Any]:
        policy = self.kubectl(
            [
                "-n",
                self.s.sriov_operator_namespace,
                "get",
                "sriovnetworknodepolicy.sriovnetwork.openshift.io",
                f"{self.s.environment_name}-rdma-vfs",
                "-o",
                "name",
            ],
            check=False,
        )
        network = self.kubectl(
            [
                "-n",
                self.s.sriov_operator_namespace,
                "get",
                "sriovnetwork.sriovnetwork.openshift.io",
                self.s.vf_network_name,
                "-o",
                "name",
            ],
            check=False,
        )
        return {
            "policy_exists": policy.returncode == 0,
            "network_exists": network.returncode == 0,
            "hardware_fields_locked": policy.returncode == 0,
            "network_fields_locked": network.returncode == 0,
        }

    def rdma_discovery(self) -> dict[str, Any]:
        """Discover and assess SR-IOV-capable PFs from live node state.

        Automatic recommendations are intentionally conservative for OCI RDMA:
        the PF must exist on every selected worker, be Mellanox/MLX5-backed, and
        report one consistent MTU of at least 4000. A mismatched 1500/4220 view
        is treated as a node-health blocker, not as a reason to select a different
        down/unused Mellanox port.
        """
        nodes = self._rdma_nodes()
        node_names = {
            str(name) for n in nodes
            if (name := n.get("metadata", {}).get("name"))
        }
        states = [
            item for item in self._node_states(check=False)
            if item.get("metadata", {}).get("name") in node_names
        ]

        by_node: list[dict[str, Any]] = []
        for state in states:
            status = state.get("status", {})
            by_node.append({
                "name": state.get("metadata", {}).get("name", "unknown"),
                "sync_status": status.get("syncStatus", "Unknown"),
                "interfaces": self._normalized_interfaces(status),
            })

        common: list[dict[str, Any]] = []
        if by_node and len(by_node) == len(node_names):
            common_names: set[str] | None = None
            for node in by_node:
                names = {i["name"] for i in node["interfaces"] if i["name"]}
                common_names = names if common_names is None else common_names & names
            # OCI BM nodes can expose multiple MLX5 PFs. The VCN PF can also be
            # SR-IOV-capable, so "mlx5" alone is not enough to identify the RDMA
            # fabric. Use conservative OCI-specific evidence: the fabric PFs in
            # the supported CPU-RDMA profiles use a consistent MTU around 4220
            # and have the highest common VF capability on the host. Anything
            # else remains visible but cannot be approved by the normal UI.
            raw_matches: dict[str, list[dict[str, Any]]] = {
                name: [next(i for i in node["interfaces"] if i["name"] == name) for node in by_node]
                for name in sorted(common_names or [])
            }
            highest_common_vf_capacity = max(
                (
                    min(m["total_vfs"] for m in matches)
                    for matches in raw_matches.values()
                    if all(m["likely_rdma"] for m in matches)
                ),
                default=0,
            )
            for name, matches in raw_matches.items():
                mtus = sorted({m["mtu"] for m in matches})
                admin_states = sorted({m["link_admin_state"].lower() for m in matches if m["link_admin_state"]})
                mtu_consistent = len(mtus) == 1
                mtu = matches[0]["mtu"] if mtu_consistent else None
                min_total_vfs = min(m["total_vfs"] for m in matches)
                blockers: list[str] = []
                if not all(m["likely_rdma"] for m in matches):
                    blockers.append("The interface is not consistently reported as Mellanox/MLX5-backed.")
                if min_total_vfs < highest_common_vf_capacity:
                    blockers.append(
                        f"The common VF capability ({min_total_vfs}) is below the host RDMA-class maximum "
                        f"({highest_common_vf_capacity}); this is likely a VCN/control-plane PF rather than the OCI RDMA fabric PF."
                    )
                if not mtu_consistent:
                    blockers.append(f"Workers report inconsistent MTUs: {', '.join(str(x) for x in mtus)}.")
                elif not 4000 <= (mtu or 0) <= 5000:
                    blockers.append(
                        f"The common MTU is {mtu}; the supported OCI CPU-RDMA profiles expect a fabric MTU in the 4000-5000 range "
                        "(normally 4220). Verify RDMA authentication/link state and do not select a 1500- or 9000-byte VCN PF."
                    )
                if any(state in {"down", "disabled"} for state in admin_states):
                    blockers.append(f"At least one worker reports a non-active link-admin state: {', '.join(admin_states)}.")
                common.append({
                    "name": name,
                    "mtu": mtu,
                    "mtus": mtus,
                    "mtu_consistent": mtu_consistent,
                    "min_total_vfs": min_total_vfs,
                    "highest_common_vf_capacity": highest_common_vf_capacity,
                    "drivers": sorted({m["driver"] for m in matches}),
                    "vendors": sorted({m["vendor"] for m in matches}),
                    "link_admin_states": admin_states,
                    "likely_rdma": all(m["likely_rdma"] for m in matches),
                    "all_nodes": True,
                    "eligible": not blockers,
                    "blockers": blockers,
                })
            common.sort(key=lambda x: (not x["eligible"], -(x["min_total_vfs"] or 0), x["name"]))

        recommended = next((c for c in common if c["eligible"]), None)
        blockers = []
        if len(by_node) != len(node_names):
            blockers.append(
                f"SriovNetworkNodeState is available for {len(by_node)}/{len(node_names)} selected RDMA workers."
            )
        if not recommended:
            blockers.append(
                "No common PF is currently safe for automatic VF configuration. Resolve node/link/MTU inconsistencies first."
            )
        return {
            "nodes_expected": len(nodes),
            "nodes_reporting_state": len(by_node),
            "nodes": by_node,
            "common_candidates": common,
            "recommended": recommended,
            "configured": self.s.rdma_config(),
            "ready_for_vf_configuration": bool(recommended) and not blockers,
            "blockers": blockers,
            "note": (
                "Read-only discovery from SriovNetworkNodeState. The quickstart refuses to recommend "
                "a PF when workers disagree on MTU, when the MTU looks like a VCN interface (1500/9000), "
                "or when the PF has lower VF capacity than the host's RDMA-class interfaces."
            ),
        }

    def validate_rdma_selection(self, values: dict[str, Any]) -> dict[str, Any]:
        discovery = self.rdma_discovery()
        name = str(values.get("rdma_pf_name", ""))
        selected = next((item for item in discovery.get("common_candidates", []) if item["name"] == name), None)
        if not selected:
            raise ProviderError(
                f"PF {name!r} is not reported as a common SR-IOV-capable interface on every selected RDMA worker."
            )
        if not selected.get("eligible"):
            raise ProviderError(
                f"PF {name!r} is not safe for VF configuration: " + " ".join(selected.get("blockers", []))
            )
        requested_mtu = self._resource_count(values.get("rdma_mtu"))
        if requested_mtu != selected.get("mtu"):
            raise ProviderError(
                f"Requested MTU {requested_mtu} does not match the consistent live MTU {selected.get('mtu')} for {name}."
            )
        requested_vfs = self._resource_count(values.get("rdma_vfs_per_node"))
        if requested_vfs > self._resource_count(selected.get("min_total_vfs")):
            raise ProviderError(
                f"Requested VF count {requested_vfs} exceeds the live minimum total VF capability "
                f"{selected.get('min_total_vfs')} for {name}."
            )
        return selected

    def node_diagnostics(self) -> dict[str, Any]:
        """Query managed RDMA nodes through Kubernetes and OCI read-only APIs.

        This deliberately avoids SSH and arbitrary host commands. It combines
        Kubernetes readiness, SriovNetworkNodeState inventory, OCI instance
        lifecycle data, and Oracle Cloud Agent plugin runtime state.
        """
        nodes = self._rdma_nodes()
        node_pool_instances = self._node_pool_instance_map()
        state_map = {
            item.get("metadata", {}).get("name"): item.get("status", {})
            for item in self._node_states(check=False)
            if item.get("metadata", {}).get("name")
        }
        required_plugins = (
            "Compute HPC RDMA Authentication",
            "Compute HPC RDMA Auto-Configuration",
        )
        details: list[dict[str, Any]] = []
        for node in nodes:
            name = node.get("metadata", {}).get("name", "unknown")
            ready = any(
                condition.get("type") == "Ready" and condition.get("status") == "True"
                for condition in node.get("status", {}).get("conditions", [])
            )
            internal_ip = self._node_internal_ip(node)
            instance_id = (
                self._node_instance_id(node)
                or node_pool_instances.get(name, "")
                or node_pool_instances.get(internal_ip, "")
            )
            plugins = self._instance_agent_plugins(instance_id)
            plugin_map = {item.get("name"): item for item in plugins.get("items", [])}
            required = [{
                "name": plugin_name,
                "status": plugin_map.get(plugin_name, {}).get("status", "UNKNOWN"),
                "message": plugin_map.get(plugin_name, {}).get("message", ""),
                "updated": plugin_map.get(plugin_name, {}).get("updated", ""),
            } for plugin_name in required_plugins]
            state = state_map.get(name, {})
            interfaces = self._normalized_interfaces(state)
            issues: list[dict[str, str]] = []
            if not ready:
                issues.append({"severity": "block", "message": "Kubernetes node is not Ready."})
            if not instance_id:
                issues.append({"severity": "warn", "message": "OCI instance OCID could not be extracted from the Kubernetes node."})
            if plugins.get("available"):
                for plugin in required:
                    if str(plugin["status"]).upper() != "RUNNING":
                        issues.append({
                            "severity": "block",
                            "message": f"{plugin['name']} is {plugin['status']} rather than RUNNING.",
                        })
            else:
                issues.append({
                    "severity": "block",
                    "message": (
                        "OCI Instance Agent plugin status is unavailable, so the required RDMA authentication/configuration "
                        "state cannot be proven: " + str(plugins.get("error", "unknown error"))
                    ),
                })
            sync_status = str(state.get("syncStatus", "Missing"))
            if sync_status != "Succeeded":
                issues.append({
                    "severity": "block",
                    "message": f"SriovNetworkNodeState syncStatus is {sync_status}, not Succeeded.",
                })

            likely_interfaces = [interface for interface in interfaces if interface.get("likely_rdma")]
            if not likely_interfaces:
                issues.append({"severity": "block", "message": "No Mellanox/MLX5 SR-IOV-capable interface is reported by SriovNetworkNodeState."})
            else:
                max_vfs = max(self._resource_count(interface.get("total_vfs")) for interface in likely_interfaces)
                rdma_class = [
                    interface for interface in likely_interfaces
                    if self._resource_count(interface.get("total_vfs")) == max_vfs
                ]
                healthy_fabric = [
                    interface for interface in rdma_class
                    if 4000 <= self._resource_count(interface.get("mtu")) <= 5000
                    and str(interface.get("link_admin_state", "")).lower() not in {"down", "disabled"}
                ]
                if not healthy_fabric:
                    summary = ", ".join(
                        f"{interface.get('name')} MTU {interface.get('mtu')}"
                        for interface in rdma_class
                    ) or "none"
                    issues.append({
                        "severity": "block",
                        "message": (
                            "No high-capacity MLX5 PF reports a healthy OCI RDMA fabric MTU on this node "
                            f"({summary}). Verify per-interface RDMA authentication/link state before creating VFs."
                        ),
                    })
            status = "pass"
            if any(issue["severity"] == "block" for issue in issues):
                status = "block"
            elif issues:
                status = "warn"
            node_info = node.get("status", {}).get("nodeInfo", {})
            details.append({
                "name": name,
                "status": status,
                "ready": ready,
                "internal_ip": internal_ip,
                "instance_id": instance_id,
                "instance": self._instance_details(instance_id),
                "os_image": node_info.get("osImage", ""),
                "kernel_version": node_info.get("kernelVersion", ""),
                "kubelet_version": node_info.get("kubeletVersion", ""),
                "sriov_sync_status": state.get("syncStatus", "Missing"),
                "vf_allocatable": self._resource_count(
                    node.get("status", {}).get("allocatable", {}).get(self.s.rdma_resource_full, "0")
                ),
                "plugins": required,
                "plugins_available": plugins.get("available", False),
                "interfaces": interfaces,
                "issues": issues,
                "break_glass_command": (
                    f"kubectl debug node/{name} -it --image=docker.io/library/ubuntu:24.04 "
                    "--profile=sysadmin -- chroot /host bash"
                ),
            })

        discovery = self.rdma_discovery()
        overall = "pass"
        if any(node["status"] == "block" for node in details) or not discovery.get("recommended"):
            overall = "block"
        elif any(node["status"] == "warn" for node in details):
            overall = "warn"
        return {
            "overall": overall,
            "queried_at": int(time.time()),
            "nodes": details,
            "summary": {
                "total": len(details),
                "ready": sum(1 for node in details if node["ready"]),
                "plugin_healthy": sum(
                    1 for node in details
                    if node["plugins_available"] and all(str(p["status"]).upper() == "RUNNING" for p in node["plugins"])
                ),
                "recommended_pf": discovery.get("recommended"),
                "discovery_blockers": discovery.get("blockers", []),
            },
            "note": (
                "Read-only diagnostics use Kubernetes and OCI Instance Agent APIs. "
                "The break-glass command is displayed but never executed by the web application."
            ),
        }

    def environment(self) -> dict[str, Any]:
        nodes = self._rdma_nodes()
        addons_raw = self.oci(
            ["ce", "cluster", "list-addons", "--cluster-id", self.s.cluster_id, "--all", "--output", "json"]
        ).stdout
        addons = json.loads(addons_raw).get("data", [])
        return {
            "mode": "live",
            "environment_name": self.s.environment_name,
            "region": self.s.region,
            "cluster_id": self.s.cluster_id,
            "cluster_name": self.s.cluster_name,
            "platform": {
                "kubernetes_version": self.s.kubernetes_version,
                "kubernetes_minor": self.s.kubernetes_minor,
                "ubuntu_release": self.s.ubuntu_release,
                "oke_node_package": self.s.oke_node_package,
                "oke_repo_url": self.s.oke_repo_url,
            },
            "node_count": len(nodes),
            "nodes": [
                {
                    "name": n["metadata"]["name"],
                    "ready": any(
                        c.get("type") == "Ready" and c.get("status") == "True"
                        for c in n.get("status", {}).get("conditions", [])
                    ),
                    "internal_ip": self._node_internal_ip(n),
                    "instance_id": self._node_instance_id(n),
                    "vf_allocatable": n.get("status", {}).get("allocatable", {}).get(
                        self.s.rdma_resource_full, "0"
                    ),
                }
                for n in nodes
            ],
            "addons": [
                {
                    "name": self._addon_name(addon),
                    "state": self._addon_state(addon),
                    "version": self._addon_version(addon),
                    "error": addon.get("addon-error") or addon.get("addon_error"),
                }
                for addon in addons
            ],
            "rdma": {
                "configured": self.s.rdma_configured,
                "pf": self.s.rdma_pf_name,
                "mtu": self.s.rdma_mtu,
                "vfs_per_node": self.s.rdma_vfs_per_node,
                "resource": self.s.rdma_resource_full,
                "resource_name": self.s.rdma_resource_name,
                "ip_pool": self.s.rdma_ip_pool_cidr,
                "tools_image": self.s.rdma_tools_image,
                "tools_image_configured": bool(self.s.rdma_tools_image),
            },
            "configuration_status": self.configuration_status(),
            "vf_reconciliation": self._vf_readiness(),
        }

    def preflight(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        env = self.environment()
        nodes = env["nodes"]
        checks.append({
            "name": "Two RDMA workers",
            "status": "pass" if len(nodes) >= 2 else "block",
            "detail": f"Found {len(nodes)} node(s) labelled oci-rdma=true.",
        })
        ready = sum(1 for n in nodes if n["ready"])
        checks.append({
            "name": "RDMA workers Ready",
            "status": "pass" if ready == len(nodes) and ready >= 2 else "block",
            "detail": f"{ready}/{len(nodes)} labelled nodes are Ready.",
        })

        api = self.kubectl(["api-resources", "-o", "name"], check=False).stdout.splitlines()
        required = {
            "sriovnetworknodepolicies.sriovnetwork.openshift.io": "SR-IOV Node Policy CRD",
            "sriovnetworknodestates.sriovnetwork.openshift.io": "SR-IOV Node State CRD",
            "sriovnetworks.sriovnetwork.openshift.io": "SR-IOV Network CRD",
            "ippools.nv-ipam.nvidia.com": "NVIDIA IPAM pool CRD",
        }
        for resource, label in required.items():
            checks.append({
                "name": label,
                "status": "pass" if resource in api else "block",
                "detail": resource,
            })

        addon_expectations = (
            ("Node Feature Discovery add-on", self.s.nfd_addon_name),
            ("Certificate Manager add-on", self.s.cert_manager_addon_name),
            ("NVIDIA Network Operator add-on", self.s.network_operator_addon_name),
        )
        for label, expected_name in addon_expectations:
            addon = next(
                (item for item in env["addons"] if str(item.get("name", "")).lower() == expected_name.lower()),
                None,
            )
            state = str((addon or {}).get("state", "UNKNOWN")).upper()
            checks.append({
                "name": label,
                "status": "pass" if addon and state in {"ACTIVE", "SUCCEEDED"} else "block",
                "detail": addon or {"expected_name": expected_name},
            })

        diagnostics = self.node_diagnostics()
        checks.append({
            "name": "OCI RDMA node and plugin health",
            "status": diagnostics["overall"],
            "detail": diagnostics["summary"],
        })

        discovery = self.rdma_discovery()
        checks.append({
            "name": "SR-IOV hardware discovery",
            "status": "pass" if discovery.get("recommended") else "block",
            "detail": {
                "common_candidates": len(discovery["common_candidates"]),
                "nodes_reporting_state": discovery["nodes_reporting_state"],
                "nodes_expected": discovery["nodes_expected"],
                "blockers": discovery.get("blockers", []),
            },
        })
        saved_status = "block"
        saved_detail: Any = "Select a healthy live PF/MTU in SR-IOV & VFs before applying a policy."
        if self.s.rdma_configured:
            try:
                selected = self.validate_rdma_selection(self.s.rdma_config())
                saved_status = "pass"
                saved_detail = {"config": self.s.rdma_config(), "live_candidate": selected}
            except ProviderError as exc:
                saved_detail = str(exc)
        checks.append({
            "name": "RDMA VF configuration saved and still valid",
            "status": saved_status,
            "detail": saved_detail,
        })

        vf_readiness = env.get("vf_reconciliation", self._vf_readiness())
        checks.append({
            "name": "SR-IOV VF reconciliation",
            "status": "pass" if vf_readiness.get("ready") else "warn",
            "detail": vf_readiness,
        })

        if self.s.rdma_tools_image:
            immutable = "@sha256:" in self.s.rdma_tools_image and len(
                self.s.rdma_tools_image.rsplit("@sha256:", 1)[-1]
            ) == 64
            checks.append({
                "name": "Immutable RDMA tools image",
                "status": "pass" if immutable else "block",
                "detail": self.s.rdma_tools_image,
            })
        else:
            checks.append({
                "name": "RDMA tools image",
                "status": "warn",
                "detail": "Not configured. VF setup can continue, but live bandwidth validation is disabled.",
            })

        return {"checks": checks, "blocking": sum(1 for c in checks if c["status"] == "block")}

    def _vf_readiness(self) -> dict[str, Any]:
        node_result = self.kubectl(["get", "nodes", "-l", "oci-rdma=true", "-o", "json"], check=False)
        if node_result.returncode:
            return {"ready": False, "reason": "Unable to read RDMA nodes", "nodes": []}
        try:
            nodes = json.loads(node_result.stdout).get("items", [])
        except json.JSONDecodeError:
            return {"ready": False, "reason": "Invalid node JSON returned by Kubernetes", "nodes": []}

        if not self.s.rdma_configured:
            return {
                "ready": False,
                "reason": "RDMA PF/MTU have not been selected in the Control Center",
                "expected_vfs_per_node": self.s.rdma_vfs_per_node,
                "resource": self.s.rdma_resource_full,
                "nodes": [n.get("metadata", {}).get("name", "unknown") for n in nodes],
            }

        state_items = self._node_states(check=False)
        if not state_items:
            return {
                "ready": False,
                "reason": "SriovNetworkNodeState resources are not readable yet",
                "expected_vfs_per_node": self.s.rdma_vfs_per_node,
                "nodes": [n.get("metadata", {}).get("name", "unknown") for n in nodes],
            }

        states = {
            item.get("metadata", {}).get("name"): item.get("status", {})
            for item in state_items
            if item.get("metadata", {}).get("name")
        }
        details: list[dict[str, Any]] = []
        for node in nodes:
            name = node.get("metadata", {}).get("name", "unknown")
            state = states.get(name, {})
            sync_status = state.get("syncStatus", "Missing")
            message = state.get("lastSyncError") or state.get("error") or state.get("message") or ""
            allocatable = self._resource_count(
                node.get("status", {}).get("allocatable", {}).get(self.s.rdma_resource_full, "0")
            )
            details.append({
                "name": name,
                "sync_status": sync_status,
                "vf_allocatable": allocatable,
                "expected_vfs": self.s.rdma_vfs_per_node,
                "ready": sync_status == "Succeeded" and allocatable >= self.s.rdma_vfs_per_node,
                "message": str(message)[:500],
            })

        return {
            "ready": len(details) >= 2 and all(item["ready"] for item in details),
            "expected_vfs_per_node": self.s.rdma_vfs_per_node,
            "resource": self.s.rdma_resource_full,
            "nodes": details,
        }

    def _require_vf_readiness(self) -> dict[str, Any]:
        readiness = self._vf_readiness()
        if not readiness.get("ready"):
            raise ProviderError(
                "SR-IOV VF reconciliation is not complete on every RDMA node. "
                "Wait until SriovNetworkNodeState syncStatus is Succeeded and the "
                f"configured {self.s.rdma_resource_full} capacity is allocatable. "
                + json.dumps(readiness)
            )
        return readiness

    def _wait_for_network_attachment(self, timeout: int = 90) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            result = self.kubectl(
                [
                    "-n",
                    self.s.workload_namespace,
                    "get",
                    "network-attachment-definitions.k8s.cni.cncf.io",
                    self.s.vf_network_name,
                    "-o",
                    "json",
                ],
                check=False,
            )
            if result.returncode == 0:
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    last_error = "network attachment returned invalid JSON"
            else:
                last_error = (result.stderr or result.stdout).strip()[-1000:]
            time.sleep(2)
        raise ProviderError(
            f"Timed out waiting for NetworkAttachmentDefinition {self.s.workload_namespace}/{self.s.vf_network_name}: {last_error}"
        )

    def _apply_documents(self, docs: list[dict[str, Any]], *, dry_run: bool = False) -> str:
        text = yaml.safe_dump_all(docs, sort_keys=False)
        args = ["apply", "-f", "-"]
        if dry_run:
            args.insert(1, "--dry-run=server")
        return self.kubectl(args, stdin=text, timeout=120).stdout

    def _pf_selector_key(self) -> str:
        """Accommodate SR-IOV operator API variants using pfName or pfNames."""
        result = self.kubectl(
            ["get", "crd", "sriovnetworknodepolicies.sriovnetwork.openshift.io", "-o", "json"],
            check=False,
        )
        if result.returncode:
            return "pfNames"
        try:
            crd = json.loads(result.stdout)
            versions = crd.get("spec", {}).get("versions", [])
            version = next((v for v in versions if v.get("served")), versions[0] if versions else {})
            props = (
                version.get("schema", {})
                .get("openAPIV3Schema", {})
                .get("properties", {})
                .get("spec", {})
                .get("properties", {})
                .get("nicSelector", {})
                .get("properties", {})
            )
            if "pfNames" in props:
                return "pfNames"
            if "pfName" in props:
                return "pfName"
        except (json.JSONDecodeError, IndexError):
            pass
        return "pfNames"

    def configure_vfs(self) -> dict[str, Any]:
        if not self.s.rdma_configured:
            raise ProviderError("Select and save the RDMA PF and MTU in the Control Center before configuring VFs")

        diagnostics = self.node_diagnostics()
        if diagnostics.get("overall") == "block":
            raise ProviderError(
                "VF configuration is blocked because one or more managed RDMA nodes are unhealthy. "
                "Open Managed nodes, resolve the reported Kubernetes/OCI plugin/interface issues, "
                "then query the nodes again before approving the policy. "
                + json.dumps(diagnostics.get("summary", {}))
            )

        selected = self.validate_rdma_selection(self.s.rdma_config())

        selector_key = self._pf_selector_key()
        policy = {
            "apiVersion": "sriovnetwork.openshift.io/v1",
            "kind": "SriovNetworkNodePolicy",
            "metadata": {
                "name": f"{self.s.environment_name}-rdma-vfs",
                "namespace": self.s.sriov_operator_namespace,
            },
            "spec": {
                "resourceName": self.s.rdma_resource_name,
                "nodeSelector": {"oci-rdma": "true"},
                "priority": 90,
                "mtu": self.s.rdma_mtu,
                "numVfs": self.s.rdma_vfs_per_node,
                "nicSelector": {selector_key: [self.s.rdma_pf_name]},
                "deviceType": "netdevice",
                "isRdma": True,
            },
        }
        dry = self._apply_documents([policy], dry_run=True)
        applied = self._apply_documents([policy], dry_run=False)
        return {
            "dry_run": dry.strip(),
            "apply": applied.strip(),
            "selected_interface": selected,
            "warning": "VF reconciliation can drain/reconfigure nodes. Wait for node states and allocatable VF resources before continuing.",
        }

    def configure_network(self) -> dict[str, Any]:
        readiness = self._require_vf_readiness()
        ipaddress.ip_network(self.s.rdma_ip_pool_cidr, strict=False)
        ns = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": self.s.workload_namespace,
                "labels": {"app.kubernetes.io/part-of": "oke-rdma-quickstart"},
            },
        }
        pool = {
            "apiVersion": "nv-ipam.nvidia.com/v1alpha1",
            "kind": "IPPool",
            "metadata": {"name": self.s.ip_pool_name, "namespace": self.s.sriov_operator_namespace},
            "spec": {"subnet": self.s.rdma_ip_pool_cidr, "perNodeBlockSize": 8},
        }
        network = {
            "apiVersion": "sriovnetwork.openshift.io/v1",
            "kind": "SriovNetwork",
            "metadata": {"name": self.s.vf_network_name, "namespace": self.s.sriov_operator_namespace},
            "spec": {
                "networkNamespace": self.s.workload_namespace,
                "resourceName": self.s.rdma_resource_name,
                "ipam": json.dumps({"type": "nv-ipam", "poolName": self.s.ip_pool_name}),
            },
        }
        dry = self._apply_documents([ns, pool, network], dry_run=True)
        applied = self._apply_documents([ns, pool, network])
        nad = self._wait_for_network_attachment()
        return {
            "dry_run": dry.strip(),
            "apply": applied.strip(),
            "vf_readiness": readiness,
            "network_attachment": {
                "namespace": nad.get("metadata", {}).get("namespace"),
                "name": nad.get("metadata", {}).get("name"),
            },
        }

    def _validation_pods(self) -> list[dict[str, Any]]:
        if not self.s.rdma_tools_image or "@sha256:" not in self.s.rdma_tools_image:
            raise ProviderError(
                "Configure the RDMA tools image in the Control Center as an immutable repository@sha256:digest reference"
            )
        docs: list[dict[str, Any]] = []
        for role in ("server", "client"):
            docs.append({
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {
                    "name": f"rdma-{role}",
                    "namespace": self.s.workload_namespace,
                    "labels": {"app": "oke-rdma-validation", "role": role},
                    "annotations": {
                        "k8s.v1.cni.cncf.io/networks": json.dumps([
                            {"name": self.s.vf_network_name, "interface": "net1"}
                        ])
                    },
                },
                "spec": {
                    "restartPolicy": "Never",
                    "hostNetwork": False,
                    "hostPID": False,
                    "hostIPC": False,
                    "automountServiceAccountToken": False,
                    "nodeSelector": {"oci-rdma": "true"},
                    "affinity": {
                        "podAntiAffinity": {
                            "requiredDuringSchedulingIgnoredDuringExecution": [{
                                "labelSelector": {"matchLabels": {"app": "oke-rdma-validation"}},
                                "topologyKey": "kubernetes.io/hostname",
                            }]
                        }
                    },
                    "securityContext": {"seccompProfile": {"type": "RuntimeDefault"}},
                    "containers": [{
                        "name": "rdma",
                        "image": self.s.rdma_tools_image,
                        "imagePullPolicy": "IfNotPresent",
                        "command": ["/bin/bash", "-c"],
                        "args": [
                            "set -euo pipefail; command -v ib_write_bw; command -v python3; ip -br addr; rdma link; exec sleep infinity"
                        ],
                        "securityContext": {
                            "privileged": False,
                            "allowPrivilegeEscalation": False,
                            "runAsUser": 0,
                            "readOnlyRootFilesystem": True,
                            "capabilities": {"drop": ["ALL"], "add": ["IPC_LOCK", "NET_RAW"]},
                        },
                        "resources": {
                            "requests": {"cpu": "1", "memory": "512Mi", self.s.rdma_resource_full: "1"},
                            "limits": {"memory": "2Gi", self.s.rdma_resource_full: "1"},
                        },
                        "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
                    }],
                    "volumes": [{"name": "tmp", "emptyDir": {}}],
                },
            })
        return docs

    def rdma_validation(self) -> dict[str, Any]:
        self._require_vf_readiness()
        self._wait_for_network_attachment(timeout=30)
        self.kubectl(
            [
                "-n",
                self.s.workload_namespace,
                "delete",
                "pod",
                "rdma-server",
                "rdma-client",
                "--ignore-not-found=true",
            ],
            check=False,
        )
        self._apply_documents(self._validation_pods(), dry_run=True)
        self._apply_documents(self._validation_pods())
        self.kubectl(
            [
                "-n",
                self.s.workload_namespace,
                "wait",
                "--for=condition=Ready",
                "pod/rdma-server",
                "pod/rdma-client",
                "--timeout=300s",
            ],
            timeout=320,
        )
        result = self._run(
            [
                "python3",
                str(Path(__file__).resolve().parents[1] / "validation" / "test_rdma.py"),
                "--namespace",
                self.s.workload_namespace,
            ],
            timeout=180,
            check=False,
        )
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            parsed = {
                "status": "failed",
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
            }
        if result.returncode:
            raise ProviderError(json.dumps(parsed))
        return parsed

    def cleanup_validation(self) -> dict[str, Any]:
        result = self.kubectl(
            [
                "-n",
                self.s.workload_namespace,
                "delete",
                "pod",
                "rdma-server",
                "rdma-client",
                "--ignore-not-found=true",
            ],
            check=False,
        )
        return {
            "output": (result.stdout + result.stderr).strip(),
            "note": "VF policy and SR-IOV network were intentionally left intact.",
        }


class DemoProvider:
    def __init__(self, settings: Settings):
        self.s = settings

    def configuration_status(self) -> dict[str, Any]:
        return {
            "policy_exists": False,
            "network_exists": False,
            "hardware_fields_locked": False,
            "network_fields_locked": False,
        }

    def rdma_discovery(self) -> dict[str, Any]:
        common = {
            "name": "ens800f0np0",
            "mtu": 4220,
            "mtus": [4220],
            "mtu_consistent": True,
            "min_total_vfs": 8,
            "drivers": ["mlx5_core"],
            "vendors": ["15b3"],
            "link_admin_states": ["up"],
            "likely_rdma": True,
            "all_nodes": True,
            "eligible": True,
            "blockers": [],
        }
        return {
            "nodes_expected": 2,
            "nodes_reporting_state": 2,
            "nodes": [
                {
                    "name": "rdma-node-a",
                    "sync_status": "Succeeded",
                    "interfaces": [{**common, "total_vfs": 8, "driver": "mlx5_core", "vendor": "15b3", "pci_address": "0000:81:00.0", "device_id": "demo", "link_type": "ETH", "link_admin_state": "up", "link_speed": "100000 Mb/s"}],
                },
                {
                    "name": "rdma-node-b",
                    "sync_status": "Succeeded",
                    "interfaces": [{**common, "total_vfs": 8, "driver": "mlx5_core", "vendor": "15b3", "pci_address": "0000:81:00.0", "device_id": "demo", "link_type": "ETH", "link_admin_state": "up", "link_speed": "100000 Mb/s"}],
                },
            ],
            "common_candidates": [common],
            "recommended": common,
            "configured": self.s.rdma_config(),
            "ready_for_vf_configuration": True,
            "blockers": [],
            "note": "Demo inventory only; no live hardware was queried.",
        }

    def validate_rdma_selection(self, values: dict[str, Any]) -> dict[str, Any]:
        candidate = self.rdma_discovery()["recommended"]
        if values.get("rdma_pf_name") != candidate["name"]:
            raise ProviderError("Demo PF selection is not available")
        if int(values.get("rdma_mtu", 0)) != candidate["mtu"]:
            raise ProviderError("Demo MTU does not match discovered MTU")
        if int(values.get("rdma_vfs_per_node", 0)) > candidate["min_total_vfs"]:
            raise ProviderError("Demo VF count exceeds capacity")
        return candidate

    def node_diagnostics(self) -> dict[str, Any]:
        plugins = [
            {"name": "Compute HPC RDMA Authentication", "status": "RUNNING", "message": "", "updated": "demo"},
            {"name": "Compute HPC RDMA Auto-Configuration", "status": "RUNNING", "message": "", "updated": "demo"},
        ]
        interface = {
            "name": "ens800f0np0", "mtu": 4220, "num_vfs": 0, "total_vfs": 8,
            "driver": "mlx5_core", "vendor": "15b3", "device_id": "demo",
            "pci_address": "0000:98:00.0", "link_type": "ETH", "link_admin_state": "up",
            "link_speed": "100000 Mb/s", "likely_rdma": True,
        }
        nodes = []
        for index, name in enumerate(("rdma-node-a", "rdma-node-b"), start=1):
            nodes.append({
                "name": name,
                "status": "pass",
                "ready": True,
                "internal_ip": f"10.70.1.{index}",
                "instance_id": f"ocid1.instance.demo{index}",
                "instance": {"available": True, "shape": "BM.Optimized3.36", "lifecycle_state": "RUNNING", "display_name": name, "availability_domain": "DEMO-AD-1"},
                "os_image": "Ubuntu 24.04",
                "kernel_version": "demo",
                "kubelet_version": "v1.36.4",
                "sriov_sync_status": "Succeeded",
                "vf_allocatable": self.s.rdma_vfs_per_node,
                "plugins": plugins,
                "plugins_available": True,
                "interfaces": [interface],
                "issues": [],
                "break_glass_command": f"kubectl debug node/{name} -it --image=docker.io/library/ubuntu:24.04 --profile=sysadmin -- chroot /host bash",
            })
        return {
            "overall": "pass",
            "queried_at": int(time.time()),
            "nodes": nodes,
            "summary": {"total": 2, "ready": 2, "plugin_healthy": 2, "recommended_pf": self.rdma_discovery()["recommended"], "discovery_blockers": []},
            "note": "Demo inventory only; no live nodes or OCI plugins were queried.",
        }

    def environment(self) -> dict[str, Any]:
        return {
            "mode": "demo",
            "environment_name": self.s.environment_name,
            "region": self.s.region,
            "cluster_id": self.s.cluster_id,
            "cluster_name": self.s.cluster_name,
            "platform": {
                "kubernetes_version": self.s.kubernetes_version,
                "kubernetes_minor": self.s.kubernetes_minor,
                "ubuntu_release": self.s.ubuntu_release,
                "oke_node_package": self.s.oke_node_package,
                "oke_repo_url": self.s.oke_repo_url,
            },
            "node_count": 2,
            "nodes": [
                {"name": "rdma-node-a", "ready": True, "vf_allocatable": "2"},
                {"name": "rdma-node-b", "ready": True, "vf_allocatable": "2"},
            ],
            "addons": [{
                "name": self.s.network_operator_addon_name,
                "state": "ACTIVE",
                "version": "demo",
            }],
            "rdma": {
                "configured": self.s.rdma_configured,
                "pf": self.s.rdma_pf_name,
                "mtu": self.s.rdma_mtu,
                "vfs_per_node": self.s.rdma_vfs_per_node,
                "resource": self.s.rdma_resource_full,
                "resource_name": self.s.rdma_resource_name,
                "ip_pool": self.s.rdma_ip_pool_cidr,
                "tools_image": self.s.rdma_tools_image,
                "tools_image_configured": bool(self.s.rdma_tools_image),
            },
            "configuration_status": self.configuration_status(),
            "vf_reconciliation": {
                "ready": self.s.rdma_configured,
                "expected_vfs_per_node": self.s.rdma_vfs_per_node,
                "resource": self.s.rdma_resource_full,
                "nodes": [
                    {"name": "rdma-node-a", "sync_status": "Succeeded", "vf_allocatable": self.s.rdma_vfs_per_node, "expected_vfs": self.s.rdma_vfs_per_node, "ready": self.s.rdma_configured, "message": "Demo only"},
                    {"name": "rdma-node-b", "sync_status": "Succeeded", "vf_allocatable": self.s.rdma_vfs_per_node, "expected_vfs": self.s.rdma_vfs_per_node, "ready": self.s.rdma_configured, "message": "Demo only"},
                ],
            },
        }

    def preflight(self) -> dict[str, Any]:
        return {
            "blocking": 0 if self.s.rdma_configured else 1,
            "checks": [
                {"name": "Two RDMA workers", "status": "pass", "detail": "Demo: 2 labelled nodes"},
                {"name": "NVIDIA Network Operator add-on", "status": "pass", "detail": "Demo only; not a live OCI measurement"},
                {"name": "SR-IOV hardware discovery", "status": "pass", "detail": "Demo: common Mellanox PF candidate detected"},
                {"name": "RDMA VF configuration saved", "status": "pass" if self.s.rdma_configured else "block", "detail": self.s.rdma_config()},
                {"name": "Immutable RDMA tools image", "status": "pass" if self.s.rdma_tools_image else "warn", "detail": self.s.rdma_tools_image or "Not configured"},
            ],
        }

    def configure_vfs(self) -> dict[str, Any]:
        time.sleep(0.4)
        return {"status": "simulated", "warning": "Demo only; no nodes were reconfigured."}

    def configure_network(self) -> dict[str, Any]:
        time.sleep(0.3)
        return {"status": "simulated"}

    def rdma_validation(self) -> dict[str, Any]:
        time.sleep(0.6)
        return {
            "status": "simulated",
            "cross_node": True,
            "bandwidth_gbit_s": None,
            "note": "Demo mode never fabricates a benchmark measurement.",
        }

    def cleanup_validation(self) -> dict[str, Any]:
        return {"status": "simulated"}


def get_provider(settings: Settings):
    return DemoProvider(settings) if settings.mode == "demo" else LiveProvider(settings)
