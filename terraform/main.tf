module "oke" {
  source  = "oracle-terraform-modules/oke/oci"
  version = "5.1.5"

  # Provider
  providers           = { oci.home = oci.home }
  home_region         = var.home_region
  region              = var.region
  tenancy_id          = var.tenancy_id
  compartment_id      = var.compartment_id
  ssh_public_key_path = var.ssh_public_key_path
  ssh_private_key_path = var.ssh_private_key_path
  
  kubernetes_version = var.kubernetes_version
  cluster_type = var.cluster_type
  
  
  allow_worker_ssh_access     = true
  control_plane_allowed_cidrs = ["0.0.0.0/0"]

  control_plane_is_public = true 
  
 
  vcn_name      = "hpc"
  
  #subnets
  subnets = {
    bastion  = { newbits = 13, netnum = 0, dns_label = "bastion" }
    operator = { newbits = 13, netnum = 1, dns_label = "operator" }
    cp       = { newbits = 13, netnum = 2, dns_label = "cp" }
    workers  = { newbits = 2, netnum = 1, dns_label = "workers" }
  }

  assign_dns           = true
  
  
  # bastion host
  create_bastion        = true
  bastion_allowed_cidrs = ["0.0.0.0/0"]
  bastion_upgrade       = false
  
  
  #operator host
  create_operator            = true
  operator_upgrade           = false
  create_iam_resources       = true
  create_iam_operator_policy = "always"
  operator_install_k9s       = true
  
  
  create_cluster       = true 
  use_defined_tags     = false


  #node pools
  worker_pools = {

   hpc = {
     description = "HPC pool", enabled = true,
     disable_default_cloud_init=true,
     mode        = "cluster-network",
     size = 2,
     shape = var.hpc_shape
     boot_volume_size = 250,
     placement_ads = [1],
     image_type = "custom",
     image_id = var.hpc_image,
     cloud_init = [{ content = "./cloud-init/ol8.sh" }],
     agent_config = {
        are_all_plugins_disabled = false,
        is_management_disabled   = false,
        is_monitoring_disabled   = false,
        plugins_config = {
          "Compute HPC RDMA Authentication"     = "ENABLED",
          "Compute HPC RDMA Auto-Configuration" = "ENABLED",
          "Compute Instance Monitoring"         = "ENABLED",
          "Compute Instance Run Command"        = "ENABLED",
          "Custom Logs Monitoring"              = "ENABLED",
          "Management Agent"                    = "ENABLED",
          "Oracle Autonomous Linux"             = "DISABLED",
          "OS Management Service Agent"         = "DISABLED",
        }
      }
    }
  }
}