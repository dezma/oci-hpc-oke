data "oci_containerengine_cluster_option" "all" {
  cluster_option_id              = var.oke_cluster_option_id
  compartment_id                 = var.compartment_ocid
  should_list_all_patch_versions = true
}

data "oci_containerengine_addon_options" "available" {
  kubernetes_version        = var.kubernetes_version
  should_show_all_versions = false
}

# Query version-bearing add-ons individually as well as through the catalog above.
# Some OKE/provider responses populate version metadata more reliably when an
# explicit addon_name filter is supplied. The unfiltered catalog remains useful
# for name discovery, while these filtered queries are authoritative for version
# resolution.
data "oci_containerengine_addon_options" "cert_manager" {
  count = var.enable_nvidia_network_operator ? 1 : 0

  kubernetes_version        = var.kubernetes_version
  addon_name                = local.cert_manager_addon_name
  should_show_all_versions = false
}

data "oci_containerengine_addon_options" "network_operator" {
  count = var.enable_nvidia_network_operator ? 1 : 0

  kubernetes_version        = var.kubernetes_version
  addon_name                = local.network_operator_addon_name
  should_show_all_versions = false
}

data "oci_core_shapes" "rdma_candidate" {
  compartment_id      = var.compartment_ocid
  availability_domain = var.availability_domain
  image_id             = var.hpc_custom_image_ocid
  shape                = var.node_shape
}

data "oci_objectstorage_namespace" "this" {
  compartment_id = var.compartment_ocid
}

data "oci_core_images" "operator" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Oracle Linux"
  operating_system_version = "9"
  shape                    = var.operator_shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"

  filter {
    name   = "state"
    values = ["AVAILABLE"]
  }
}

locals {
  tags = merge(var.freeform_tags, {
    environment = var.name_prefix
  })

  supported_kubernetes_versions = data.oci_containerengine_cluster_option.all.kubernetes_versions

  kubernetes_version_without_v = trimprefix(var.kubernetes_version, "v")
  kubernetes_version_parts     = split(".", local.kubernetes_version_without_v)
  kubernetes_minor             = join(".", slice(local.kubernetes_version_parts, 0, 2))

  # Oracle's published Ubuntu node-package compatibility matrix. Keep this map explicit
  # rather than assuming the package patch always equals the selected OKE patch.
  ubuntu_oke_node_packages = {
    "1.27" = "oci-oke-node-all-1.27.10"
    "1.28" = "oci-oke-node-all-1.28.10"
    "1.29" = "oci-oke-node-all-1.29.1"
    "1.30" = "oci-oke-node-all-1.30.10"
    "1.31" = "oci-oke-node-all-1.31.10"
    "1.32" = "oci-oke-node-all-1.32.10"
    "1.33" = "oci-oke-node-all-1.33.10"
    "1.34" = "oci-oke-node-all-1.34.10"
    "1.35" = "oci-oke-node-all-1.35.2"
    "1.36" = "oci-oke-node-all-1.36.4"
  }
  oke_node_package = lookup(local.ubuntu_oke_node_packages, local.kubernetes_minor, "")

  nfd_candidates = [
    for addon in data.oci_containerengine_addon_options.available.addon_options : addon.name
    if can(regex("(?i)node.*feature.*discovery", "${addon.name} ${addon.description}"))
  ]

  cert_manager_candidates = [
    for addon in data.oci_containerengine_addon_options.available.addon_options : addon.name
    if can(regex("(?i)cert.*manager", "${addon.name} ${addon.description}"))
  ]

  network_operator_candidates = [
    for addon in data.oci_containerengine_addon_options.available.addon_options : addon.name
    if can(regex("(?i)nvidia.*network.*operator", "${addon.name} ${addon.description}"))
  ]

  nfd_addon_name              = var.nfd_addon_name_override != "" ? var.nfd_addon_name_override : try(local.nfd_candidates[0], "")
  cert_manager_addon_name     = try(local.cert_manager_candidates[0], "CertManager")
  network_operator_addon_name = var.nvidia_network_operator_addon_name_override != "" ? var.nvidia_network_operator_addon_name_override : try(local.network_operator_candidates[0], "")

  # The Network Operator and SR-IOV admission webhooks use generated TLS
  # certificates. Keep Certificate Manager as an explicit managed dependency.
  # OKE documentation commonly shows versions without a leading `v`, while the
  # add-on API can return the exact installable spelling with `v`. Resolve using
  # a prefix-free comparison key, but always pass the exact API-returned value
  # into oci_containerengine_addon.
  cert_manager_live_versions = var.enable_nvidia_network_operator ? distinct(flatten([
    for addon in try(data.oci_containerengine_addon_options.cert_manager[0].addon_options, []) : [
      for addon_version in addon.versions : trimspace(addon_version.version_number)
    ]
  ])) : []

  cert_manager_supported_version_groups = {
    for version in local.cert_manager_live_versions :
    trimprefix(trimprefix(trimspace(version), "v"), "V") => trimspace(version)...
  }
  cert_manager_supported_versions = sort(keys(local.cert_manager_supported_version_groups))
  cert_manager_preferred_version  = "1.17.4"
  cert_manager_resolved_version   = try(local.cert_manager_supported_version_groups[local.cert_manager_preferred_version][0], "")

  # NvidiaNetworkOperator requires an explicit add-on version. Resolve the
  # selected friendly value against a dedicated live OKE query. This accepts
  # either `25.10.0-1` or `v25.10.0-1` as input while preserving the exact
  # installable spelling returned by OKE.
  network_operator_live_versions = var.enable_nvidia_network_operator ? distinct(flatten([
    for addon in try(data.oci_containerengine_addon_options.network_operator[0].addon_options, []) : [
      for addon_version in addon.versions : trimspace(addon_version.version_number)
    ]
  ])) : []

  network_operator_supported_version_groups = {
    for version in local.network_operator_live_versions :
    trimprefix(trimprefix(trimspace(version), "v"), "V") => trimspace(version)...
  }
  network_operator_supported_versions = sort(keys(local.network_operator_supported_version_groups))
  network_operator_requested_version  = trimprefix(trimprefix(trimspace(var.nvidia_network_operator_version), "v"), "V")
  network_operator_resolved_version   = try(local.network_operator_supported_version_groups[local.network_operator_requested_version][0], "")

  operator_image_id = var.operator_image_ocid != "" ? var.operator_image_ocid : try(data.oci_core_images.operator.images[0].id, "")

  ubuntu_repo_url = "https://objectstorage.us-sanjose-1.oraclecloud.com/n/odx-oke/b/okn-repositories/o/prod/${var.ubuntu_release}/kubernetes-${local.kubernetes_minor} stable main"

  managed_node_cloud_init = templatefile("${path.module}/operator/managed-ubuntu-hpc.yaml.tftpl", {
    oke_repo_url     = local.ubuntu_repo_url
    oke_node_package = local.oke_node_package
  })

  operator_payload_path   = "${path.module}/operator/payload/oke-rdma-control.tar.gz"
  operator_payload_sha256 = filesha256(local.operator_payload_path)
  operator_payload_name   = "releases/oke-rdma-control-${local.operator_payload_sha256}.tar.gz"

  operator_cluster_verb = var.operator_kubernetes_access_mode == "iam_admin" ? "manage" : "use"
}

