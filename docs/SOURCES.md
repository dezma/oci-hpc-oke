# Sources reviewed

Reviewed for the October 2026 quickstart design:

- OKE managed nodes in OCI Compute Clusters  
  https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/contengusingcomputeclusters.htm
- NVIDIA Network Operator add-on configuration arguments  
  https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/configuration-arguments-nvidia-network-operator.htm
- OKE supported add-on versions  
  https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/contengconfiguringclusteraddons-supportedversions.htm
- OKE Ubuntu node package compatibility matrix  
  https://docs.oracle.com/en-us/iaas/Content/ContEng/Concepts/contengCompatibilitymatrix_topic.htm
- Running Ubuntu on OKE workers using custom images  
  https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/contengcreatingubuntubasedworkernodes.htm
- Supported OKE Kubernetes versions  
  https://docs.oracle.com/en-us/iaas/Content/ContEng/Concepts/contengaboutk8sversions.htm
- OKE access control and IAM  
  https://docs.oracle.com/en-us/iaas/Content/ContEng/Concepts/contengaboutaccesscontrol.htm
- OKE IAM policy reference  
  https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/contengpolicyreference.htm
- OCI Core IAM resource types, including Instance Agent  
  https://docs.oracle.com/en-us/iaas/Content/Identity/policyreference/corepolicyreference_topic-ResourceTypes.htm
- OCI Terraform node-pool resource (`compute_cluster_id`, `ssh_public_key`)  
  https://docs.oracle.com/en-us/iaas/tools/terraform-provider-oci/latest/docs/r/containerengine_node_pool.html
- Connecting to OCI Bastion sessions  
  https://docs.oracle.com/en-us/iaas/Content/Bastion/Tasks/connectingtosessions.htm
- OCI Cloud Agent HPC/RDMA plugin operations  
  https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/transitioning-to-hpc-plugin.htm
- SR-IOV Network Operator upstream node-state and policy model  
  https://github.com/k8snetworkplumbingwg/sriov-network-operator  
  https://github.com/k8snetworkplumbingwg/sriov-network-operator/blob/master/doc/quickstart.md

The Terraform compatibility map and pinned add-on choices are intentionally explicit and must be reviewed when Oracle changes supported Kubernetes/add-on versions.
