resource "oci_core_compute_cluster" "rdma" {
  availability_domain = var.availability_domain
  compartment_id      = var.compartment_ocid
  display_name        = "${var.name_prefix}-compute-cluster"
  freeform_tags       = local.tags
}

resource "oci_identity_policy" "nodepool_compute_cluster" {
  compartment_id = var.compartment_ocid
  name           = "${var.name_prefix}-nodepool-compute-cluster"
  description    = "Allow this OKE managed node pool resource principal to launch workers into its OCI Compute Cluster."
  freeform_tags  = local.tags

  statements = [
    "allow any-user to {COMPUTE_CLUSTER_LAUNCH_INSTANCE} in compartment id ${var.compartment_ocid} where all {request.principal.type = 'nodepool', target.resource.id = '${oci_core_compute_cluster.rdma.id}'}"
  ]
}

resource "oci_containerengine_cluster" "this" {
  depends_on         = [terraform_data.preflight]
  compartment_id    = var.compartment_ocid
  kubernetes_version = var.kubernetes_version
  name               = "${var.name_prefix}-oke"
  type               = "ENHANCED_CLUSTER"
  vcn_id             = oci_core_vcn.this.id
  freeform_tags      = local.tags

  cluster_pod_network_options {
    cni_type = "OCI_VCN_IP_NATIVE"
  }

  endpoint_config {
    is_public_ip_enabled = false
    subnet_id            = oci_core_subnet.private["api"].id
    nsg_ids = [
      oci_core_network_security_group.oke_internal.id,
      oci_core_network_security_group.api_operator.id,
    ]
  }

  options {
    service_lb_subnet_ids = [oci_core_subnet.private["services"].id]

    add_ons {
      is_kubernetes_dashboard_enabled = false
      is_tiller_enabled               = false
    }

    kubernetes_network_config {
      services_cidr = var.services_cidr
    }
  }
}

resource "oci_containerengine_node_pool" "rdma" {
  depends_on = [oci_identity_policy.nodepool_compute_cluster]

  cluster_id         = oci_containerengine_cluster.this.id
  compartment_id     = var.compartment_ocid
  kubernetes_version = var.kubernetes_version
  name               = "${var.name_prefix}-rdma"
  node_shape         = var.node_shape
  freeform_tags      = local.tags

  node_source_details {
    source_type             = "IMAGE"
    image_id                = var.hpc_custom_image_ocid
    boot_volume_size_in_gbs = var.node_boot_volume_gbs
  }

  node_metadata = {
    user_data = base64encode(local.managed_node_cloud_init)
  }

  # Optional break-glass access only. Existing nodes receive an updated key only
  # through the OKE node-pool cycling/replacement lifecycle.
  ssh_public_key = trimspace(var.worker_ssh_public_key) != "" ? trimspace(var.worker_ssh_public_key) : null

  node_config_details {
    size               = var.node_count
    compute_cluster_id = oci_core_compute_cluster.rdma.id
    nsg_ids            = [oci_core_network_security_group.oke_internal.id]

    placement_configs {
      availability_domain = var.availability_domain
      subnet_id            = oci_core_subnet.private["workers"].id
      # Do not set fault domains when a Compute Cluster is used.
    }

    node_pool_pod_network_option_details {
      cni_type          = "OCI_VCN_IP_NATIVE"
      max_pods_per_node = var.max_pods_per_node
      pod_subnet_ids    = [oci_core_subnet.private["pods"].id]
      pod_nsg_ids       = [oci_core_network_security_group.oke_internal.id]
    }
  }

  initial_node_labels {
    key   = "oci-rdma"
    value = "true"
  }

  node_pool_cycling_details {
    is_node_cycling_enabled = true
    maximum_surge           = "1"
    maximum_unavailable     = "0"
  }

  timeouts {
    create = "90m"
    update = "90m"
    delete = "90m"
  }
}

resource "oci_containerengine_addon" "nfd" {
  count = var.enable_nvidia_network_operator ? 1 : 0

  depends_on = [oci_containerengine_node_pool.rdma, terraform_data.preflight]

  addon_name                       = local.nfd_addon_name
  cluster_id                       = oci_containerengine_cluster.this.id
  remove_addon_resources_on_delete = true
  override_existing                = false
}

# Both the NVIDIA Network Operator admission controller and the SR-IOV
# Network Operator admission controller use generated webhook certificates.
# Install OKE Certificate Manager first so add-on installation does not race
# against a missing certificate issuer/CRD dependency.
resource "oci_containerengine_addon" "cert_manager" {
  count = var.enable_nvidia_network_operator ? 1 : 0

  depends_on = [oci_containerengine_node_pool.rdma, terraform_data.preflight]

  addon_name                       = local.cert_manager_addon_name
  cluster_id                       = oci_containerengine_cluster.this.id
  remove_addon_resources_on_delete = true
  override_existing                = false
  version                          = local.cert_manager_resolved_version
}

resource "oci_containerengine_addon" "nvidia_network_operator" {
  count = var.enable_nvidia_network_operator ? 1 : 0

  depends_on = [
    oci_containerengine_addon.nfd,
    oci_containerengine_addon.cert_manager,
  ]

  addon_name                       = local.network_operator_addon_name
  cluster_id                       = oci_containerengine_cluster.this.id
  remove_addon_resources_on_delete = true
  override_existing                = false
  # Use the exact spelling returned by OKE add-on options (currently prefixed
  # with `v`) rather than the user-facing normalized selector value.
  version                          = local.network_operator_resolved_version

  configurations {
    key   = "operator.admissionControllers.enabled"
    value = "true"
  }

  configurations {
    key   = "sriovNetworkOperator.enabled"
    value = "true"
  }

  configurations {
    key   = "sriov-network-operator.operator.resourcePrefix"
    value = "nvidia.com"
  }

  configurations {
    key   = "sriov-network-operator.operator.admissionControllers.enabled"
    value = "true"
  }

  configurations {
    key   = "sriov-network-operator.operator.sriovOperatorConfig.configDaemonNodeSelectors"
    value = jsonencode({
      "kubernetes.io/os" = "linux"
      "oci-rdma"         = "true"
    })
  }

  configurations {
    key   = "vfCreationMode"
    value = "sriovNetworkOperator"
  }

  # NFD is installed and awaited as a separate OKE-managed add-on above.
  # Tell Network Operator not to perform a redundant bundled/dependency check.
  configurations {
    key   = "skipNodeFeatureDiscoveryDependencyCheck"
    value = "true"
  }
}
