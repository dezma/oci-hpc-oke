from __future__ import annotations

from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_resource_manager_form_derives_ubuntu_bootstrap_values():
    schema = yaml.safe_load((ROOT / "terraform" / "schema.yaml").read_text())
    variables = schema["variables"]
    assert "kubernetes_minor" not in variables
    assert "oke_node_package" not in variables
    assert variables["ubuntu_release"]["type"] == "enum"
    assert set(variables["ubuntu_release"]["enum"]) == {"ubuntu-noble", "ubuntu-jammy"}


def test_custom_hpc_image_is_manual_ocid_field_not_platform_picker():
    schema = yaml.safe_load((ROOT / "terraform" / "schema.yaml").read_text())
    image = schema["variables"]["hpc_custom_image_ocid"]
    assert image["type"] == "string"
    assert "ocid1" in image["pattern"]


def test_rdma_operational_values_are_not_resource_manager_variables():
    schema = yaml.safe_load((ROOT / "terraform" / "schema.yaml").read_text())
    variables = schema["variables"]
    for name in (
        "rdma_pf_name",
        "rdma_mtu",
        "rdma_vfs_per_node",
        "rdma_resource_name",
        "rdma_ip_pool_cidr",
        "rdma_tools_image",
    ):
        assert name not in variables


def test_terraform_has_explicit_ubuntu_package_compatibility_map():
    text = (ROOT / "terraform" / "locals.tf").read_text()
    assert '"1.36" = "oci-oke-node-all-1.36.4"' in text
    assert "lookup(local.ubuntu_oke_node_packages" in text
    assert "local.kubernetes_minor" in text


def test_cloud_init_static_config_does_not_bake_rdma_pf_or_pool():
    text = (ROOT / "terraform" / "operator" / "cloud-init.sh.tftpl").read_text()
    assert '"rdma_pf_name"' not in text
    assert '"rdma_ip_pool_cidr"' not in text
    assert '"oke_node_package"' in text
    assert "HPC_CONTROL_RDMA_CONFIG" in text


def test_network_operator_has_managed_certificate_and_nfd_dependencies():
    text = (ROOT / "terraform" / "oke.tf").read_text()
    assert 'resource "oci_containerengine_addon" "cert_manager"' in text
    assert 'version                          = local.cert_manager_resolved_version' in text
    assert 'oci_containerengine_addon.cert_manager' in text
    assert 'key   = "skipNodeFeatureDiscoveryDependencyCheck"' in text
    assert 'value = "true"' in text



def test_addon_versions_use_dedicated_filtered_queries_and_prefix_normalization():
    text = (ROOT / "terraform" / "locals.tf").read_text()
    assert 'data "oci_containerengine_addon_options" "cert_manager"' in text
    assert 'addon_name                = local.cert_manager_addon_name' in text
    assert 'data "oci_containerengine_addon_options" "network_operator"' in text
    assert 'addon_name                = local.network_operator_addon_name' in text
    assert 'trimprefix(trimprefix(trimspace(version), "v"), "V")' in text
    assert 'cert_manager_resolved_version' in text
    assert 'network_operator_resolved_version' in text


def test_addon_resources_receive_exact_resolved_live_versions():
    text = (ROOT / "terraform" / "oke.tf").read_text()
    assert 'version                          = local.cert_manager_resolved_version' in text
    assert 'version                          = local.network_operator_resolved_version' in text


def test_cert_manager_compatibility_target():
    text = (ROOT / "terraform" / "locals.tf").read_text()
    assert 'cert_manager_preferred_version  = "1.17.4"' in text
    assert 'cert_manager_preferred_version  = "1.17.1"' not in text

def test_cloud_init_escapes_shell_parameter_expansion_for_templatefile():
    text = (ROOT / "terraform" / "operator" / "cloud-init.sh.tftpl").read_text()
    assert '$${PATH:-}' in text
    assert '${PATH:-}' not in text.replace('$${PATH:-}', '')


def test_operator_bootstrap_uses_valid_object_get_and_reports_failures():
    text = (ROOT / "terraform" / "operator" / "cloud-init.sh.tftpl").read_text()
    object_get_block = text.split('"$OCI_BOOTSTRAP_BIN" os object get', 1)[1].split("then", 1)[0]
    assert "--force" not in object_get_block
    assert 'rm -f "$PAYLOAD"' in text
    assert "IDENTITY_MAX_ATTEMPTS=120" in text
    assert "IDENTITY_RETRY_SECONDS=30" in text
    assert "trap on_exit EXIT" in text
    assert 'write_status "identity" "failed"' in text
    assert 'export PATH="/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin:' in text
    assert '"$OCI_BOOTSTRAP_BIN" --version' in text


def test_operator_bootstrap_configures_private_ui_firewall_and_shell_helpers():
    text = (ROOT / "terraform" / "operator" / "cloud-init.sh.tftpl").read_text()
    assert "bastion_private_endpoint_ip" in text
    assert "firewall-cmd --zone=public --permanent --add-rich-rule" in text
    assert "/etc/profile.d/oke-rdma-control.sh" in text
    assert "export KUBECONFIG=/etc/oke-rdma-control/kube/config" in text
    assert "/usr/local/bin/oke-rdma-doctor" in text
    assert "sudo cat /etc/oke-rdma-control/admin.token" in text


def test_optional_worker_ssh_is_explicit_and_disabled_by_default():
    variables = (ROOT / "terraform" / "variables.tf").read_text()
    oke = (ROOT / "terraform" / "oke.tf").read_text()
    network = (ROOT / "terraform" / "network.tf").read_text()
    schema = yaml.safe_load((ROOT / "terraform" / "schema.yaml").read_text())
    assert 'variable "enable_worker_ssh_from_operator"' in variables
    assert 'default     = false' in variables
    assert 'ssh_public_key = trimspace(var.worker_ssh_public_key)' in oke
    assert 'resource "oci_core_network_security_group_security_rule" "workers_ssh_from_operator"' in network
    assert schema["variables"]["enable_worker_ssh_from_operator"]["default"] is False


def test_operator_identity_can_query_compute_and_instance_agent_read_only():
    text = (ROOT / "terraform" / "iam.tf").read_text()
    assert "to read instances in compartment id" in text
    assert "to read instance-agent-family in compartment id" in text


def test_control_center_has_read_only_managed_node_diagnostics():
    main = (ROOT / "control" / "app" / "main.py").read_text()
    provider = (ROOT / "control" / "app" / "provider.py").read_text()
    web = (ROOT / "control" / "web" / "index.html").read_text()
    javascript = (ROOT / "control" / "web" / "app.js").read_text()
    assert '@app.get("/api/v1/nodes"' in main
    assert "def node_diagnostics" in provider
    assert "instance-agent" in provider
    assert "Break-glass host inspection command" in javascript
    assert "the web service never executes it" in javascript
    assert "Query managed RDMA nodes directly" in web


def test_rdma_discovery_blocks_inconsistent_or_standard_mtu_candidates():
    provider = (ROOT / "control" / "app" / "provider.py").read_text()
    assert '"mtu_consistent"' in provider
    assert 'not 4000 <= (mtu or 0) <= 5000' in provider
    assert 'highest_common_vf_capacity' in provider
    assert '"eligible": not blockers' in provider
    assert "validate_rdma_selection" in provider

