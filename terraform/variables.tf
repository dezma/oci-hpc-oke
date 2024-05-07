variable "home_region" { type = string }
variable "region" { type = string }
variable "tenancy_id" { type = string }
variable "compartment_id" { type = string }
variable "ssh_public_key" { type = string }
variable "ssh_private_key_path" { type = string }

variable hpc_image { default = "" }
variable hpc_shape { default = "BM.Optimized3.36" }
variable kubernetes_version { default = "v1.29.1" }
variable cluster_type { default = "enhanced" }
variable cluster_name { default = "oke-rdma-cluster" }
variable cni_type {default = "flannel"}
