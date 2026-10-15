variable "tenancy_ocid" {
  description = "OCI tenancy OCID. Used for the operator dynamic group."
  type        = string
}

variable "compartment_ocid" {
  description = "Compartment in which the quickstart resources are created."
  type        = string
}

variable "region" {
  description = "OCI region, for example eu-frankfurt-1."
  type        = string
}

variable "availability_domain" {
  description = "Availability domain containing the Compute Cluster and RDMA managed node pool."
  type        = string
}

variable "name_prefix" {
  description = "Short prefix used for names and tags."
  type        = string
  default     = "oke-rdma"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,23}$", var.name_prefix))
    error_message = "name_prefix must start with a lowercase letter and contain 3-24 lowercase letters, digits, or hyphens."
  }
}

variable "oke_cluster_option_id" {
  description = "OKE cluster option ID used by Resource Manager to populate supported Kubernetes versions."
  type        = string
  default     = "all"
}

variable "kubernetes_version" {
  description = "Full OKE Kubernetes patch version, for example v1.36.4. The plan validates it against the live OKE option set."
  type        = string

  validation {
    condition     = can(regex("^v?[0-9]+\\.[0-9]+\\.[0-9]+$", var.kubernetes_version))
    error_message = "kubernetes_version must be a full patch version such as v1.36.4."
  }
}

variable "ubuntu_release" {
  description = "Ubuntu release used by the custom HPC image and Oracle OKE node-package repository."
  type        = string
  default     = "ubuntu-noble"

  validation {
    condition     = contains(["ubuntu-jammy", "ubuntu-noble"], var.ubuntu_release)
    error_message = "ubuntu_release must be ubuntu-jammy or ubuntu-noble."
  }
}

variable "hpc_custom_image_ocid" {
  description = "OCID of the approved Ubuntu HPC custom image used directly by the managed RDMA node pool. It must contain the compatible RDMA/OFED stack and Oracle Cloud Agent."
  type        = string

  validation {
    condition     = can(regex("^ocid1\\.image\\.", var.hpc_custom_image_ocid))
    error_message = "hpc_custom_image_ocid must be an OCI image OCID beginning with ocid1.image."
  }
}

variable "node_shape" {
  description = "RDMA and Compute Cluster capable bare-metal CPU shape."
  type        = string
  default     = "BM.Optimized3.36"
}

variable "node_count" {
  description = "Number of managed RDMA workers. Two is the minimum useful cross-node validation size."
  type        = number
  default     = 2

  validation {
    condition     = var.node_count >= 2 && var.node_count <= 64
    error_message = "node_count must be between 2 and 64."
  }
}

variable "node_boot_volume_gbs" {
  type    = number
  default = 100

  validation {
    condition     = var.node_boot_volume_gbs >= 50
    error_message = "node_boot_volume_gbs must be at least 50 GiB."
  }
}

variable "max_pods_per_node" {
  type    = number
  default = 31
}

variable "enable_nvidia_network_operator" {
  description = "Install the native OKE Node Feature Discovery and NVIDIA Network Operator add-ons."
  type        = bool
  default     = true
}

variable "nfd_addon_name_override" {
  description = "Optional exact OKE add-on name. Leave empty to auto-discover an add-on whose name/description matches Node Feature Discovery."
  type        = string
  default     = ""
}

variable "nvidia_network_operator_addon_name_override" {
  description = "Optional exact OKE add-on name. Leave empty to auto-discover the NVIDIA Network Operator for the selected Kubernetes version."
  type        = string
  default     = ""
}

variable "nvidia_network_operator_version" {
  description = "Explicit NVIDIA Network Operator add-on version. The Resource Manager UI uses the prefix-free form (for example 25.10.0-1); Terraform matches it to the exact live OKE add-on version spelling (for example v25.10.0-1) before installation."
  type        = string
  default     = "25.10.0-1"

  validation {
    condition     = trimspace(var.nvidia_network_operator_version) != ""
    error_message = "nvidia_network_operator_version must not be empty when the NVIDIA Network Operator is enabled."
  }
}

variable "bastion_client_cidr" {
  description = "Public workstation or corporate VPN CIDR allowed to create OCI Bastion sessions. Use a /32 for one workstation when practical."
  type        = string
}

variable "enable_worker_ssh_from_operator" {
  description = "Enable break-glass TCP/22 access from the private operator NSG to RDMA worker nodes. Normal Control Center operation does not depend on SSH."
  type        = bool
  default     = false
}

variable "worker_ssh_public_key" {
  description = "Optional SSH public key installed on newly launched RDMA workers. Required only when enable_worker_ssh_from_operator is true. Keep the private key on the administrator workstation and use agent forwarding through the operator."
  type        = string
  default     = ""

  validation {
    condition = (
      trimspace(var.worker_ssh_public_key) == "" ||
      can(regex("^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256) [A-Za-z0-9+/=]+( .*)?$", trimspace(var.worker_ssh_public_key)))
    )
    error_message = "worker_ssh_public_key must be empty or contain a valid OpenSSH public key."
  }
}

variable "operator_shape" {
  description = "Private operator VM shape."
  type        = string
  default     = "VM.Standard.E5.Flex"
}

variable "operator_shape_ocpus" {
  type    = number
  default = 1
}

variable "operator_shape_memory_gbs" {
  type    = number
  default = 8
}

variable "operator_boot_volume_gbs" {
  type    = number
  default = 60
}

variable "operator_image_ocid" {
  description = "Optional approved Oracle Linux operator image OCID. Empty selects the newest available Oracle Linux 9 image compatible with the operator shape."
  type        = string
  default     = ""
}

variable "operator_kubernetes_access_mode" {
  description = "iam_admin is the easiest single-operator path, scoped to this cluster. least_privilege_rbac keeps OCI IAM at use clusters and requires the generated Kubernetes ClusterRoleBinding to be applied once by a cluster administrator."
  type        = string
  default     = "iam_admin"

  validation {
    condition     = contains(["iam_admin", "least_privilege_rbac"], var.operator_kubernetes_access_mode)
    error_message = "operator_kubernetes_access_mode must be iam_admin or least_privilege_rbac."
  }
}

variable "operator_bootstrap_generation" {
  description = "Increment only when intentionally replacing the operator VM to pick up a new packaged control-center payload."
  type        = number
  default     = 1
}

variable "vcn_cidr" {
  type    = string
  default = "10.70.0.0/16"
}

variable "api_subnet_cidr" {
  type    = string
  default = "10.70.0.0/28"
}

variable "worker_subnet_cidr" {
  type    = string
  default = "10.70.1.0/24"
}

variable "pod_subnet_cidr" {
  type    = string
  default = "10.70.16.0/20"
}

variable "service_lb_subnet_cidr" {
  type    = string
  default = "10.70.32.0/24"
}

variable "operator_subnet_cidr" {
  type    = string
  default = "10.70.48.0/28"
}

variable "bastion_subnet_cidr" {
  type    = string
  default = "10.70.49.0/28"
}

variable "services_cidr" {
  type    = string
  default = "10.96.0.0/16"
}

variable "freeform_tags" {
  type = map(string)
  default = {
    project    = "oci-oke-rdma-quickstart"
    managed-by = "resource-manager"
  }
}