resource "terraform_data" "preflight" {
  input = {
    kubernetes_version = var.kubernetes_version
    kubernetes_minor   = local.kubernetes_minor
    oke_node_package   = local.oke_node_package
    nfd_addon          = local.nfd_addon_name
    cert_manager_addon = local.cert_manager_addon_name
    cert_manager_version            = local.cert_manager_resolved_version
    cert_manager_supported_versions = local.cert_manager_supported_versions
    network_operator   = local.network_operator_addon_name
    network_operator_versions         = local.network_operator_supported_versions
    network_operator_resolved_version = local.network_operator_resolved_version
    operator_image     = local.operator_image_id
  }

  lifecycle {
    precondition {
      condition     = contains(local.supported_kubernetes_versions, var.kubernetes_version)
      error_message = "The selected full Kubernetes patch version is not in the live OKE option set for this tenancy/region."
    }

    precondition {
      condition     = local.oke_node_package != ""
      error_message = "No Ubuntu OKE node package is mapped for Kubernetes ${local.kubernetes_minor}. Review Oracle's Ubuntu Node Package Compatibility matrix and update the quickstart compatibility map before deploying."
    }

    precondition {
      condition     = local.operator_image_id != ""
      error_message = "No compatible Oracle Linux 9 operator image was found. Supply operator_image_ocid explicitly."
    }

    precondition {
      condition     = length(data.oci_core_shapes.rdma_candidate.shapes) == 1
      error_message = "The selected CPU RDMA shape is not available in the chosen AD with the supplied custom image. Verify shape/image/AD compatibility and the custom image OCID."
    }

    precondition {
      condition     = length(data.oci_core_shapes.rdma_candidate.shapes) == 1 ? try(data.oci_core_shapes.rdma_candidate.shapes[0].rdma_ports, 0) > 0 : false
      error_message = "The selected node shape does not expose RDMA ports according to the live OCI shape catalog."
    }

    precondition {
      condition     = length(data.oci_core_shapes.rdma_candidate.shapes) == 1 ? try(data.oci_core_shapes.rdma_candidate.shapes[0].gpus, 0) == 0 : false
      error_message = "This quickstart is intentionally CPU-RDMA focused; select an RDMA-capable shape without GPUs."
    }

    precondition {
      condition     = !var.enable_nvidia_network_operator || local.nfd_addon_name != ""
      error_message = "Node Feature Discovery add-on could not be auto-discovered. Set nfd_addon_name_override to the exact name returned by OKE add-on options."
    }

    precondition {
      condition     = !var.enable_nvidia_network_operator || local.cert_manager_addon_name != ""
      error_message = "Certificate Manager add-on could not be auto-discovered. The Network Operator admission webhooks require certificate management before installation."
    }

    precondition {
      condition     = !var.enable_nvidia_network_operator || local.cert_manager_resolved_version != ""
      error_message = "Certificate Manager ${local.cert_manager_preferred_version} is not in the supported version set for ${var.kubernetes_version} returned by the dedicated live OKE CertManager query. Supported versions returned by OKE (normalized): ${join(", ", local.cert_manager_supported_versions)}. Exact API values: ${join(", ", local.cert_manager_live_versions)}."
    }

    precondition {
      condition     = !var.enable_nvidia_network_operator || local.network_operator_addon_name != ""
      error_message = "NVIDIA Network Operator add-on could not be auto-discovered. Set nvidia_network_operator_addon_name_override to the exact name returned by OKE add-on options."
    }

    precondition {
      condition     = !var.enable_nvidia_network_operator || local.network_operator_resolved_version != ""
      error_message = "NVIDIA Network Operator version ${var.nvidia_network_operator_version} is not in the supported version set for ${var.kubernetes_version} returned by the dedicated live OKE NvidiaNetworkOperator query. Supported versions returned by OKE (normalized): ${join(", ", local.network_operator_supported_versions)}. Exact API values: ${join(", ", local.network_operator_live_versions)}."
    }

    precondition {
      condition     = !var.enable_worker_ssh_from_operator || trimspace(var.worker_ssh_public_key) != ""
      error_message = "worker_ssh_public_key is required when enable_worker_ssh_from_operator is true."
    }
  }
}
