# Deploying a HPC Cluster with RDMA Network on OCI OKE 

## Assumptions

1. The terraform script will be run on  OCI Cloud Shell.
2. The OKE clusters will use private control planes.


![OKE RDMA](Architecture/oci-hpc-arc.png)


## Create the OKE Clusters

1. Copy the terraform.tfvars.example to terraform.tfvars and provide the necessary values as detailed in steps 2-6.

2. Configure the provider parameters:

```
# provider

home_region = "eu-frankfurt-1"

region = "eu-frankfurt"

tenancy_id = "ocid1.tenancy.oc1.."

compartment_id = "ocid1.compartment.oc1.."
```

3. Configure an ssh key pair:

```
# ssh
ssh_private_key_path = "~/.ssh/id_rsa"
ssh_public_key_path  = "~/.ssh/id_rsa.pub"
```


5. Configure additional parameters if necessary:

```
kubernetes_version = "v1.28.2"

cluster_type = "basic"

oke_control_plane = "private"
```

6. Configure your node pools:

```
nodepools = {
  np1 = {
    shape            = "VM.Standard.E4.Flex",
    ocpus            = 2,
    memory           = 64,
    size             = 2,
    boot_volume_size = 150,
  }
}
```

7. Run terraform to create your clusters:

```
terraform apply --auto-approve
```

8. Once the Dynamic Routing Gateways (DRGs) and Remote Peering Connections (RPCs) have been created, use the OCI console to establish a connection between them.

## Mount OCI FSS as Persistent Volume

1. The template will deploy a bastion instance and an operator instance. The operator instance will have access to the OKE cluster. You can connect to the operator instance via SSH with

```
ssh_to_operator = "ssh -o ProxyCommand='ssh -W %h:%p -i <path-to-private-key> opc@<bastion_ip>' -i <path-to-private-key> opc@<operator_ip>"
```

2. Verify you can see all nodes in the cluster:

```
kubectl get nodes
```

3. Copy the the hpc-fss-pv.yaml located in the OKE FSS PV folder and edit the following line:

```
volumeHandle to <FileSystemOCID>:<MountTargetIP>:<path>
where:
•	<FileSystemOCID> is the OCID of the file system defined in the File Storage service.
•	<MountTargetIP> is the IP address assigned to the mount target.
•	<path> is the mount path to the file system relative to the mount target IP address, starting with a slash.

```
4. Create a persistent volume

```
kubectl create -f hpc-fss-pv.yaml
```

5. Copy and Edit the hpc-fss-pvc.yaml and edit the line:
volumeName: hpc-fss-pv to have the correct name of the Persistent volume 

```
volumeName: <name of Persistent volume>
```

6. Create the peristent volume claim and make sure its bound:

```
$kubectl create -f hpc-fss-pv.yaml

$kubectl get pvc
```

